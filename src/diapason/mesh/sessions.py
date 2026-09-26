"""Device sessions: how a paired phone is recognised on the tailnet gateway.

26/09/2026, phase 2 of the mobile plan. The phone reaches the Mac through
``tailscale serve`` and a gateway socket; until now nothing represented "this
browser tab belongs to that paired device". The only credential a request
could carry was the local API key — a shared secret that anything holding it
can copy out of a WebView and replay forever, with no way to cut one device
off without cutting them all.

A session is the answer, in two stages:

* a **ticket**, minted only after the device has proved itself with a signed
  envelope. It is single-use and dies after 60 seconds: long enough for the
  WebView to POST it once, too short to be worth stealing from a log;
* a **session token**, obtained by spending the ticket. It lives 12 hours and
  travels only as an ``HttpOnly`` cookie, so the JavaScript never sees it.

Both are stored HASHED. A copy of ``mesh.db`` — a backup, a synced folder —
must not be a copy of the keys to the Mac.

What makes revocation real is not these tables but the join in
``verify_session``: the device must be ``TRUSTED`` at EVERY call. A cache of
"known good sessions" would turn a revocation into a suggestion.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import closing
from typing import Any

from diapason.mesh.registry import TRUST_TRUSTED, DeviceRegistry, MeshError, now_ms

__all__ = [
    "DeviceSessions",
    "SESSION_TTL_MS",
    "TICKET_TTL_MS",
    "SESSION_TOUCH_INTERVAL_MS",
]

# Twelve hours, renewed when the app comes back to the foreground (decided
# 25/09/2026). A day-long session would outlive a phone left unlocked on a
# café table overnight; an hour would ask the phone to re-sign every time
# the user glances at it, and each re-sign is a round trip over the tailnet.
SESSION_TTL_MS = 12 * 60 * 60 * 1000

# Sixty seconds: the ticket only has to survive one POST from the WebView,
# right after the phone received it. The signed envelope that mints it is
# itself valid 60 s at most — a ticket outliving its own proof would extend
# a replay window instead of closing it.
TICKET_TTL_MS = 60_000

# "Last activity" is shown on the Devices page, not used for any decision.
# Writing it on every request would turn each GET of the WebView into a
# write on mesh.db — the same file the beacon and the command queue write
# to. Once a minute is as precise as a human reads "vu il y a 3 min".
SESSION_TOUCH_INTERVAL_MS = 60_000

# A token or ticket is ~60 characters. Anything much longer is not one of
# ours, and hashing megabytes sent by a stranger is work we refuse to do.
_MAX_SECRET_LENGTH = 200

_SESSION_PREFIX = "diapason_session_"
_TICKET_PREFIX = "diapason_ticket_"


def _secret_hash(secret: str) -> str:
    """Sessions and tickets live hashed, exactly like pairing tokens.

    A plain SHA-256 is enough: the secrets carry 256 bits of entropy from
    ``secrets.token_urlsafe(32)``, so there is nothing to brute-force.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _readable_secret(value: Any, prefix: str) -> str | None:
    """The secret as a string, or None when it cannot possibly be ours."""
    if not isinstance(value, str):
        return None
    if len(value) > _MAX_SECRET_LENGTH or not value.startswith(prefix):
        return None
    return value


class DeviceSessions:
    """Sessions of paired devices, stored beside them in ``mesh.db``.

    The tables are created by ``DeviceRegistry`` (``_SCHEMA``), so that the
    foreign key to ``mesh_devices`` exists from the first open and ``forget``
    cascades. Every connection comes from the registry, which is the one
    place that turns ``PRAGMA foreign_keys`` on.
    """

    def __init__(self, registry: DeviceRegistry | None = None) -> None:
        self.registry = registry or DeviceRegistry()

    def _connect(self) -> sqlite3.Connection:
        # Borrowed on purpose: a second _connect here would be a second place
        # to forget PRAGMA foreign_keys=ON, and without it `forget()` leaves
        # orphan sessions that a re-pairing under the same id would inherit.
        return self.registry._connect()  # noqa: SLF001 - same package, one door

    # ── tickets ──────────────────────────────────────────────────────────

    def issue_ticket(self, device_id: str) -> dict[str, Any]:
        """Mint a single-use ticket for a device that has just proved itself.

        The caller has verified a signed envelope; this method still refuses
        a device that is not TRUSTED right now, because the envelope and the
        revocation may have crossed each other.
        """
        stamp = now_ms()
        ticket = f"{_TICKET_PREFIX}{secrets.token_urlsafe(32)}"
        expires = stamp + TICKET_TTL_MS
        with closing(self._connect()) as conn, conn:
            # Dead tickets and sessions are swept here, on the rare write,
            # rather than on every read: a table of spent secrets is a
            # liability, not a record.
            conn.execute(
                "DELETE FROM mesh_session_tickets "
                "WHERE expires_at_ms < ? OR redeemed_at_ms IS NOT NULL",
                (stamp,),
            )
            conn.execute("DELETE FROM mesh_sessions WHERE expires_at_ms < ?", (stamp,))
            cursor = conn.execute(
                "INSERT INTO mesh_session_tickets"
                "(ticket_hash, device_id, created_at_ms, expires_at_ms) "
                "SELECT ?, device_id, ?, ? FROM mesh_devices "
                "WHERE device_id=? AND trust_level=?",
                (_secret_hash(ticket), stamp, expires, device_id, TRUST_TRUSTED),
            )
            conn.commit()
        if cursor.rowcount != 1:
            raise MeshError("Cet appareil n'est pas autorisé sur cette machine.")
        return {
            "ticket": ticket,
            "expiresAtMs": expires,
            "expiresInSeconds": TICKET_TTL_MS // 1000,
        }

    def redeem_ticket(self, ticket: Any) -> dict[str, Any] | None:
        """Spend *ticket* once and open a session. None when it cannot be.

        The guard is the UPDATE itself: ``WHERE redeemed_at_ms IS NULL`` and
        the rowcount decide, inside one transaction, which of two concurrent
        redemptions wins. A SELECT-then-UPDATE would let both see an unspent
        ticket and both walk away with a session.
        """
        clean = _readable_secret(ticket, _TICKET_PREFIX)
        if clean is None:
            return None
        stamp = now_ms()
        token = f"{_SESSION_PREFIX}{secrets.token_urlsafe(32)}"
        expires = stamp + SESSION_TTL_MS
        with closing(self._connect()) as conn, conn:
            # IMMEDIATE takes the write lock before reading anything: in WAL
            # mode, a deferred transaction that read an old snapshot could
            # otherwise fail its upgrade with SQLITE_BUSY_SNAPSHOT, which the
            # busy timeout does not retry — a legitimate redemption would
            # then look like a spent ticket.
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE mesh_session_tickets SET redeemed_at_ms=? "
                "WHERE ticket_hash=? AND redeemed_at_ms IS NULL "
                "  AND expires_at_ms >= ? "
                "  AND device_id IN "
                "    (SELECT device_id FROM mesh_devices WHERE trust_level=?)",
                (stamp, _secret_hash(clean), stamp, TRUST_TRUSTED),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return None
            row = conn.execute(
                "SELECT device_id FROM mesh_session_tickets WHERE ticket_hash=?",
                (_secret_hash(clean),),
            ).fetchone()
            conn.execute(
                "INSERT INTO mesh_sessions"
                "(session_hash, device_id, created_at_ms, last_used_at_ms,"
                " expires_at_ms) VALUES (?,?,?,?,?)",
                (_secret_hash(token), row["device_id"], stamp, stamp, expires),
            )
            conn.commit()
        return {
            "sessionToken": token,
            "deviceId": row["device_id"],
            "expiresAtMs": expires,
            "maxAgeSeconds": SESSION_TTL_MS // 1000,
        }

    # ── sessions ─────────────────────────────────────────────────────────

    def verify_session(self, token: Any) -> dict[str, Any] | None:
        """The device behind *token*, or None. Asks the registry EVERY time.

        No cache, deliberately: the join on ``trust_level`` is what makes a
        revocation take effect on the very next request rather than whenever
        a cache would have expired.
        """
        clean = _readable_secret(token, _SESSION_PREFIX)
        if clean is None:
            return None
        stamp = now_ms()
        digest = _secret_hash(clean)
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT s.device_id, s.expires_at_ms, s.last_used_at_ms "
                "FROM mesh_sessions s JOIN mesh_devices d USING(device_id) "
                "WHERE s.session_hash=? AND d.trust_level=? AND s.expires_at_ms > ?",
                (digest, TRUST_TRUSTED, stamp),
            ).fetchone()
            if row is None:
                return None
            if row["last_used_at_ms"] + SESSION_TOUCH_INTERVAL_MS <= stamp:
                conn.execute(
                    "UPDATE mesh_sessions SET last_used_at_ms=? WHERE session_hash=?",
                    (stamp, digest),
                )
                conn.commit()
        return {"deviceId": row["device_id"], "expiresAtMs": row["expires_at_ms"]}

    def close_session(self, token: Any) -> bool:
        """End one session — the phone logging itself out. True if it existed."""
        clean = _readable_secret(token, _SESSION_PREFIX)
        if clean is None:
            return False
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "DELETE FROM mesh_sessions WHERE session_hash=?",
                (_secret_hash(clean),),
            )
            conn.commit()
        return cursor.rowcount > 0

    def close_device_sessions(self, device_id: str) -> int:
        """End every session and ticket of one device, without revoking it.

        Distinct from ``revoke`` on purpose: a phone left somewhere is logged
        out, but it stays paired and can open a new session with its key.
        """
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "DELETE FROM mesh_sessions WHERE device_id=?", (device_id,)
            )
            conn.execute(
                "DELETE FROM mesh_session_tickets WHERE device_id=?", (device_id,)
            )
            conn.commit()
        return cursor.rowcount

    def list_sessions(self, device_id: str) -> list[dict[str, Any]]:
        """Live sessions of one device, newest first. Never the token.

        ``sessionId`` is the first 16 hex characters of the stored hash: a
        name for the Devices page, from which neither the token nor the full
        hash can be recovered.
        """
        stamp = now_ms()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT session_hash, created_at_ms, last_used_at_ms, expires_at_ms "
                "FROM mesh_sessions WHERE device_id=? AND expires_at_ms > ? "
                "ORDER BY created_at_ms DESC",
                (device_id, stamp),
            ).fetchall()
        return [
            {
                "sessionId": str(row["session_hash"])[:16],
                "createdAtMs": row["created_at_ms"],
                "lastUsedAtMs": row["last_used_at_ms"],
                "expiresAtMs": row["expires_at_ms"],
            }
            for row in rows
        ]
