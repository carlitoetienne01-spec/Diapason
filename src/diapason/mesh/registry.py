"""The devices this installation knows, and what each is allowed to do.

The registry answers the three questions the domain cannot (spec §5): which
devices exist, what each one is, and whether it may still be listened to.
Succès remains the single source of truth for tasks and notes — nothing
here duplicates business data.

Pairing mirrors the mechanism Succès already proved in production: a
one-time invitation token, hashed at rest, short TTL, redeemed exactly once.
What the mesh adds is the exchange of PUBLIC KEYS, which is what later lets
a command be verified rather than merely accepted.

Trust is a state, not a flag (spec §5): UNTRUSTED → PENDING → TRUSTED →
REVOKED, and revocation is terminal — a revoked device is never silently
re-admitted by presenting the same key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from diapason.core.paths import get_data_dir
from diapason.mesh.capabilities import effective_capabilities

__all__ = [
    "MeshError",
    "DeviceRegistry",
    "PAIRING_TTL_MS",
    "TRUST_LEVELS",
]


class MeshError(RuntimeError):
    """A mesh operation the user must see explained, in French."""


PAIRING_TTL_MS = 10 * 60 * 1000  # ten minutes, as Succès already uses

TRUST_UNTRUSTED = "UNTRUSTED"
TRUST_PENDING = "PENDING"
TRUST_TRUSTED = "TRUSTED"
TRUST_REVOKED = "REVOKED"
TRUST_LEVELS = (TRUST_UNTRUSTED, TRUST_PENDING, TRUST_TRUSTED, TRUST_REVOKED)

_DEVICE_TYPES = frozenset({"DESKTOP", "LAPTOP", "PHONE", "TABLET", "BROWSER"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mesh_devices (
    device_id TEXT PRIMARY KEY,
    public_key TEXT NOT NULL,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    device_type TEXT NOT NULL,
    trust_level TEXT NOT NULL,
    declared_capabilities TEXT NOT NULL DEFAULT '[]',
    app_version TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    last_seen_at_ms INTEGER,
    revoked_at_ms INTEGER,
    app_state TEXT,
    transport TEXT,
    address TEXT
);
CREATE INDEX IF NOT EXISTS mesh_devices_trust_idx
    ON mesh_devices(trust_level, last_seen_at_ms);

CREATE TABLE IF NOT EXISTS mesh_pairings (
    token_hash TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    redeemed_at_ms INTEGER
);
PRAGMA user_version = 1;
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def _token_hash(token: str) -> str:
    """Tokens live hashed, exactly as Succès stores its pairing secrets."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean(value: Any, *, field: str, maximum: int, required: bool = True) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise MeshError(f"{field} est obligatoire.")
        return ""
    if len(text) > maximum:
        raise MeshError(f"{field} est trop long.")
    return text


class DeviceRegistry:
    """Devices known to this installation, in its own SQLite file."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or (get_data_dir() / "mesh.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)
            self._ensure_columns(conn)
            conn.commit()

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        """Additive migration for registries created before presence existed."""
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(mesh_devices)").fetchall()
        }
        for name in ("app_state", "transport", "address"):
            if name not in columns:
                conn.execute(f"ALTER TABLE mesh_devices ADD COLUMN {name} TEXT")
        # The watermark that makes a replayed beacon useless. Nullable, so a
        # registry that predates signed presence simply accepts the first one.
        if "last_beacon_at_ms" not in columns:
            conn.execute(
                "ALTER TABLE mesh_devices ADD COLUMN last_beacon_at_ms INTEGER"
            )

    def _connect(self) -> sqlite3.Connection:
        """Ouvre une connexion NEUVE, que l'appelant doit fermer lui-même.

        Toujours via ``with closing(self._connect()) as conn, conn:`` — car le
        gestionnaire de contexte d'une connexion sqlite3 ne gère QUE la
        transaction (commit en sortie, rollback sur exception) et ne ferme
        jamais rien. Un simple ``with self._connect()`` fuit donc un
        descripteur à chaque appel, jusqu'à « Too many open files » : le
        serveur reste vivant et lié à son port mais n'accepte plus aucune
        connexion, panne parfaitement silencieuse.

        L'ordre des deux gestionnaires est vital : dans ``with A, B:`` c'est B
        qui est quitté en premier, donc la transaction (``conn``) commit AVANT
        que ``closing`` ne ferme. L'inverse perdrait les écritures.
        """
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        # Entre l'ouverture et le retour, la connexion n'appartient à personne :
        # si un PRAGMA lève (base corrompue, disque plein, verrou exclusif), elle
        # n'atteint jamais le closing() de l'appelant et fuit exactement comme
        # avant le correctif. On la referme donc soi-même avant de relancer.
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
        except BaseException:
            conn.close()
            raise
        return conn

    # ── pairing ──────────────────────────────────────────────────────────

    def create_pairing(self, device_name: str) -> dict[str, Any]:
        """Open a one-time, short-lived invitation for a new device."""
        name = _clean(device_name, field="Le nom de l'appareil", maximum=80)
        token = f"diapason_mesh_{secrets.token_urlsafe(32)}"
        created = now_ms()
        expires = created + PAIRING_TTL_MS
        with closing(self._connect()) as conn, conn:
            # Expired and spent invitations are swept on each new one: an
            # unbounded table of dead secrets is a liability, not a record.
            conn.execute(
                "DELETE FROM mesh_pairings "
                "WHERE expires_at_ms < ? OR redeemed_at_ms IS NOT NULL",
                (created,),
            )
            conn.execute(
                "INSERT INTO mesh_pairings"
                "(token_hash,device_name,created_at_ms,expires_at_ms)"
                " VALUES (?,?,?,?)",
                (_token_hash(token), name, created, expires),
            )
            conn.commit()
        return {
            "pairingToken": token,
            "deviceName": name,
            "expiresAtMs": expires,
            "expiresInSeconds": PAIRING_TTL_MS // 1000,
        }

    def redeem_pairing(
        self,
        token: str,
        *,
        device_id: str,
        public_key_b64: str,
        name: str,
        platform: str,
        device_type: str = "DESKTOP",
        declared_capabilities: Sequence[str] | None = None,
        app_version: str = "",
    ) -> dict[str, Any]:
        """Spend an invitation and enrol the device that presented it.

        The invitation proves a human authorised THIS enrolment; the public
        key is what every later command will be checked against.
        """
        if not token.startswith("diapason_mesh_"):
            raise MeshError("Ce code d'appairage est invalide.")
        device_id = _clean(device_id, field="L'identifiant d'appareil", maximum=120)
        name = _clean(name, field="Le nom de l'appareil", maximum=80)
        platform = _clean(platform, field="La plateforme", maximum=40).upper()
        device_type = (device_type or "DESKTOP").strip().upper()
        if device_type not in _DEVICE_TYPES:
            raise MeshError(f"Le type d'appareil « {device_type} » est inconnu.")
        key = self._validate_public_key(public_key_b64)

        stamp = now_ms()
        with closing(self._connect()) as conn, conn:
            # Claim the invitation FIRST, and let the UPDATE be the test.
            #
            # Reading `redeemed_at_ms` and then writing it is two steps with a
            # gap, and sqlite3 opens its transaction only at the first write —
            # so two redemptions racing both read "unused" and both succeed,
            # enrolling two devices from one invitation. Worse than the extra
            # device is the silence: the legitimate one still succeeds, so the
            # « déjà utilisé » message that would have warned the user their
            # code was stolen never appears.
            #
            # Making the spend the guard is the pattern this module already
            # uses for nonces and for beacon watermarks: only one writer can
            # see the old value, so only one can win.
            claimed = conn.execute(
                "UPDATE mesh_pairings SET redeemed_at_ms=? "
                "WHERE token_hash=? AND redeemed_at_ms IS NULL "
                "  AND expires_at_ms >= ?",
                (stamp, _token_hash(token), stamp),
            )
            if claimed.rowcount != 1:
                # Say which of the three it was, since the user acts on it
                # differently: mistyped, already used, or waited too long.
                row = conn.execute(
                    "SELECT expires_at_ms, redeemed_at_ms FROM mesh_pairings "
                    "WHERE token_hash=?",
                    (_token_hash(token),),
                ).fetchone()
                if row is None:
                    raise MeshError("Ce code d'appairage est inconnu.")
                if row["redeemed_at_ms"] is not None:
                    raise MeshError("Ce code d'appairage a déjà été utilisé.")
                raise MeshError("Ce code d'appairage a expiré.")

            existing = conn.execute(
                "SELECT public_key, trust_level FROM mesh_devices WHERE device_id=?",
                (device_id,),
            ).fetchone()
            if existing is not None:
                # Revocation is terminal: presenting a fresh invitation must
                # not launder a device the user deliberately cut off.
                if existing["trust_level"] == TRUST_REVOKED:
                    raise MeshError(
                        "Cet appareil a été révoqué. Supprimez-le d'abord de "
                        "la liste des appareils pour pouvoir le réappairer."
                    )
                # A known device that turns up with a DIFFERENT key is either
                # a reinstall or an impostor; either way the human decides.
                if existing["public_key"] != key:
                    raise MeshError(
                        "Un appareil portant cet identifiant est déjà connu "
                        "avec une autre clé. Révoquez-le avant de le réappairer."
                    )

            conn.execute(
                """INSERT INTO mesh_devices
                   (device_id, public_key, name, platform, device_type,
                    trust_level, declared_capabilities, app_version,
                    created_at_ms, last_seen_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(device_id) DO UPDATE SET
                     name=excluded.name,
                     platform=excluded.platform,
                     device_type=excluded.device_type,
                     trust_level=excluded.trust_level,
                     declared_capabilities=excluded.declared_capabilities,
                     app_version=excluded.app_version,
                     last_seen_at_ms=excluded.last_seen_at_ms""",
                (
                    device_id,
                    key,
                    name,
                    platform,
                    device_type,
                    TRUST_TRUSTED,
                    json.dumps(sorted({str(c) for c in (declared_capabilities or [])})),
                    str(app_version or "")[:40],
                    stamp,
                    stamp,
                ),
            )
            conn.commit()
        return self.get(device_id)

    @staticmethod
    def _validate_public_key(public_key_b64: str) -> str:
        """Accept only a real Ed25519 public key, in canonical base64."""
        raw = _clean(public_key_b64, field="La clé publique", maximum=200)
        try:
            decoded = base64.b64decode(raw, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise MeshError("La clé publique est illisible.") from exc
        if len(decoded) != 32:
            raise MeshError("La clé publique n'a pas la taille attendue (Ed25519).")
        # Re-encode so one key always has exactly one stored spelling.
        return base64.b64encode(decoded).decode("ascii")

    # ── reading ──────────────────────────────────────────────────────────

    def get(self, device_id: str) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM mesh_devices WHERE device_id=?", (device_id,)
            ).fetchone()
        if row is None:
            raise MeshError("Cet appareil n'est pas enregistré.")
        return self._serialize(row)

    def find(self, device_id: str) -> dict[str, Any] | None:
        try:
            return self.get(device_id)
        except MeshError:
            return None

    def list_devices(self, *, include_revoked: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM mesh_devices"
        if not include_revoked:
            query += f" WHERE trust_level != '{TRUST_REVOKED}'"
        query += " ORDER BY created_at_ms"
        with closing(self._connect()) as conn:
            rows = conn.execute(query).fetchall()
        return [self._serialize(row) for row in rows]

    def public_key_of(self, device_id: str) -> bytes | None:
        """The key a command from this device must verify against.

        Returns None for unknown OR revoked devices, so a caller cannot
        accidentally verify a signature from a device that was cut off.
        """
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT public_key, trust_level FROM mesh_devices WHERE device_id=?",
                (device_id,),
            ).fetchone()
        if row is None or row["trust_level"] != TRUST_TRUSTED:
            return None
        return base64.b64decode(row["public_key"])

    # ── writing ──────────────────────────────────────────────────────────

    def heartbeat(
        self,
        device_id: str,
        *,
        app_state: str = "",
        transport: str = "",
        address: str = "",
    ) -> dict[str, Any]:
        """Record that a TRUSTED device is alive right now.

        Restricted to trusted devices on purpose: a revoked one must not be
        able to make itself look reachable again simply by keeping a timer
        running.
        """
        # The address is learned from the heartbeat rather than fixed at
        # pairing: a laptop changes network, and a stale address is worse
        # than none — it sends commands into the void.
        clean_address = str(address or "").strip()[:200]
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE mesh_devices SET last_seen_at_ms=?, app_state=?, "
                "transport=?, address=COALESCE(NULLIF(?,''), address) "
                "WHERE device_id=? AND trust_level=?",
                (
                    now_ms(),
                    str(app_state or "")[:40] or None,
                    str(transport or "")[:40] or None,
                    clean_address,
                    device_id,
                    TRUST_TRUSTED,
                ),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise MeshError("Cet appareil n'est pas autorisé à signaler sa présence.")
        return self.get(device_id)

    def heartbeat_signed(
        self,
        device_id: str,
        *,
        app_state: str = "",
        transport: str = "",
        address: str = "",
        app_version: str = "",
        sent_at_ms: int,
    ) -> dict[str, Any] | None:
        """Record presence claimed by the device itself, once per timestamp.

        Returns ``None`` when the beacon is not strictly newer than the last
        one accepted — which is what a replay looks like. The comparison and
        the write are one UPDATE on purpose: two beacons arriving together
        cannot both see the old watermark, so only one can win.
        """
        clean_address = str(address or "").strip()[:200]
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE mesh_devices SET last_seen_at_ms=?, last_beacon_at_ms=?, "
                "app_state=?, transport=?, "
                "address=COALESCE(NULLIF(?,''), address), "
                "app_version=COALESCE(NULLIF(?,''), app_version) "
                "WHERE device_id=? AND trust_level=? "
                "  AND (last_beacon_at_ms IS NULL OR last_beacon_at_ms < ?)",
                (
                    now_ms(),
                    int(sent_at_ms),
                    str(app_state or "")[:40] or None,
                    str(transport or "")[:40] or None,
                    clean_address,
                    str(app_version or "")[:40],
                    device_id,
                    TRUST_TRUSTED,
                    int(sent_at_ms),
                ),
            )
            conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get(device_id)

    def touch(self, device_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE mesh_devices SET last_seen_at_ms=? WHERE device_id=?",
                (now_ms(), device_id),
            )
            conn.commit()

    def rename(self, device_id: str, name: str) -> dict[str, Any]:
        clean = _clean(name, field="Le nom de l'appareil", maximum=80)
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE mesh_devices SET name=? WHERE device_id=?", (clean, device_id)
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise MeshError("Cet appareil n'est pas enregistré.")
        return self.get(device_id)

    def declare_capabilities(
        self, device_id: str, capabilities: Iterable[str]
    ) -> dict[str, Any]:
        """Record what a device CLAIMS. What it gets is computed on read."""
        payload = json.dumps(
            sorted({str(c).strip() for c in capabilities if str(c).strip()})
        )
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE mesh_devices SET declared_capabilities=?, last_seen_at_ms=? "
                "WHERE device_id=? AND trust_level=?",
                (payload, now_ms(), device_id, TRUST_TRUSTED),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise MeshError("Cet appareil n'est pas autorisé à déclarer ses capacités.")
        return self.get(device_id)

    def revoke(self, device_id: str) -> dict[str, Any]:
        """Cut a device off. Terminal until the user deletes it outright."""
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE mesh_devices SET trust_level=?, revoked_at_ms=? "
                "WHERE device_id=?",
                (TRUST_REVOKED, now_ms(), device_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise MeshError("Cet appareil n'est pas enregistré.")
        return self.get(device_id)

    def forget(self, device_id: str) -> None:
        """Delete a device outright — the only way back from revocation."""
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM mesh_devices WHERE device_id=?", (device_id,))
            conn.commit()

    # ── serialisation ────────────────────────────────────────────────────

    @staticmethod
    def _serialize(row: Mapping[str, Any]) -> dict[str, Any]:
        try:
            declared = json.loads(row["declared_capabilities"] or "[]")
        except ValueError:
            declared = []
        platform = str(row["platform"])
        return {
            "deviceId": row["device_id"],
            "publicKey": row["public_key"],
            "name": row["name"],
            "platform": platform,
            "deviceType": row["device_type"],
            "trustLevel": row["trust_level"],
            # Both are exposed on purpose: the difference between them is
            # exactly what a user needs to understand why a phone cannot run
            # an automation it happens to advertise.
            "declaredCapabilities": list(declared),
            "capabilities": list(effective_capabilities(platform, declared)),
            "appVersion": row["app_version"],
            "createdAtMs": row["created_at_ms"],
            "lastSeenAtMs": row["last_seen_at_ms"],
            "revokedAtMs": row["revoked_at_ms"],
            "appState": row["app_state"] if "app_state" in row.keys() else None,
            "transport": row["transport"] if "transport" in row.keys() else None,
            "address": row["address"] if "address" in row.keys() else None,
        }
