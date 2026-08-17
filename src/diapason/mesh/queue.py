"""The outbox: commands waiting to reach a device, and what came back.

Three questions this answers that the protocol alone cannot (spec §44/§45):

* what happens when the target is not there — and the honest answer differs
  per tool. Opening a screen on a sleeping phone is pointless by the time it
  wakes (REQUIRE_ONLINE); a notification is worth keeping
  (QUEUE_UNTIL_EXPIRATION); some things are simply not worth retrying
  (DROP_IF_OFFLINE);
* whether a command already ran — replaying a delivery must never produce
  two effects, so results are recorded against the idempotency key and
  replayed rather than re-executed;
* what the user is told — every terminal state carries a French sentence
  that is true. A queued command says queued. It never says done.

The one rule above all (spec §57): an offline device is never reported as
having executed anything.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping

from diapason.core.paths import get_data_dir
from diapason.mesh.commands import RemoteCommand

logger = logging.getLogger(__name__)

__all__ = [
    "CommandQueue",
    "OFFLINE_POLICIES",
]

OFFLINE_POLICIES = ("DROP_IF_OFFLINE", "QUEUE_UNTIL_EXPIRATION", "REQUIRE_ONLINE")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mesh_commands (
    command_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    origin_device_id TEXT NOT NULL,
    target_device_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error_code TEXT,
    user_message TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS mesh_commands_pending_idx
    ON mesh_commands(status, target_device_id, expires_at_ms);
CREATE UNIQUE INDEX IF NOT EXISTS mesh_commands_idem_idx
    ON mesh_commands(idempotency_key);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


class CommandQueue:
    """Durable record of every command this device sent or received."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or (get_data_dir() / "mesh.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ── writing ──────────────────────────────────────────────────────────

    def enqueue(self, command: RemoteCommand, *, status: str = "PENDING") -> dict:
        """Record a command before any attempt to deliver it.

        Written FIRST, on purpose: a command that left the machine without a
        row behind it is a command nobody can tell you about afterwards. This
        is the transactional-outbox rule of spec §16 applied to commands.
        """
        stamp = now_ms()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM mesh_commands WHERE idempotency_key=?",
                (command.idempotency_key,),
            ).fetchone()
            if existing is not None:
                # Same intent, already recorded — hand back what we know
                # instead of creating a second one (spec §45).
                return self._serialize(existing)
            conn.execute(
                """INSERT INTO mesh_commands
                   (command_id, idempotency_key, origin_device_id,
                    target_device_id, tool, envelope_json, status,
                    created_at_ms, expires_at_ms, updated_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    command.command_id,
                    command.idempotency_key,
                    command.origin_device_id,
                    command.target_device_id,
                    command.tool,
                    json.dumps(command.to_dict(), ensure_ascii=False),
                    status,
                    command.created_at_ms,
                    command.expires_at_ms,
                    stamp,
                ),
            )
            conn.commit()
        return self.get(command.command_id)

    def mark(
        self,
        command_id: str,
        status: str,
        *,
        user_message: str = "",
        result: Any = None,
        error_code: str = "",
    ) -> dict:
        terminal = status in {"SUCCESS", "FAILED", "DENIED", "EXPIRED", "UNSUPPORTED"}
        stamp = now_ms()
        with self._connect() as conn:
            conn.execute(
                """UPDATE mesh_commands
                   SET status=?, user_message=?, result_json=?, error_code=?,
                       updated_at_ms=?, completed_at_ms=?
                   WHERE command_id=?""",
                (
                    status,
                    user_message,
                    json.dumps(result, ensure_ascii=False)
                    if result is not None
                    else None,
                    error_code or None,
                    stamp,
                    stamp if terminal else None,
                    command_id,
                ),
            )
            conn.commit()
        return self.get(command_id)

    def record_attempt(self, command_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE mesh_commands SET attempts=attempts+1, updated_at_ms=? "
                "WHERE command_id=?",
                (now_ms(), command_id),
            )
            conn.commit()

    def expire_stale(self, *, now: int | None = None) -> int:
        """Turn past-deadline queued commands into honest EXPIRED rows.

        Without this a queue quietly accumulates commands the user believes
        are still coming.
        """
        stamp = now_ms() if now is None else now
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE mesh_commands
                   SET status='EXPIRED', completed_at_ms=?, updated_at_ms=?,
                       user_message='La commande a expiré avant d''être livrée.'
                   WHERE status IN ('PENDING','QUEUED','ACCEPTED','RUNNING')
                     AND expires_at_ms < ?""",
                (stamp, stamp, stamp),
            )
            conn.commit()
        return cursor.rowcount

    # ── reading ──────────────────────────────────────────────────────────

    def get(self, command_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mesh_commands WHERE command_id=?", (command_id,)
            ).fetchone()
        if row is None:
            raise KeyError(command_id)
        return self._serialize(row)

    def find_by_idempotency(self, key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mesh_commands WHERE idempotency_key=?", (key,)
            ).fetchone()
        return None if row is None else self._serialize(row)

    def pending_for(self, target_device_id: str, *, limit: int = 50) -> list[dict]:
        """Queued commands still worth delivering to this device."""
        stamp = now_ms()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM mesh_commands
                   WHERE target_device_id=? AND status IN ('PENDING','QUEUED')
                     AND expires_at_ms >= ?
                   ORDER BY created_at_ms LIMIT ?""",
                (target_device_id, stamp, limit),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def envelope_of(self, command_id: str) -> RemoteCommand | None:
        """The signed command as it was recorded, ready to travel again.

        Re-sent verbatim rather than rebuilt: the signature covers the
        original bytes, so a command re-signed with a fresh timestamp would
        be a *different* command, and the receiver's replay protection could
        no longer tell a retry from a duplicate.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT envelope_json FROM mesh_commands WHERE command_id=?",
                (command_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return RemoteCommand.from_dict(json.loads(row["envelope_json"]))
        except (TypeError, ValueError, KeyError):
            logger.warning("enveloppe illisible pour %s", command_id)
            return None

    def pending_envelopes_for(
        self, target_device_id: str, *, limit: int = 50
    ) -> list[dict]:
        """The same queue, as signed envelopes a device can verify itself.

        Separate from ``pending_for`` because the envelope is only ever wanted
        by the one caller that hands commands to a polling device. Putting it
        in every serialisation would push signatures through the command
        history and the UI, which have no use for them.
        """
        stamp = now_ms()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT command_id, envelope_json FROM mesh_commands
                   WHERE target_device_id=? AND status IN ('PENDING','QUEUED')
                     AND expires_at_ms >= ?
                   ORDER BY created_at_ms LIMIT ?""",
                (target_device_id, stamp, limit),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            try:
                envelope = json.loads(row["envelope_json"])
            except (TypeError, ValueError):
                # A row we cannot parse is one we cannot honestly deliver.
                # Skipping keeps the poll working for every other command.
                logger.warning("enveloppe illisible pour %s", row["command_id"])
                continue
            out.append({"commandId": row["command_id"], "envelope": envelope})
        return out

    def history(self, *, limit: int = 50) -> list[dict]:
        """Recent commands, newest first — the §43 command history."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mesh_commands ORDER BY created_at_ms DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    @staticmethod
    def _serialize(row: Mapping[str, Any]) -> dict:
        result = row["result_json"]
        return {
            "commandId": row["command_id"],
            "idempotencyKey": row["idempotency_key"],
            "originDeviceId": row["origin_device_id"],
            "targetDeviceId": row["target_device_id"],
            "tool": row["tool"],
            "status": row["status"],
            "result": json.loads(result) if result else None,
            "errorCode": row["error_code"],
            "userSafeMessage": row["user_message"],
            "attempts": row["attempts"],
            "createdAtMs": row["created_at_ms"],
            "expiresAtMs": row["expires_at_ms"],
            "completedAtMs": row["completed_at_ms"],
        }
