"""Secure, local-first replication for the native Succès workspace.

The transport is deliberately separate from the data model: the Mac keeps
working offline, every mutation remains in the immutable operation log, and a
paired client exchanges batches using cursors.  Pairing and peer credentials
are stored only as SHA-256 hashes.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from diapason.succes.continuity import (
    QUOTE_CATEGORIES,
    SuccesContinuityStore,
)
from diapason.succes.dates import normalize_time
from diapason.succes.relay import normalize_relay_url, relay_post
from diapason.succes.store import (
    MAX_SUBTASK_DEPTH,
    PRIORITIES,
    SuccesError,
    _clean_text,
    _safe_timestamp,
    _validate_iso_date,
    now_ms,
)
from diapason.succes.workspace import (
    HABIT_FREQUENCIES,
    _color,
    _month_slots,
    _weekly_days,
)

MAX_SYNC_BATCH = 500
PAIRING_TTL_MS = 10 * 60 * 1000
_META_RELAY_URL = "sync_relay_url"
_META_GUEST_TOKEN = "sync_guest_token"
_META_GUEST_PEER_ID = "sync_guest_peer_id"
_META_GUEST_SERVER_ID = "sync_guest_server_device_id"
_META_GUEST_NAME = "sync_guest_device_name"
_META_GUEST_PULL = "sync_guest_pull_cursor"
_META_GUEST_PUSH = "sync_guest_push_cursor"
_META_LAST_SYNC_AT = "sync_last_at_ms"
_META_LAST_SYNC_ERROR = "sync_last_error"
_GUEST_META_KEYS = (
    _META_GUEST_TOKEN,
    _META_GUEST_PEER_ID,
    _META_GUEST_SERVER_ID,
    _META_GUEST_NAME,
    _META_GUEST_PULL,
    _META_GUEST_PUSH,
)
SYNC_ENTITIES = frozenset(
    {
        "tasks",
        "subtasks",
        "projects",
        "habits",
        "habit_logs",
        "notes",
        "todo_templates",
        "quotes",
    }
)

_SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS succes_sync_pairings (
    token_hash TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    redeemed_at_ms INTEGER
);
CREATE TABLE IF NOT EXISTS succes_sync_peers (
    id TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at_ms INTEGER NOT NULL,
    last_seen_at_ms INTEGER,
    last_pull_cursor INTEGER NOT NULL DEFAULT 0,
    last_push_at_ms INTEGER,
    revoked_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS succes_sync_peers_active_idx
    ON succes_sync_peers(revoked_at_ms, last_seen_at_ms);
CREATE TABLE IF NOT EXISTS succes_sync_clocks (
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    op_id TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(entity, entity_id)
);
CREATE TABLE IF NOT EXISTS succes_sync_tombstones (
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    deleted_at_ms INTEGER NOT NULL,
    op_id TEXT NOT NULL,
    PRIMARY KEY(entity, entity_id)
);
PRAGMA user_version = 4;
"""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clock_wins(timestamp_ms: int, op_id: str, current: sqlite3.Row | None) -> bool:
    if current is None:
        return True
    current_clock = (int(current["timestamp_ms"]), str(current["op_id"]))
    return (timestamp_ms, op_id) > current_clock


class SuccesSyncStore(SuccesContinuityStore):
    """Continuity store extended with authenticated operation replication."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__(db_path)
        with self._connect() as conn:
            conn.executescript(_SYNC_SCHEMA)
            self._ensure_peer_columns(conn)
            conn.execute(
                "INSERT OR IGNORE INTO succes_meta(key,value) "
                "VALUES('sync_clock_cursor','0')"
            )
            self._refresh_local_clocks(conn)
            conn.commit()

    @staticmethod
    def _ensure_peer_columns(conn: sqlite3.Connection) -> None:
        """Additive migration: bind each peer to the device it authors as.

        Nullable on purpose — existing pairs predate the binding and learn
        their device on the next exchange rather than being locked out.
        """
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(succes_sync_peers)").fetchall()
        }
        if "device_id" not in columns:
            conn.execute("ALTER TABLE succes_sync_peers ADD COLUMN device_id TEXT")

    # Pairing and peer credentials -----------------------------------

    def create_pairing(self, device_name: str) -> dict[str, Any]:
        clean_name = _clean_text(
            device_name,
            field="Le nom de l'appareil",
            maximum=80,
            required=True,
        )
        token = f"diapason_pair_{secrets.token_urlsafe(32)}"
        created = now_ms()
        expires = created + PAIRING_TTL_MS
        with self._transaction() as conn:
            conn.execute(
                "DELETE FROM succes_sync_pairings WHERE expires_at_ms<? "
                "OR redeemed_at_ms IS NOT NULL",
                (created,),
            )
            conn.execute(
                """INSERT INTO succes_sync_pairings
                   (token_hash,device_name,created_at_ms,expires_at_ms)
                   VALUES (?,?,?,?)""",
                (_token_hash(token), clean_name, created, expires),
            )
        return {
            "pairingToken": token,
            "deviceName": clean_name,
            "expiresAtMs": expires,
            "expiresInSeconds": PAIRING_TTL_MS // 1000,
        }

    def verify_pairing_token(self, token: str) -> bool:
        if not token.startswith("diapason_pair_"):
            return False
        with self._connect() as conn:
            row = conn.execute(
                """SELECT expires_at_ms,redeemed_at_ms
                   FROM succes_sync_pairings WHERE token_hash=?""",
                (_token_hash(token),),
            ).fetchone()
        return bool(
            row
            and row["redeemed_at_ms"] is None
            and int(row["expires_at_ms"]) >= now_ms()
        )

    def redeem_pairing(self, token: str) -> dict[str, Any]:
        timestamp = now_ms()
        peer_token = f"diapason_sync_{secrets.token_urlsafe(40)}"
        peer_id = f"peer_{secrets.token_hex(10)}"
        with self._transaction() as conn:
            pairing = conn.execute(
                """SELECT * FROM succes_sync_pairings
                   WHERE token_hash=? AND redeemed_at_ms IS NULL
                   AND expires_at_ms>=?""",
                (_token_hash(token), timestamp),
            ).fetchone()
            if pairing is None:
                raise SuccesError(
                    "Ce code d'appairage est invalide, expiré ou déjà utilisé."
                )
            conn.execute(
                "UPDATE succes_sync_pairings SET redeemed_at_ms=? WHERE token_hash=?",
                (timestamp, _token_hash(token)),
            )
            conn.execute(
                """INSERT INTO succes_sync_peers
                   (id,device_name,token_hash,created_at_ms,last_seen_at_ms)
                   VALUES (?,?,?,?,?)""",
                (
                    peer_id,
                    pairing["device_name"],
                    _token_hash(peer_token),
                    timestamp,
                    timestamp,
                ),
            )
        return {
            "peerId": peer_id,
            "deviceName": pairing["device_name"],
            "syncToken": peer_token,
            "serverDeviceId": self.device_id(),
        }

    def peer_for_token(self, token: str) -> dict[str, Any] | None:
        if not token.startswith("diapason_sync_"):
            return None
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id,device_name,created_at_ms,last_seen_at_ms,
                          last_pull_cursor,last_push_at_ms
                   FROM succes_sync_peers
                   WHERE token_hash=? AND revoked_at_ms IS NULL""",
                (_token_hash(token),),
            ).fetchone()
        return dict(row) if row is not None else None

    def verify_sync_token(self, token: str) -> bool:
        return self.peer_for_token(token) is not None

    def revoke_peer(self, peer_id: str) -> bool:
        with self._transaction() as conn:
            result = conn.execute(
                "UPDATE succes_sync_peers SET revoked_at_ms=? "
                "WHERE id=? AND revoked_at_ms IS NULL",
                (now_ms(), peer_id),
            )
        return bool(result.rowcount)

    def list_peers(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id,device_name,created_at_ms,last_seen_at_ms,
                          last_pull_cursor,last_push_at_ms
                   FROM succes_sync_peers WHERE revoked_at_ms IS NULL
                   ORDER BY COALESCE(last_seen_at_ms,created_at_ms) DESC"""
            ).fetchall()
        return [
            {
                "id": row["id"],
                "deviceName": row["device_name"],
                "createdAtMs": row["created_at_ms"],
                "lastSeenAtMs": row["last_seen_at_ms"],
                "lastPullCursor": row["last_pull_cursor"],
                "lastPushAtMs": row["last_push_at_ms"],
            }
            for row in rows
        ]

    # Replication ----------------------------------------------------

    @staticmethod
    def _effective_entity(
        entity: str, entity_id: str, payload: Mapping[str, Any]
    ) -> tuple[str, str]:
        if entity == "subtasks":
            task_id = str(payload.get("id") or "")
            return ("tasks", task_id or entity_id)
        return entity, entity_id

    def _refresh_local_clocks(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT value FROM succes_meta WHERE key='sync_clock_cursor'"
        ).fetchone()
        cursor = int(row["value"]) if row else 0
        operations = conn.execute(
            "SELECT * FROM succes_operations WHERE seq>? ORDER BY seq", (cursor,)
        ).fetchall()
        for operation in operations:
            try:
                payload = json.loads(operation["payload_json"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, Mapping):
                payload = {}
            entity, entity_id = self._effective_entity(
                str(operation["entity"]),
                str(operation["entity_id"]),
                payload,
            )
            if entity not in SYNC_ENTITIES or not entity_id:
                continue
            self._set_clock(
                conn,
                entity,
                entity_id,
                int(operation["timestamp_ms"]),
                str(operation["op_id"]),
                str(operation["kind"]) == "delete",
            )
        if operations:
            conn.execute(
                "UPDATE succes_meta SET value=? WHERE key='sync_clock_cursor'",
                (str(operations[-1]["seq"]),),
            )

    @staticmethod
    def _set_clock(
        conn: sqlite3.Connection,
        entity: str,
        entity_id: str,
        timestamp_ms: int,
        op_id: str,
        deleted: bool,
    ) -> None:
        current = conn.execute(
            "SELECT * FROM succes_sync_clocks WHERE entity=? AND entity_id=?",
            (entity, entity_id),
        ).fetchone()
        if not _clock_wins(timestamp_ms, op_id, current):
            return
        conn.execute(
            """INSERT INTO succes_sync_clocks
               (entity,entity_id,timestamp_ms,op_id,deleted)
               VALUES (?,?,?,?,?) ON CONFLICT(entity,entity_id) DO UPDATE SET
               timestamp_ms=excluded.timestamp_ms,op_id=excluded.op_id,
               deleted=excluded.deleted""",
            (entity, entity_id, timestamp_ms, op_id, int(deleted)),
        )

    def exchange(
        self,
        peer_id: str,
        *,
        after: int,
        operations: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if len(operations) > MAX_SYNC_BATCH:
            raise SuccesError(
                "Un lot de synchronisation ne peut pas dépasser "
                f"{MAX_SYNC_BATCH} opérations."
            )
        applied = self.apply_remote_operations(peer_id, operations)
        outgoing = self.list_operations(after=max(0, int(after)), limit=MAX_SYNC_BATCH)
        timestamp = now_ms()
        with self._transaction() as conn:
            conn.execute(
                """UPDATE succes_sync_peers SET last_seen_at_ms=?,
                   last_pull_cursor=?,last_push_at_ms=? WHERE id=?
                   AND revoked_at_ms IS NULL""",
                (timestamp, max(0, int(after)), timestamp, peer_id),
            )
        return {"received": applied, **outgoing}

    def apply_remote_operations(
        self, peer_id: str, operations: Sequence[Mapping[str, Any]]
    ) -> dict[str, int]:
        if len(operations) > MAX_SYNC_BATCH:
            raise SuccesError("Le lot reçu est trop volumineux.")
        stats = {"applied": 0, "stale": 0, "duplicate": 0}
        # Habits must exist before their daily log because SQLite enforces the FK.
        ordered = sorted(
            operations, key=lambda op: str(op.get("entity")) == "habit_logs"
        )
        with self._transaction() as conn:
            peer = conn.execute(
                "SELECT 1 FROM succes_sync_peers WHERE id=? AND revoked_at_ms IS NULL",
                (peer_id,),
            ).fetchone()
            if peer is None:
                raise SuccesError("Cet appareil n'est plus autorisé à synchroniser.")
            # Bind peer ↔ device on first use: the pairing token proved the
            # authorization, the first device id it authors becomes the
            # identity it is held to from then on. Learning it (rather than
            # demanding it at pairing time) keeps every existing pair working
            # across the upgrade.
            bound = self._peer_device_id(conn, peer_id)
            authored = self._authored_device_id(conn, ordered)
            if bound is None and authored is not None:
                conn.execute(
                    "UPDATE succes_sync_peers SET device_id=? WHERE id=?",
                    (authored, peer_id),
                )
                bound = authored
            self._refresh_local_clocks(conn)
            for raw in ordered:
                result = self._apply_operation(conn, raw, expected_device_id=bound)
                stats[result] += 1
            conn.execute(
                "UPDATE succes_sync_peers SET last_seen_at_ms=? WHERE id=?",
                (now_ms(), peer_id),
            )
        return stats

    @staticmethod
    def _peer_device_id(conn: sqlite3.Connection, peer_id: str) -> str | None:
        row = conn.execute(
            "SELECT device_id FROM succes_sync_peers WHERE id=?", (peer_id,)
        ).fetchone()
        value = None if row is None else row["device_id"]
        return str(value) if value else None

    @staticmethod
    def _authored_device_id(
        conn: sqlite3.Connection, operations: Sequence[Mapping[str, Any]]
    ) -> str | None:
        """The device id of the first operation this peer genuinely authors.

        Relayed history (op ids we already hold) says nothing about who is
        speaking, so it is skipped — otherwise the very first exchange, which
        echoes our own operations back, would bind the peer to US.
        """
        for raw in operations:
            if not isinstance(raw, Mapping):
                continue
            op_id = str(raw.get("opId") or "")
            device_id = str(raw.get("deviceId") or "")
            if not op_id or not device_id:
                continue
            known = conn.execute(
                "SELECT 1 FROM succes_operations WHERE op_id=?", (op_id,)
            ).fetchone()
            if known is None:
                return device_id
        return None

    def apply_inbound_operations(
        self, operations: Sequence[Mapping[str, Any]]
    ) -> dict[str, int]:
        """Apply a trusted exchange bundle locally (guest side, no peer row)."""
        if len(operations) > MAX_SYNC_BATCH:
            raise SuccesError("Le lot reçu est trop volumineux.")
        stats = {"applied": 0, "stale": 0, "duplicate": 0}
        ordered = sorted(
            operations, key=lambda op: str(op.get("entity")) == "habit_logs"
        )
        with self._transaction() as conn:
            self._refresh_local_clocks(conn)
            for raw in ordered:
                result = self._apply_operation(conn, raw)
                stats[result] += 1
        return stats

    def _meta_get(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM succes_meta WHERE key=?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def _meta_set(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO succes_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def _meta_delete(self, conn: sqlite3.Connection, key: str) -> None:
        conn.execute("DELETE FROM succes_meta WHERE key=?", (key,))

    def relay_url(self) -> str:
        return (self._meta_get(_META_RELAY_URL) or "").strip()

    def set_relay_url(self, url: str) -> dict[str, Any]:
        normalized = normalize_relay_url(url)
        with self._transaction() as conn:
            self._meta_set(conn, _META_RELAY_URL, normalized)
        return self.sync_status()

    def clear_relay_url(self) -> dict[str, Any]:
        with self._transaction() as conn:
            self._meta_delete(conn, _META_RELAY_URL)
        return self.sync_status()

    def guest_session(self) -> dict[str, Any] | None:
        token = self._meta_get(_META_GUEST_TOKEN)
        if not token:
            return None
        return {
            "peerId": self._meta_get(_META_GUEST_PEER_ID) or "",
            "deviceName": self._meta_get(_META_GUEST_NAME) or "",
            "serverDeviceId": self._meta_get(_META_GUEST_SERVER_ID) or "",
            "pullCursor": int(self._meta_get(_META_GUEST_PULL) or 0),
            "pushCursor": int(self._meta_get(_META_GUEST_PUSH) or 0),
            "hasToken": True,
        }

    def clear_guest_session(self) -> dict[str, Any]:
        with self._transaction() as conn:
            for key in _GUEST_META_KEYS:
                self._meta_delete(conn, key)
            self._meta_delete(conn, _META_LAST_SYNC_ERROR)
        return self.sync_status()

    def join_remote(
        self,
        pairing_token: str,
        *,
        relay_url: str | None = None,
        device_name: str = "",
    ) -> dict[str, Any]:
        """Redeem a host invitation through the configured (or provided) relay."""
        token = _clean_text(
            pairing_token,
            field="Le code d'appairage",
            maximum=160,
            required=True,
        )
        if not token.startswith("diapason_pair_"):
            raise SuccesError("Ce code d'appairage n'a pas un format reconnu.")
        base = normalize_relay_url(relay_url or self.relay_url())
        remote = relay_post(base, "/v1/succes/sync/pair", {"pairingToken": token})
        sync_token = str(remote.get("syncToken") or "")
        peer_id = str(remote.get("peerId") or "")
        if not sync_token.startswith("diapason_sync_") or not peer_id:
            raise SuccesError("Le relais n'a pas renvoyé d'identifiants de sync valides.")
        name = _clean_text(
            device_name or remote.get("deviceName") or "Appareil distant",
            field="Le nom de l'appareil",
            maximum=80,
            required=True,
        )
        with self._transaction() as conn:
            self._meta_set(conn, _META_RELAY_URL, base)
            self._meta_set(conn, _META_GUEST_TOKEN, sync_token)
            self._meta_set(conn, _META_GUEST_PEER_ID, peer_id)
            self._meta_set(
                conn, _META_GUEST_SERVER_ID, str(remote.get("serverDeviceId") or "")
            )
            self._meta_set(conn, _META_GUEST_NAME, name)
            self._meta_set(conn, _META_GUEST_PULL, "0")
            self._meta_set(conn, _META_GUEST_PUSH, "0")
            self._meta_delete(conn, _META_LAST_SYNC_ERROR)
        status = self.sync_status()
        status["joined"] = {
            "peerId": peer_id,
            "deviceName": name,
            "serverDeviceId": remote.get("serverDeviceId"),
            "relayUrl": base,
        }
        return status

    def run_exchange(self) -> dict[str, Any]:
        """Push local ops and pull host ops through the configured relay (guest)."""
        base = self.relay_url()
        token = self._meta_get(_META_GUEST_TOKEN)
        if not base or not token:
            raise SuccesError(
                "Configurez d'abord un relais et rejoignez un appareil avec un code."
            )
        pull_cursor = int(self._meta_get(_META_GUEST_PULL) or 0)
        push_cursor = int(self._meta_get(_META_GUEST_PUSH) or 0)
        bundle = self.list_operations(after=push_cursor, limit=MAX_SYNC_BATCH)
        outbound = [
            {
                "opId": op["opId"],
                "deviceId": op["deviceId"],
                "entity": op["entity"],
                "entityId": op["entityId"],
                "kind": op["kind"],
                "request": op["request"],
                "payload": op["payload"],
                "timestampMs": op["timestampMs"],
            }
            for op in bundle["operations"]
            if op["deviceId"] == self.device_id()
        ]
        try:
            remote = relay_post(
                base,
                "/v1/succes/sync/exchange",
                {
                    "peerToken": token,
                    "cursor": pull_cursor,
                    "operations": outbound,
                },
            )
        except SuccesError as exc:
            with self._transaction() as conn:
                self._meta_set(conn, _META_LAST_SYNC_ERROR, str(exc))
            raise

        inbound = remote.get("operations")
        if not isinstance(inbound, list):
            inbound = []
        received = self.apply_inbound_operations(inbound)
        next_pull = int(remote.get("cursor") or pull_cursor)
        if bundle["operations"]:
            next_push = int(bundle["operations"][-1]["cursor"])
        else:
            next_push = int(bundle["cursor"])
        timestamp = now_ms()
        with self._transaction() as conn:
            self._meta_set(conn, _META_GUEST_PULL, str(next_pull))
            self._meta_set(conn, _META_GUEST_PUSH, str(next_push))
            self._meta_set(conn, _META_LAST_SYNC_AT, str(timestamp))
            self._meta_delete(conn, _META_LAST_SYNC_ERROR)
        return {
            "pushed": len(outbound),
            "pulled": len(inbound),
            "received": received,
            "pullCursor": next_pull,
            "pushCursor": next_push,
            "hasMore": bool(remote.get("hasMore")) or bool(bundle.get("hasMore")),
            "syncedAtMs": timestamp,
            "status": self.sync_status(),
        }

    def _apply_operation(
        self,
        conn: sqlite3.Connection,
        raw: Mapping[str, Any],
        *,
        expected_device_id: str | None = None,
    ) -> str:
        if not isinstance(raw, Mapping):
            raise SuccesError("Une opération de synchronisation est illisible.")
        op_id = _clean_text(
            raw.get("opId"),
            field="L'identifiant d'opération",
            maximum=200,
            required=True,
        )
        device_id = _clean_text(
            raw.get("deviceId"),
            field="L'identifiant d'appareil",
            maximum=120,
            required=True,
        )
        entity = str(raw.get("entity") or "")
        entity_id = _clean_text(
            raw.get("entityId"),
            field="L'identifiant de donnée",
            maximum=300,
            required=True,
        )
        kind = str(raw.get("kind") or "")
        if entity not in SYNC_ENTITIES:
            raise SuccesError(
                f"Le type synchronisé « {entity} » n'est pas pris en charge."
            )
        if kind not in {"upsert", "delete", "habitlog_set"}:
            raise SuccesError(f"L'opération « {kind} » n'est pas prise en charge.")
        payload = raw.get("payload")
        request = raw.get("request") or {}
        if not isinstance(payload, Mapping) or not isinstance(request, Mapping):
            raise SuccesError(
                "Le contenu de l'opération de synchronisation est invalide."
            )
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        existing = conn.execute(
            "SELECT device_id,entity,entity_id,kind,payload_json "
            "FROM succes_operations WHERE op_id=?",
            (op_id,),
        ).fetchone()
        if existing is not None:
            previous = json.dumps(
                json.loads(existing["payload_json"]),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if (
                previous != canonical_payload
                or existing["device_id"] != device_id
                or existing["entity"] != entity
                or existing["entity_id"] != entity_id
                or existing["kind"] != kind
            ):
                raise SuccesError(
                    "Un identifiant d'opération reçu existe déjà avec un autre contenu."
                )
            return "duplicate"

        # ── Attribution: a peer may RELAY history it received (those arrive as
        # duplicates above and never reach this point), but it may not AUTHOR a
        # brand-new operation in another device's name. The device id used to be
        # taken on trust from the body, so an authenticated peer could forge
        # history attributed to any device — and every later guarantee (audit,
        # revocation, conflict arbitration) keys on that field.
        if expected_device_id is not None and device_id != expected_device_id:
            raise SuccesError(
                "Une opération inédite prétend venir d'un autre appareil que "
                "celui qui l'envoie."
            )

        timestamp = _safe_timestamp(raw.get("timestampMs"))
        effective_entity, effective_id = self._effective_entity(
            entity, entity_id, payload
        )
        current = conn.execute(
            "SELECT * FROM succes_sync_clocks WHERE entity=? AND entity_id=?",
            (effective_entity, effective_id),
        ).fetchone()
        wins = _clock_wins(timestamp, op_id, current)
        if wins:
            if kind == "delete":
                self._apply_delete(
                    conn, effective_entity, effective_id, timestamp, op_id
                )
            else:
                self._apply_upsert(
                    conn, effective_entity, effective_id, payload, timestamp
                )
                conn.execute(
                    "DELETE FROM succes_sync_tombstones WHERE entity=? AND entity_id=?",
                    (effective_entity, effective_id),
                )
            self._set_clock(
                conn,
                effective_entity,
                effective_id,
                timestamp,
                op_id,
                kind == "delete",
            )

        conn.execute(
            """INSERT INTO succes_operations
               (op_id,device_id,entity,entity_id,kind,request_json,payload_json,
                timestamp_ms,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                op_id,
                device_id,
                entity,
                entity_id,
                kind,
                self._canonical_json(request),
                json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":"), default=str
                ),
                timestamp,
                now_ms(),
            ),
        )
        return "applied" if wins else "stale"

    def _apply_delete(
        self,
        conn: sqlite3.Connection,
        entity: str,
        entity_id: str,
        timestamp: int,
        op_id: str,
    ) -> None:
        tables = {
            "tasks": "succes_tasks",
            "projects": "succes_projects",
            "habits": "succes_habits",
            "notes": "succes_notes",
            "todo_templates": "succes_task_templates",
            "quotes": "succes_quotes",
        }
        table = tables.get(entity)
        if table:
            conn.execute(
                f"UPDATE {table} SET deleted_at_ms=?,updated_at_ms=? WHERE id=?",
                (timestamp, timestamp, entity_id),
            )
            if entity == "tasks":
                conn.execute(
                    "UPDATE succes_subtasks SET deleted_at_ms=?,updated_at_ms=? "
                    "WHERE task_id=? AND deleted_at_ms IS NULL",
                    (timestamp, timestamp, entity_id),
                )
        elif entity == "habit_logs":
            habit_id, separator, log_date = entity_id.rpartition("_")
            if separator:
                conn.execute(
                    "DELETE FROM succes_habit_logs WHERE habit_id=? AND log_date=?",
                    (habit_id, log_date),
                )
        conn.execute(
            """INSERT INTO succes_sync_tombstones
               (entity,entity_id,deleted_at_ms,op_id) VALUES (?,?,?,?)
               ON CONFLICT(entity,entity_id) DO UPDATE SET
               deleted_at_ms=excluded.deleted_at_ms,op_id=excluded.op_id""",
            (entity, entity_id, timestamp, op_id),
        )

    def _apply_upsert(
        self,
        conn: sqlite3.Connection,
        entity: str,
        entity_id: str,
        payload: Mapping[str, Any],
        timestamp: int,
    ) -> None:
        if entity == "tasks":
            self._upsert_task(conn, entity_id, payload, timestamp)
        elif entity == "projects":
            self._upsert_project(conn, entity_id, payload, timestamp)
        elif entity == "habits":
            self._upsert_habit(conn, entity_id, payload, timestamp)
        elif entity == "habit_logs":
            self._upsert_habit_log(conn, entity_id, payload, timestamp)
        elif entity == "notes":
            self._upsert_note(conn, entity_id, payload, timestamp)
        elif entity == "todo_templates":
            self._upsert_template(conn, entity_id, payload, timestamp)
        elif entity == "quotes":
            self._upsert_quote(conn, entity_id, payload, timestamp)

    def _upsert_task(
        self, conn: sqlite3.Connection, task_id: str, data: Mapping[str, Any], ts: int
    ) -> None:
        title = _clean_text(
            data.get("title"), field="Le titre", maximum=200, required=True
        )
        priority = str(data.get("priority") or "medium").lower()
        if priority not in PRIORITIES:
            raise SuccesError("La priorité synchronisée n'est pas valide.")
        scheduled = _validate_iso_date(str(data.get("date") or ""))
        created = _validate_iso_date(
            str(data.get("createdAt") or date.today().isoformat()), "createdAt"
        )
        completed = _validate_iso_date(
            str(data.get("completedDate") or ""), "completedDate"
        )
        conn.execute(
            """INSERT INTO succes_tasks
               (id,title,done,priority,scheduled_date,scheduled_time,project_id,
                category,notes,emoji,template_id,group_id,order_index,created_date,
                completed_date,postponed_count,updated_at_ms,deleted_at_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title,done=excluded.done,
               priority=excluded.priority,scheduled_date=excluded.scheduled_date,
               scheduled_time=excluded.scheduled_time,project_id=excluded.project_id,
               category=excluded.category,notes=excluded.notes,emoji=excluded.emoji,
               template_id=excluded.template_id,group_id=excluded.group_id,
               order_index=excluded.order_index,created_date=excluded.created_date,
               completed_date=excluded.completed_date,
               postponed_count=excluded.postponed_count,
               updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL""",
            (
                task_id,
                title,
                int(bool(data.get("done"))),
                priority,
                scheduled,
                str(data.get("time") or "")[:20],
                str(data.get("projectId") or "")[:300],
                str(data.get("category") or "")[:100],
                _clean_text(data.get("notes"), field="Les notes", maximum=2000),
                str(data.get("emoji") or "")[:16],
                str(data.get("templateId") or "")[:300],
                str(data.get("groupId") or "")[:300],
                int(data.get("order") or 0),
                created,
                completed,
                max(0, int(data.get("postponedCount") or 0)),
                ts,
            ),
        )
        conn.execute(
            "UPDATE succes_subtasks SET deleted_at_ms=?,updated_at_ms=? "
            "WHERE task_id=? AND deleted_at_ms IS NULL",
            (ts, ts, task_id),
        )
        self._replace_subtasks(conn, task_id, data.get("subtasks"), ts)

    def _replace_subtasks(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        raw_nodes: Any,
        ts: int,
    ) -> None:
        nodes = raw_nodes if isinstance(raw_nodes, list) else []
        total = 0

        def visit(items: list[Any], parent_id: str | None, depth: int) -> None:
            nonlocal total
            if depth > MAX_SUBTASK_DEPTH:
                raise SuccesError("La hiérarchie synchronisée est trop profonde.")
            for order, raw in enumerate(items):
                if not isinstance(raw, Mapping):
                    raise SuccesError("Une sous-tâche synchronisée est illisible.")
                total += 1
                if total > 500:
                    raise SuccesError(
                        "Une tâche ne peut pas contenir plus de 500 sous-tâches."
                    )
                subtask_id = _clean_text(
                    raw.get("id"),
                    field="L'identifiant de sous-tâche",
                    maximum=300,
                    required=True,
                )
                title = _clean_text(
                    raw.get("title"), field="Le titre", maximum=200, required=True
                )
                children = (
                    raw.get("children") if isinstance(raw.get("children"), list) else []
                )
                conn.execute(
                    """INSERT INTO succes_subtasks
                       (id,task_id,parent_id,title,done,is_group,order_index,
                        updated_at_ms,deleted_at_ms)
                       VALUES (?,?,?,?,?,?,?,?,NULL) ON CONFLICT(id) DO UPDATE SET
                       task_id=excluded.task_id,parent_id=excluded.parent_id,
                       title=excluded.title,done=excluded.done,is_group=excluded.is_group,
                       order_index=excluded.order_index,updated_at_ms=excluded.updated_at_ms,
                       deleted_at_ms=NULL""",
                    (
                        subtask_id,
                        task_id,
                        parent_id,
                        title,
                        int(bool(raw.get("done"))),
                        int(bool(children)),
                        order,
                        ts,
                    ),
                )
                visit(children, subtask_id, depth + 1)

        visit(nodes, None, 1)

    def _upsert_project(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        data: Mapping[str, Any],
        ts: int,
    ) -> None:
        name = _clean_text(
            data.get("name"), field="Le projet", maximum=200, required=True
        )
        start = _validate_iso_date(str(data.get("startDate") or ""))
        end = _validate_iso_date(str(data.get("endDate") or ""))
        if start and end and end < start:
            raise SuccesError("Les dates du projet synchronisé sont incohérentes.")
        conn.execute(
            """INSERT INTO succes_projects
               (id,name,description,color,icon,start_date,end_date,created_date,
                updated_at_ms,deleted_at_ms) VALUES (?,?,?,?,?,?,?,?,?,NULL)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,
               description=excluded.description,color=excluded.color,icon=excluded.icon,
               start_date=excluded.start_date,end_date=excluded.end_date,
               created_date=excluded.created_date,updated_at_ms=excluded.updated_at_ms,
               deleted_at_ms=NULL""",
            (
                project_id,
                name,
                _clean_text(
                    data.get("description"), field="La description", maximum=4000
                ),
                _color(data.get("color")),
                str(data.get("icon") or "")[:16],
                start,
                end,
                str(data.get("createdAt") or date.today().isoformat())[:30],
                ts,
            ),
        )

    def _upsert_habit(
        self, conn: sqlite3.Connection, habit_id: str, data: Mapping[str, Any], ts: int
    ) -> None:
        frequency = str(data.get("frequency") or "daily").lower()
        if frequency not in HABIT_FREQUENCIES:
            raise SuccesError("La fréquence synchronisée n'est pas valide.")
        days = _weekly_days(data.get("weeklyDays"))
        slots = _month_slots(data.get("monthWeekSlots"))
        month_day = int(data.get("monthWeekDay") or 1)
        if not 0 <= month_day <= 6:
            raise SuccesError("Le jour mensuel synchronisé n'est pas valide.")
        start = _validate_iso_date(
            str(data.get("startDate") or date.today().isoformat())
        )
        end = _validate_iso_date(str(data.get("endDate") or ""))
        if end and end < start:
            raise SuccesError("Les dates de l'habitude synchronisée sont incohérentes.")
        try:
            reminder = normalize_time(str(data.get("reminderTime") or ""))
        except ValueError as exc:
            raise SuccesError(str(exc)) from exc
        conn.execute(
            """INSERT INTO succes_habits
               (id,name,icon,color,frequency,created_date,start_date,end_date,
                weekly_days_json,month_week_slots_json,month_week_day,
                reminder_time,updated_at_ms,deleted_at_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL) ON CONFLICT(id) DO UPDATE SET
               name=excluded.name,icon=excluded.icon,color=excluded.color,
               frequency=excluded.frequency,created_date=excluded.created_date,
               start_date=excluded.start_date,end_date=excluded.end_date,
               weekly_days_json=excluded.weekly_days_json,
               month_week_slots_json=excluded.month_week_slots_json,
               month_week_day=excluded.month_week_day,reminder_time=excluded.reminder_time,
               updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL""",
            (
                habit_id,
                _clean_text(
                    data.get("name"), field="L'habitude", maximum=200, required=True
                ),
                str(data.get("icon") or "")[:16],
                _color(data.get("color")),
                frequency,
                str(data.get("createdAt") or date.today().isoformat())[:30],
                start,
                end,
                json.dumps(days),
                json.dumps(slots),
                month_day,
                reminder,
                ts,
            ),
        )

    def _upsert_habit_log(
        self, conn: sqlite3.Connection, entity_id: str, data: Mapping[str, Any], ts: int
    ) -> None:
        habit_id = _clean_text(
            data.get("habitId"), field="L'habitude", maximum=300, required=True
        )
        log_date = _validate_iso_date(str(data.get("date") or ""))
        if entity_id != f"{habit_id}_{log_date}":
            raise SuccesError("L'identifiant du suivi d'habitude est incohérent.")
        if (
            conn.execute(
                "SELECT 1 FROM succes_habits WHERE id=? AND deleted_at_ms IS NULL",
                (habit_id,),
            ).fetchone()
            is None
        ):
            raise SuccesError("Le suivi reçu référence une habitude absente.")
        conn.execute(
            """INSERT INTO succes_habit_logs(habit_id,log_date,done,updated_at_ms)
               VALUES (?,?,?,?) ON CONFLICT(habit_id,log_date) DO UPDATE SET
               done=excluded.done,updated_at_ms=excluded.updated_at_ms""",
            (habit_id, log_date, int(bool(data.get("done"))), ts),
        )

    def _upsert_note(
        self, conn: sqlite3.Connection, note_id: str, data: Mapping[str, Any], ts: int
    ) -> None:
        content = str(data.get("content") or "")
        if len(content) > 100_000:
            raise SuccesError("La note synchronisée est trop longue.")
        title, _, meta = self._note_fields({**data, "title": data.get("title") or "Note"})
        conn.execute(
            """INSERT INTO succes_notes
               (id,title,content,created_at,updated_at,updated_at_ms,deleted_at_ms,
                page_format,page_background,font_family,doc_lang,color)
               VALUES (?,?,?,?,?,?,NULL,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
               title=excluded.title,content=excluded.content,
               created_at=excluded.created_at,updated_at=excluded.updated_at,
               updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL,
               page_format=excluded.page_format,
               page_background=excluded.page_background,
               font_family=excluded.font_family,doc_lang=excluded.doc_lang,
               color=excluded.color""",
            (
                note_id,
                title,
                content,
                str(data.get("createdAt") or date.today().isoformat())[:40],
                str(data.get("updatedAt") or date.today().isoformat())[:40],
                ts,
                meta["pageFormat"],
                meta["pageBackground"],
                meta["fontFamily"],
                meta["docLang"],
                meta["color"],
            ),
        )

    def _upsert_template(
        self,
        conn: sqlite3.Connection,
        template_id: str,
        data: Mapping[str, Any],
        ts: int,
    ) -> None:
        clean = self._validated_template(data)
        conn.execute(
            """INSERT INTO succes_task_templates
               (id,title,emoji,frequency,days_of_week_json,weekly_days_json,
                month_week_slots_json,month_week_dow,project_id,priority,
                template_kind,start_date,end_date,active,linked_habit_id,
                created_date,updated_at_ms,deleted_at_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title,emoji=excluded.emoji,
               frequency=excluded.frequency,days_of_week_json=excluded.days_of_week_json,
               weekly_days_json=excluded.weekly_days_json,
               month_week_slots_json=excluded.month_week_slots_json,
               month_week_dow=excluded.month_week_dow,project_id=excluded.project_id,
               priority=excluded.priority,template_kind=excluded.template_kind,
               start_date=excluded.start_date,end_date=excluded.end_date,
               active=excluded.active,linked_habit_id=excluded.linked_habit_id,
               created_date=excluded.created_date,updated_at_ms=excluded.updated_at_ms,
               deleted_at_ms=NULL""",
            (
                template_id,
                clean["title"],
                clean["emoji"],
                clean["frequency"],
                json.dumps(clean["daysOfWeek"]),
                json.dumps(clean["weeklyDays"]),
                json.dumps(clean["monthWeekSlots"]),
                clean["monthWeekDow"],
                clean["projectId"],
                clean["priority"],
                clean["templateKind"],
                clean["startDate"],
                clean["endDate"],
                int(clean["active"]),
                str(data.get("linkedHabitId") or "")[:300],
                str(data.get("createdAt") or date.today().isoformat())[:30],
                ts,
            ),
        )

    def _upsert_quote(
        self, conn: sqlite3.Connection, quote_id: str, data: Mapping[str, Any], ts: int
    ) -> None:
        category = str(data.get("category") or "autre").lower()
        if category not in QUOTE_CATEGORIES:
            category = "autre"
        conn.execute(
            """INSERT INTO succes_quotes
               (id,text,author,category,updated_at_ms,deleted_at_ms)
               VALUES (?,?,?,?,?,NULL) ON CONFLICT(id) DO UPDATE SET
               text=excluded.text,author=excluded.author,category=excluded.category,
               updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL""",
            (
                quote_id,
                _clean_text(
                    data.get("text"), field="La citation", maximum=1000, required=True
                ),
                _clean_text(data.get("author"), field="L'auteur", maximum=200),
                category,
                ts,
            ),
        )

    def sync_status(self) -> dict[str, Any]:
        with self._transaction() as conn:
            self._refresh_local_clocks(conn)
            cursor = int(
                conn.execute(
                    "SELECT COALESCE(MAX(seq),0) AS cursor FROM succes_operations"
                ).fetchone()["cursor"]
            )
            peer_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM succes_sync_peers "
                    "WHERE revoked_at_ms IS NULL"
                ).fetchone()["count"]
            )
            pending_pairings = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM succes_sync_pairings "
                    "WHERE redeemed_at_ms IS NULL AND expires_at_ms>=?",
                    (now_ms(),),
                ).fetchone()["count"]
            )
        relay = self.relay_url()
        guest = self.guest_session()
        last_sync_raw = self._meta_get(_META_LAST_SYNC_AT)
        last_error = self._meta_get(_META_LAST_SYNC_ERROR)
        configured = peer_count > 0 or guest is not None
        if guest is not None:
            role = "guest"
            mode = "paired"
        elif peer_count > 0:
            role = "host"
            mode = "paired"
        else:
            role = "ready"
            mode = "ready"
        transport = "https_relay" if relay else "loopback_only"
        if guest is not None:
            message = (
                f"Appairé en tant qu'invité via {relay}. "
                "Lancez une synchronisation pour échanger les changements."
            )
        elif peer_count > 0:
            message = (
                f"{peer_count} appareil(s) autorisé(s)"
                + (f" · relais {relay}" if relay else "")
                + ". Les changements hors ligne seront échangés à la prochaine connexion."
            )
        elif relay:
            message = (
                f"Relais configuré ({relay}). Créez une invitation ici, ou "
                "rejoignez un autre appareil avec son code."
            )
        else:
            message = (
                "Ce Mac est prêt à appairer un appareil. Indiquez l'URL d'un relais "
                "HTTPS de confiance pour synchroniser hors de cette machine."
            )
        return {
            "mode": mode,
            "role": role,
            "configured": configured,
            "deviceId": self.device_id(),
            "localCursor": cursor,
            "peerCount": peer_count,
            "pendingPairings": pending_pairings,
            "transport": transport,
            "relayUrl": relay,
            "guest": guest,
            "lastSyncAtMs": int(last_sync_raw) if last_sync_raw else None,
            "lastSyncError": last_error,
            "peers": self.list_peers(),
            "message": message,
        }
