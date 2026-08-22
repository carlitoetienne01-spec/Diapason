"""Transactional SQLite persistence for Succès.

The schema is local-first but sync-ready: every mutation appends an immutable
operation, deletes are tombstones, and updates use millisecond LWW clocks.
No remote service is implied or reported until one is configured.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from diapason.core.paths import get_data_dir

MAX_FUTURE_SKEW_MS = 5 * 60 * 1000
MAX_SUBTASK_DEPTH = 24
MAX_TASK_TREE_DEPTH = 16
PRIORITIES = frozenset({"low", "medium", "high", "urgent"})


class SuccesError(ValueError):
    """Domain validation or conflict error safe to show to the user."""


class SuccesNotFound(SuccesError):
    """Requested Succès entity was not found."""


def now_ms() -> int:
    return int(time.time() * 1000)


def _safe_timestamp(value: Any, *, fallback: int | None = None) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
        parsed = fallback if fallback is not None else now_ms()
    return max(0, min(parsed, now_ms() + MAX_FUTURE_SKEW_MS))


def _validate_iso_date(value: str, field: str = "date") -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        date.fromisoformat(raw)
    except ValueError as exc:
        raise SuccesError(
            f"{field} doit être une date valide au format AAAA-MM-JJ."
        ) from exc
    return raw


def _clean_text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
    raw = str(value or "").strip()
    if required and not raw:
        raise SuccesError(f"{field} est obligatoire.")
    if len(raw) > maximum:
        raise SuccesError(f"{field} ne peut pas dépasser {maximum} caractères.")
    return raw


_SCHEMA = """
CREATE TABLE IF NOT EXISTS succes_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS succes_tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    priority TEXT NOT NULL DEFAULT 'medium',
    scheduled_date TEXT NOT NULL DEFAULT '',
    scheduled_time TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    emoji TEXT NOT NULL DEFAULT '',
    template_id TEXT NOT NULL DEFAULT '',
    group_id TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0,
    created_date TEXT NOT NULL,
    completed_date TEXT NOT NULL DEFAULT '',
    postponed_count INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER,
    owner_id TEXT NOT NULL DEFAULT 'local-owner'
);
CREATE INDEX IF NOT EXISTS succes_tasks_date_idx
    ON succes_tasks(scheduled_date, done, order_index);
CREATE TABLE IF NOT EXISTS succes_subtasks (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES succes_tasks(id),
    parent_id TEXT,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    is_group INTEGER NOT NULL DEFAULT 0,
    order_index INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER,
    owner_id TEXT NOT NULL DEFAULT 'local-owner'
);
CREATE INDEX IF NOT EXISTS succes_subtasks_task_idx
    ON succes_subtasks(task_id, parent_id, order_index);
CREATE TABLE IF NOT EXISTS succes_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    created_date TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE IF NOT EXISTS succes_operations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id TEXT NOT NULL UNIQUE,
    device_id TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    request_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS succes_operations_cursor_idx
    ON succes_operations(seq);
CREATE TABLE IF NOT EXISTS succes_imports (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    snapshot_json TEXT NOT NULL,
    imported_at_ms INTEGER NOT NULL,
    summary_json TEXT NOT NULL
);
PRAGMA user_version = 1;
"""


class SuccesStore:
    """Thread-safe facade using one short-lived SQLite connection per action."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or (get_data_dir() / "succes.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            operation_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(succes_operations)"
                ).fetchall()
            }
            if "request_json" not in operation_columns:
                conn.execute(
                    "ALTER TABLE succes_operations ADD COLUMN "
                    "request_json TEXT NOT NULL DEFAULT '{}'"
                )
            self._ensure_task_columns(conn)
            self._ensure_project_columns(conn)
            conn.execute(
                "INSERT OR IGNORE INTO succes_meta(key, value) VALUES('device_id', ?)",
                (f"mac-{secrets.token_hex(8)}",),
            )
            conn.commit()

    @staticmethod
    def _ensure_task_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(succes_tasks)").fetchall()
        }
        if "parent_task_id" not in columns:
            conn.execute(
                "ALTER TABLE succes_tasks ADD COLUMN "
                "parent_task_id TEXT NOT NULL DEFAULT ''"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS succes_tasks_parent_idx "
                "ON succes_tasks(project_id, parent_task_id, order_index)"
            )

    @staticmethod
    def _ensure_project_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(succes_projects)").fetchall()
        }
        if "structure" not in columns:
            conn.execute(
                "ALTER TABLE succes_projects ADD COLUMN "
                "structure TEXT NOT NULL DEFAULT 'flat'"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        # La configuration entre dans le try : un PRAGMA qui lève avant lui
        # laisserait la connexion orpheline, sans personne pour la fermer.
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def device_id(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM succes_meta WHERE key='device_id'"
            ).fetchone()
        return str(row["value"])

    def _record_op(
        self,
        conn: sqlite3.Connection,
        *,
        entity: str,
        entity_id: str,
        kind: str,
        payload: Mapping[str, Any],
        request: Mapping[str, Any],
        timestamp_ms: int,
        op_id: str | None = None,
    ) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO succes_operations
               (op_id, device_id, entity, entity_id, kind, request_json,
                payload_json, timestamp_ms, created_at_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                op_id or str(uuid.uuid4()),
                self.device_id(),
                entity,
                entity_id,
                kind,
                self._canonical_json(request),
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                timestamp_ms,
                now_ms(),
            ),
        )

    @staticmethod
    def _canonical_json(value: Mapping[str, Any]) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def _replayed_task(
        self,
        conn: sqlite3.Connection,
        op_id: str | None,
        request: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not op_id:
            return None
        row = conn.execute(
            "SELECT request_json,payload_json FROM succes_operations WHERE op_id=?",
            (op_id,),
        ).fetchone()
        if row is None:
            return None
        if row["request_json"] != self._canonical_json(request):
            raise SuccesError(
                "Cet identifiant d'opération a déjà été utilisé "
                "avec d'autres paramètres."
            )
        payload = json.loads(row["payload_json"])
        task_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
        current = self._load_task(conn, task_id) if task_id else None
        return current or payload

    @staticmethod
    def _task_dict(row: sqlite3.Row, subtasks: list[dict[str, Any]]) -> dict[str, Any]:
        keys = row.keys()
        return {
            "id": row["id"],
            "title": row["title"],
            "done": bool(row["done"]),
            "priority": row["priority"],
            "date": row["scheduled_date"],
            "time": row["scheduled_time"],
            "projectId": row["project_id"],
            "parentTaskId": row["parent_task_id"] if "parent_task_id" in keys else "",
            "category": row["category"],
            "notes": row["notes"],
            "emoji": row["emoji"],
            "templateId": row["template_id"],
            "groupId": row["group_id"],
            "order": row["order_index"],
            "createdAt": row["created_date"],
            "completedDate": row["completed_date"],
            "postponedCount": row["postponed_count"],
            "updatedAtMs": row["updated_at_ms"],
            "deletedAtMs": row["deleted_at_ms"],
            "subtasks": subtasks,
        }

    def _validate_task_parent(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: str,
        project_id: str,
        parent_task_id: str,
    ) -> str:
        parent_id = (parent_task_id or "").strip()
        if not parent_id:
            return ""
        if not project_id.strip():
            raise SuccesError(
                "Une branche doit appartenir à un projet pour avoir un parent."
            )
        if parent_id == task_id:
            raise SuccesError("Une tâche ne peut pas être son propre parent.")
        parent = conn.execute(
            """SELECT id, project_id, parent_task_id FROM succes_tasks
               WHERE id=? AND deleted_at_ms IS NULL""",
            (parent_id,),
        ).fetchone()
        if parent is None:
            raise SuccesNotFound("La tâche parente n'existe pas ou a été supprimée.")
        if str(parent["project_id"] or "") != project_id:
            raise SuccesError("La tâche parente doit appartenir au même projet.")
        depth = 1
        cursor = parent
        seen = {task_id, parent_id}
        while str(cursor["parent_task_id"] or "").strip():
            depth += 1
            if depth >= MAX_TASK_TREE_DEPTH:
                raise SuccesError(
                    f"L'arbre de tâches ne peut pas dépasser "
                    f"{MAX_TASK_TREE_DEPTH} niveaux."
                )
            next_id = str(cursor["parent_task_id"])
            if next_id in seen:
                raise SuccesError("Cette hiérarchie formerait une boucle.")
            seen.add(next_id)
            cursor = conn.execute(
                """SELECT id, project_id, parent_task_id FROM succes_tasks
                   WHERE id=? AND deleted_at_ms IS NULL""",
                (next_id,),
            ).fetchone()
            if cursor is None:
                break
        return parent_id

    @staticmethod
    def _subtask_tree(rows: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
        nodes: dict[str, dict[str, Any]] = {}
        for row in rows:
            nodes[row["id"]] = {
                "id": row["id"],
                "title": row["title"],
                "done": bool(row["done"]),
                "isGroup": bool(row["is_group"]),
                "updatedAtMs": row["updated_at_ms"],
                "children": [],
                "_parent": row["parent_id"],
                "_order": row["order_index"],
            }
        roots: list[dict[str, Any]] = []
        for node in nodes.values():
            parent = nodes.get(node["_parent"])
            (parent["children"] if parent else roots).append(node)

        def clean(items: list[dict[str, Any]]) -> None:
            items.sort(key=lambda item: (item.pop("_order"), item["id"]))
            for item in items:
                item.pop("_parent", None)
                clean(item["children"])
                item["isGroup"] = bool(item["children"])
                if item["children"]:
                    item["done"] = all(
                        bool(child["done"]) for child in item["children"]
                    )

        clean(roots)
        return roots

    def _load_task(
        self, conn: sqlite3.Connection, task_id: str, *, include_deleted: bool = False
    ) -> dict[str, Any] | None:
        sql = "SELECT * FROM succes_tasks WHERE id = ?"
        params: tuple[Any, ...] = (task_id,)
        if not include_deleted:
            sql += " AND deleted_at_ms IS NULL"
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        subrows = conn.execute(
            """SELECT * FROM succes_subtasks
               WHERE task_id = ? AND deleted_at_ms IS NULL
               ORDER BY order_index, id""",
            (task_id,),
        ).fetchall()
        return self._task_dict(row, self._subtask_tree(subrows))

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            task = self._load_task(conn, task_id)
        if task is None:
            raise SuccesNotFound("Cette tâche n'existe pas ou a été supprimée.")
        return task

    def find_tasks(self, query: str) -> list[dict[str, Any]]:
        needle = f"%{query.strip().lower()}%"
        with self._connect() as conn:
            ids = [
                row["id"]
                for row in conn.execute(
                    """SELECT id FROM succes_tasks
                       WHERE deleted_at_ms IS NULL AND lower(title) LIKE ?
                       ORDER BY updated_at_ms DESC LIMIT 20""",
                    (needle,),
                ).fetchall()
            ]
            return [task for task_id in ids if (task := self._load_task(conn, task_id))]

    def list_tasks(
        self,
        *,
        scheduled_date: str | None = None,
        include_done: bool = True,
        search: str = "",
    ) -> list[dict[str, Any]]:
        clauses = ["deleted_at_ms IS NULL"]
        params: list[Any] = []
        if scheduled_date is not None:
            clauses.append("scheduled_date = ?")
            params.append(_validate_iso_date(scheduled_date))
        if not include_done:
            clauses.append("done = 0")
        if search.strip():
            clauses.append("lower(title) LIKE ?")
            params.append(f"%{search.strip().lower()}%")
        with self._connect() as conn:
            ids = [
                row["id"]
                for row in conn.execute(
                    f"""SELECT id FROM succes_tasks WHERE {" AND ".join(clauses)}
                         ORDER BY done, CASE priority
                           WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                           WHEN 'medium' THEN 2 ELSE 3 END,
                         scheduled_time, order_index, updated_at_ms DESC""",
                    params,
                ).fetchall()
            ]
            return [task for task_id in ids if (task := self._load_task(conn, task_id))]

    def create_task(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        title = _clean_text(
            data.get("title"), field="Le titre", maximum=200, required=True
        )
        priority = str(data.get("priority") or "medium").lower()
        if priority not in PRIORITIES:
            raise SuccesError("La priorité doit être low, medium, high ou urgent.")
        request = {
            "action": "create",
            "title": title,
            "priority": priority,
            "date": str(data.get("date") or ""),
            "time": str(data.get("time") or ""),
            "projectId": str(data.get("projectId") or ""),
            "parentTaskId": str(data.get("parentTaskId") or ""),
            "category": str(data.get("category") or ""),
            "notes": str(data.get("notes") or ""),
        }
        task_id = str(
            data.get("id")
            or (
                uuid.uuid5(uuid.NAMESPACE_URL, f"diapason:succes:{op_id}")
                if op_id
                else uuid.uuid4()
            )
        )
        ts = _safe_timestamp(data.get("updatedAtMs"))
        created = _validate_iso_date(
            str(data.get("createdAt") or date.today().isoformat()), "createdAt"
        )
        scheduled = _validate_iso_date(str(data.get("date") or ""))
        completed = _validate_iso_date(
            str(data.get("completedDate") or ""), "completedDate"
        )
        notes = _clean_text(data.get("notes"), field="Les notes", maximum=2000)
        project_id = str(data.get("projectId") or "")
        with self._transaction() as conn:
            replayed = self._replayed_task(conn, op_id, request)
            if replayed is not None:
                return replayed
            parent_task_id = self._validate_task_parent(
                conn,
                task_id=task_id,
                project_id=project_id,
                parent_task_id=str(data.get("parentTaskId") or ""),
            )
            existing = conn.execute(
                "SELECT updated_at_ms FROM succes_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if existing is not None:
                raise SuccesError("Une tâche avec cet identifiant existe déjà.")
            values = (
                task_id,
                title,
                int(bool(data.get("done"))),
                priority,
                scheduled,
                str(data.get("time") or ""),
                project_id,
                parent_task_id,
                str(data.get("category") or "")[:100],
                notes,
                str(data.get("emoji") or "")[:16],
                str(data.get("templateId") or ""),
                str(data.get("groupId") or ""),
                int(data.get("order") or 0),
                created,
                completed,
                max(0, int(data.get("postponedCount") or 0)),
                ts,
            )
            conn.execute(
                """INSERT INTO succes_tasks
                   (id,title,done,priority,scheduled_date,scheduled_time,project_id,
                    parent_task_id,category,notes,emoji,template_id,group_id,order_index,
                    created_date,completed_date,postponed_count,updated_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )
            task = self._load_task(conn, task_id)
            assert task is not None
            self._record_op(
                conn,
                entity="tasks",
                entity_id=task_id,
                kind="upsert",
                payload=task,
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )
        return task

    def update_task(
        self, task_id: str, patch: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        request = {"action": "update", "taskId": task_id, "patch": dict(patch)}
        allowed = {
            "title": (
                "title",
                lambda value: _clean_text(
                    value, field="Le titre", maximum=200, required=True
                ),
            ),
            "priority": ("priority", lambda value: self._priority(value)),
            "date": (
                "scheduled_date",
                lambda value: _validate_iso_date(str(value or "")),
            ),
            "time": ("scheduled_time", lambda value: str(value or "")),
            "projectId": ("project_id", lambda value: str(value or "")),
            "parentTaskId": ("parent_task_id", lambda value: str(value or "")),
            "category": ("category", lambda value: str(value or "")[:100]),
            "notes": (
                "notes",
                lambda value: _clean_text(value, field="Les notes", maximum=2000),
            ),
            "emoji": ("emoji", lambda value: str(value or "")[:16]),
            "order": ("order_index", int),
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in patch.items():
            if key not in allowed:
                continue
            column, convert = allowed[key]
            assignments.append(f"{column} = ?")
            values.append(convert(value))
        if not assignments:
            raise SuccesError("Aucune modification reconnue.")
        ts = _safe_timestamp(patch.get("updatedAtMs"))
        assignments.extend(["updated_at_ms = ?", "deleted_at_ms = NULL"])
        values.extend([ts, task_id])
        with self._transaction() as conn:
            replayed = self._replayed_task(conn, op_id, request)
            if replayed is not None:
                return replayed
            current = self._load_task(conn, task_id)
            if current is None:
                raise SuccesNotFound("Cette tâche n'existe pas ou a été supprimée.")
            next_project = (
                str(patch["projectId"])
                if "projectId" in patch
                else str(current.get("projectId") or "")
            )
            next_parent = (
                str(patch["parentTaskId"])
                if "parentTaskId" in patch
                else str(current.get("parentTaskId") or "")
            )
            if "projectId" in patch or "parentTaskId" in patch:
                validated_parent = self._validate_task_parent(
                    conn,
                    task_id=task_id,
                    project_id=next_project,
                    parent_task_id=next_parent,
                )
                # Replace parent value in the SET list when we validated it.
                if "parentTaskId" in patch or validated_parent != next_parent:
                    try:
                        parent_idx = next(
                            i
                            for i, part in enumerate(assignments)
                            if part.startswith("parent_task_id")
                        )
                        values[parent_idx] = validated_parent
                    except StopIteration:
                        assignments.insert(-2, "parent_task_id = ?")
                        values.insert(-2, validated_parent)
            conn.execute(
                f"UPDATE succes_tasks SET {', '.join(assignments)} WHERE id = ?", values
            )
            task = self._load_task(conn, task_id)
            assert task is not None
            self._record_op(
                conn,
                entity="tasks",
                entity_id=task_id,
                kind="upsert",
                payload=task,
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )
        return task

    @staticmethod
    def _priority(value: Any) -> str:
        priority = str(value or "medium").lower()
        if priority not in PRIORITIES:
            raise SuccesError("La priorité doit être low, medium, high ou urgent.")
        return priority

    def set_task_done(
        self, task_id: str, done: bool, *, op_id: str | None = None
    ) -> dict[str, Any]:
        request = {"action": "set_done", "taskId": task_id, "done": bool(done)}
        ts = now_ms()
        with self._transaction() as conn:
            replayed = self._replayed_task(conn, op_id, request)
            if replayed is not None:
                return replayed
            task = self._load_task(conn, task_id)
            if task is None:
                raise SuccesNotFound("Cette tâche n'existe pas ou a été supprimée.")
            # A parent's state is derived from its subtasks, so toggling the
            # parent has to carry the whole tree with it. Leaving children out
            # of sync would make the next toggle either fail or flip back.
            if task["subtasks"]:
                conn.execute(
                    "UPDATE succes_subtasks SET done=?, updated_at_ms=? "
                    "WHERE task_id=? AND deleted_at_ms IS NULL",
                    (int(done), ts, task_id),
                )
            completed = date.today().isoformat() if done else ""
            conn.execute(
                "UPDATE succes_tasks SET done=?, completed_date=?, "
                "updated_at_ms=? WHERE id=?",
                (int(done), completed, ts, task_id),
            )
            task = self._load_task(conn, task_id)
            assert task is not None
            self._record_op(
                conn,
                entity="tasks",
                entity_id=task_id,
                kind="upsert",
                payload=task,
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )
        return task

    def reschedule_task(
        self, task_id: str, scheduled_date: str, *, op_id: str | None = None
    ) -> dict[str, Any]:
        scheduled = _validate_iso_date(scheduled_date)
        request = {"action": "reschedule", "taskId": task_id, "date": scheduled}
        ts = now_ms()
        with self._transaction() as conn:
            replayed = self._replayed_task(conn, op_id, request)
            if replayed is not None:
                return replayed
            task = self._load_task(conn, task_id)
            if task is None:
                raise SuccesNotFound("Cette tâche n'existe pas ou a été supprimée.")
            conn.execute(
                """UPDATE succes_tasks SET scheduled_date=?,
                   postponed_count=postponed_count+1, updated_at_ms=? WHERE id=?""",
                (scheduled, ts, task_id),
            )
            task = self._load_task(conn, task_id)
            assert task is not None
            self._record_op(
                conn,
                entity="tasks",
                entity_id=task_id,
                kind="upsert",
                payload=task,
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )
        return task

    def reschedule_series(
        self, task_id: str, scheduled_date: str, *, op_id: str | None = None
    ) -> dict[str, Any]:
        """Shift every occurrence of a recurrence by the same day offset.

        The dragged occurrence defines the delta between its current date and
        the drop target; all sibling occurrences (same ``template_id``) move by
        that delta. Occurrences without a date are left untouched, and the
        recurrence rule itself is edited separately on the Récurrences page.
        """
        scheduled = _validate_iso_date(scheduled_date)
        if not scheduled:
            raise SuccesError("Une date valide est requise pour reporter la série.")
        ts = now_ms()
        with self._transaction() as conn:
            anchor = self._load_task(conn, task_id)
            if anchor is None:
                raise SuccesNotFound("Cette tâche n'existe pas ou a été supprimée.")
            template_id = str(anchor.get("templateId") or "")
            if not template_id:
                raise SuccesError("Cette tâche ne provient pas d'une récurrence.")
            current = str(anchor.get("date") or "")
            if not current:
                raise SuccesError("La tâche de référence n'a pas encore de date.")
            delta = (date.fromisoformat(scheduled) - date.fromisoformat(current)).days
            rows = conn.execute(
                "SELECT id, scheduled_date FROM succes_tasks "
                "WHERE template_id=? AND deleted_at_ms IS NULL",
                (template_id,),
            ).fetchall()
            updated = 0
            for row in rows:
                old = str(row["scheduled_date"] or "")
                if not old:
                    continue
                new_date = (date.fromisoformat(old) + timedelta(days=delta)).isoformat()
                if delta != 0:
                    conn.execute(
                        "UPDATE succes_tasks SET scheduled_date=?, updated_at_ms=? "
                        "WHERE id=?",
                        (new_date, ts, row["id"]),
                    )
                    task = self._load_task(conn, row["id"])
                    assert task is not None
                    self._record_op(
                        conn,
                        entity="tasks",
                        entity_id=row["id"],
                        kind="upsert",
                        payload=task,
                        request={
                            "action": "reschedule_series",
                            "taskId": row["id"],
                            "templateId": template_id,
                            "date": new_date,
                        },
                        timestamp_ms=ts,
                    )
                updated += 1
        return {"templateId": template_id, "deltaDays": delta, "updated": updated}

    def add_subtask(
        self,
        task_id: str,
        title: str,
        *,
        parent_id: str | None = None,
        op_id: str | None = None,
    ) -> dict[str, Any]:
        clean_title = _clean_text(title, field="Le titre", maximum=200, required=True)
        request = {
            "action": "add_subtask",
            "taskId": task_id,
            "title": clean_title,
            "parentId": parent_id or "",
        }
        subtask_id = str(uuid.uuid4())
        ts = now_ms()
        with self._transaction() as conn:
            replayed = self._replayed_task(conn, op_id, request)
            if replayed is not None:
                return replayed
            task = self._load_task(conn, task_id)
            if task is None:
                raise SuccesNotFound("Cette tâche n'existe pas ou a été supprimée.")
            if parent_id:
                parent = conn.execute(
                    "SELECT id,parent_id FROM succes_subtasks "
                    "WHERE id=? AND task_id=? AND deleted_at_ms IS NULL",
                    (parent_id, task_id),
                ).fetchone()
                if parent is None:
                    raise SuccesNotFound("La sous-tâche parente n'existe pas.")
                depth = 1
                cursor = parent
                while cursor["parent_id"]:
                    depth += 1
                    if depth >= MAX_SUBTASK_DEPTH:
                        raise SuccesError(
                            "La profondeur maximale des sous-tâches est atteinte."
                        )
                    cursor = conn.execute(
                        "SELECT id,parent_id FROM succes_subtasks WHERE id=?",
                        (cursor["parent_id"],),
                    ).fetchone()
                    if cursor is None:
                        break
                conn.execute(
                    "UPDATE succes_subtasks SET is_group=1 WHERE id=?", (parent_id,)
                )
            order = conn.execute(
                """SELECT COALESCE(MAX(order_index), -1) + 1 AS n FROM succes_subtasks
                   WHERE task_id=? AND parent_id IS ? AND deleted_at_ms IS NULL""",
                (task_id, parent_id),
            ).fetchone()["n"]
            conn.execute(
                """INSERT INTO succes_subtasks
                   (id,task_id,parent_id,title,done,is_group,order_index,updated_at_ms)
                   VALUES (?,?,?,?,0,0,?,?)""",
                (subtask_id, task_id, parent_id, clean_title, order, ts),
            )
            self._recompute_task(conn, task_id, ts)
            task = self._load_task(conn, task_id)
            assert task is not None
            self._record_op(
                conn,
                entity="subtasks",
                entity_id=subtask_id,
                kind="upsert",
                payload=task,
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )
        return task

    def set_subtask_done(
        self, task_id: str, subtask_id: str, done: bool, *, op_id: str | None = None
    ) -> dict[str, Any]:
        request = {
            "action": "set_subtask_done",
            "taskId": task_id,
            "subtaskId": subtask_id,
            "done": bool(done),
        }
        ts = now_ms()
        with self._transaction() as conn:
            replayed = self._replayed_task(conn, op_id, request)
            if replayed is not None:
                return replayed
            row = conn.execute(
                "SELECT id FROM succes_subtasks "
                "WHERE id=? AND task_id=? AND deleted_at_ms IS NULL",
                (subtask_id, task_id),
            ).fetchone()
            if row is None:
                raise SuccesNotFound("Cette sous-tâche n'existe pas.")
            descendants = self._descendant_ids(conn, subtask_id)
            ids = [subtask_id, *descendants]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                "UPDATE succes_subtasks SET done=?, updated_at_ms=? "
                f"WHERE id IN ({placeholders})",
                [int(done), ts, *ids],
            )
            self._recompute_groups(conn, task_id, ts)
            self._recompute_task(conn, task_id, ts)
            task = self._load_task(conn, task_id)
            assert task is not None
            self._record_op(
                conn,
                entity="subtasks",
                entity_id=subtask_id,
                kind="upsert",
                payload=task,
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )
        return task

    def delete_subtask(
        self, task_id: str, subtask_id: str, *, op_id: str | None = None
    ) -> dict[str, Any]:
        request = {
            "action": "delete_subtask",
            "taskId": task_id,
            "subtaskId": subtask_id,
        }
        ts = now_ms()
        with self._transaction() as conn:
            replayed = self._replayed_task(conn, op_id, request)
            if replayed is not None:
                return replayed
            row = conn.execute(
                "SELECT id FROM succes_subtasks "
                "WHERE id=? AND task_id=? AND deleted_at_ms IS NULL",
                (subtask_id, task_id),
            ).fetchone()
            if row is None:
                raise SuccesNotFound("Cette sous-tâche n'existe pas.")
            descendants = self._descendant_ids(conn, subtask_id)
            ids = [subtask_id, *descendants]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE succes_subtasks SET deleted_at_ms=?, updated_at_ms=? "
                f"WHERE id IN ({placeholders})",
                [ts, ts, *ids],
            )
            self._recompute_groups(conn, task_id, ts)
            self._recompute_task(conn, task_id, ts)
            task = self._load_task(conn, task_id)
            assert task is not None
            self._record_op(
                conn,
                entity="subtasks",
                entity_id=subtask_id,
                kind="upsert",
                payload=task,
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )
        return task

    def delete_task(self, task_id: str, *, op_id: str | None = None) -> None:
        request = {"action": "delete", "taskId": task_id}
        ts = now_ms()
        with self._transaction() as conn:
            if self._replayed_task(conn, op_id, request) is not None:
                return
            if self._load_task(conn, task_id) is None:
                raise SuccesNotFound("Cette tâche n'existe pas ou a été supprimée.")
            conn.execute(
                "UPDATE succes_tasks SET deleted_at_ms=?, updated_at_ms=? WHERE id=?",
                (ts, ts, task_id),
            )
            conn.execute(
                "UPDATE succes_subtasks SET deleted_at_ms=? "
                "WHERE task_id=? AND deleted_at_ms IS NULL",
                (ts, task_id),
            )
            self._record_op(
                conn,
                entity="tasks",
                entity_id=task_id,
                kind="delete",
                payload={"id": task_id, "deletedAtMs": ts},
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )

    @staticmethod
    def _descendant_ids(conn: sqlite3.Connection, parent_id: str) -> list[str]:
        rows = conn.execute(
            """WITH RECURSIVE descendants(id) AS (
                 SELECT id FROM succes_subtasks
                 WHERE parent_id=? AND deleted_at_ms IS NULL
                 UNION ALL SELECT s.id FROM succes_subtasks s
                 JOIN descendants d ON s.parent_id=d.id
                 WHERE s.deleted_at_ms IS NULL)
               SELECT id FROM descendants""",
            (parent_id,),
        ).fetchall()
        return [row["id"] for row in rows]

    @staticmethod
    def _recompute_groups(conn: sqlite3.Connection, task_id: str, ts: int) -> None:
        rows = conn.execute(
            "SELECT id FROM succes_subtasks WHERE task_id=? AND deleted_at_ms IS NULL",
            (task_id,),
        ).fetchall()
        for row in reversed(rows):
            children = conn.execute(
                "SELECT done FROM succes_subtasks "
                "WHERE parent_id=? AND deleted_at_ms IS NULL",
                (row["id"],),
            ).fetchall()
            if children:
                conn.execute(
                    "UPDATE succes_subtasks SET is_group=1,done=?,"
                    "updated_at_ms=? WHERE id=?",
                    (
                        int(all(bool(child["done"]) for child in children)),
                        ts,
                        row["id"],
                    ),
                )
            else:
                conn.execute(
                    "UPDATE succes_subtasks SET is_group=0 WHERE id=?", (row["id"],)
                )

    def _recompute_task(self, conn: sqlite3.Connection, task_id: str, ts: int) -> None:
        roots = conn.execute(
            """SELECT done FROM succes_subtasks
               WHERE task_id=? AND parent_id IS NULL AND deleted_at_ms IS NULL""",
            (task_id,),
        ).fetchall()
        done = bool(roots) and all(bool(row["done"]) for row in roots)
        completed = date.today().isoformat() if done else ""
        conn.execute(
            "UPDATE succes_tasks SET done=?,completed_date=?,"
            "updated_at_ms=? WHERE id=?",
            (int(done), completed, ts, task_id),
        )

    def list_operations(self, *, after: int = 0, limit: int = 500) -> dict[str, Any]:
        limit = min(max(int(limit), 1), 1000)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM succes_operations WHERE seq>? ORDER BY seq LIMIT ?",
                (max(0, int(after)), limit),
            ).fetchall()
            cursor = conn.execute(
                "SELECT COALESCE(MAX(seq),0) AS cursor FROM succes_operations"
            ).fetchone()["cursor"]
        return {
            "operations": [
                {
                    "cursor": row["seq"],
                    "opId": row["op_id"],
                    "deviceId": row["device_id"],
                    "entity": row["entity"],
                    "entityId": row["entity_id"],
                    "kind": row["kind"],
                    "request": json.loads(row["request_json"]),
                    "payload": json.loads(row["payload_json"]),
                    "timestampMs": row["timestamp_ms"],
                }
                for row in rows
            ],
            "cursor": cursor,
            "hasMore": bool(rows and rows[-1]["seq"] < cursor),
        }

    def sync_status(self) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT COALESCE(MAX(seq),0) AS cursor FROM succes_operations"
            ).fetchone()["cursor"]
        return {
            "mode": "local_only",
            "configured": False,
            "deviceId": self.device_id(),
            "localCursor": cursor,
            "message": (
                "Les données sont enregistrées sur ce Mac. La synchronisation "
                "multi-appareil n'est pas encore configurée."
            ),
        }

    def import_legacy_snapshot(
        self, snapshot: Mapping[str, Any], *, source: str = "Life OS PHP/Flutter"
    ) -> dict[str, Any]:
        raw = json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        state = (
            snapshot.get("state")
            if isinstance(snapshot.get("state"), Mapping)
            else snapshot
        )
        todos = state.get("todos", []) if isinstance(state, Mapping) else []
        projects = state.get("projects", []) if isinstance(state, Mapping) else []
        if not isinstance(todos, list) or not isinstance(projects, list):
            raise SuccesError("Cette sauvegarde Life OS n'a pas une structure valide.")
        summary = {
            "tasksImported": 0,
            "tasksSkipped": 0,
            "projectsImported": 0,
            "archived": True,
        }
        with self._transaction() as conn:
            existing_import = conn.execute(
                "SELECT summary_json FROM succes_imports WHERE sha256=?", (digest,)
            ).fetchone()
            if existing_import:
                previous = json.loads(existing_import["summary_json"])
                return {**previous, "alreadyImported": True}
            for project in projects:
                if not isinstance(project, Mapping):
                    continue
                project_id = str(project.get("id") or "").strip()
                name = _clean_text(
                    project.get("name"), field="Le nom du projet", maximum=200
                )
                if not project_id or not name:
                    continue
                ts = _safe_timestamp(project.get("updatedAtMs"), fallback=0)
                current = conn.execute(
                    "SELECT updated_at_ms FROM succes_projects WHERE id=?",
                    (project_id,),
                ).fetchone()
                if current and current["updated_at_ms"] > ts:
                    continue
                conn.execute(
                    """INSERT INTO succes_projects
                       (id,name,description,color,icon,start_date,end_date,created_date,updated_at_ms,deleted_at_ms)
                       VALUES (?,?,?,?,?,?,?,?,?,NULL)
                       ON CONFLICT(id) DO UPDATE SET
                       name=excluded.name,description=excluded.description,
                       color=excluded.color,icon=excluded.icon,start_date=excluded.start_date,
                       end_date=excluded.end_date,created_date=excluded.created_date,
                       updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL""",
                    (
                        project_id,
                        name,
                        str(project.get("desc") or "")[:2000],
                        str(project.get("color") or "#6366f1")[:32],
                        str(project.get("icon") or "")[:32],
                        str(project.get("start") or ""),
                        str(project.get("end") or ""),
                        str(project.get("createdAt") or ""),
                        ts,
                    ),
                )
                summary["projectsImported"] += 1
            for todo in todos:
                if not isinstance(todo, Mapping):
                    continue
                try:
                    imported = self._import_task(conn, todo)
                except SuccesError:
                    summary["tasksSkipped"] += 1
                    continue
                summary["tasksImported" if imported else "tasksSkipped"] += 1
            conn.execute(
                "INSERT INTO succes_imports"
                "(id,source,sha256,snapshot_json,imported_at_ms,summary_json) "
                "VALUES(?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    source,
                    digest,
                    raw,
                    now_ms(),
                    json.dumps(summary, ensure_ascii=False),
                ),
            )
        return {**summary, "alreadyImported": False}

    def _import_task(self, conn: sqlite3.Connection, todo: Mapping[str, Any]) -> bool:
        task_id = str(todo.get("id") or "").strip()
        title = _clean_text(todo.get("title"), field="Le titre", maximum=200)
        if not task_id or not title or title.lower() == "input text":
            return False
        ts = _safe_timestamp(todo.get("updatedAtMs"), fallback=0)
        current = conn.execute(
            "SELECT updated_at_ms FROM succes_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if current and current["updated_at_ms"] > ts:
            return False
        priority = str(todo.get("priority") or "medium").lower()
        if priority not in PRIORITIES:
            priority = "medium"
        conn.execute(
            """INSERT INTO succes_tasks
               (id,title,done,priority,scheduled_date,scheduled_time,project_id,category,
                notes,emoji,template_id,group_id,order_index,created_date,completed_date,
                postponed_count,updated_at_ms,deleted_at_ms,parent_task_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title,done=excluded.done,
               priority=excluded.priority,scheduled_date=excluded.scheduled_date,
               scheduled_time=excluded.scheduled_time,project_id=excluded.project_id,
               category=excluded.category,notes=excluded.notes,emoji=excluded.emoji,
               template_id=excluded.template_id,group_id=excluded.group_id,
               order_index=excluded.order_index,created_date=excluded.created_date,
               completed_date=excluded.completed_date,postponed_count=excluded.postponed_count,
               updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL,
               parent_task_id=excluded.parent_task_id""",
            (
                task_id,
                title,
                int(bool(todo.get("done"))),
                priority,
                str(todo.get("date") or ""),
                str(todo.get("time") or ""),
                str(todo.get("projectId") or ""),
                str(todo.get("category") or "")[:100],
                str(todo.get("notes") or "")[:2000],
                str(todo.get("emoji") or "")[:16],
                str(todo.get("templateId") or ""),
                str(todo.get("groupId") or ""),
                int(todo.get("order") or 0),
                str(todo.get("createdAt") or date.today().isoformat()),
                str(todo.get("completedDate") or ""),
                max(0, int(todo.get("postponedCount") or 0)),
                ts,
                str(todo.get("parentTaskId") or ""),
            ),
        )
        conn.execute(
            "UPDATE succes_subtasks SET deleted_at_ms=? "
            "WHERE task_id=? AND deleted_at_ms IS NULL",
            (ts, task_id),
        )
        self._import_subtasks(
            conn, task_id, todo.get("subtasks"), parent_id=None, depth=0, fallback_ts=ts
        )
        task = self._load_task(conn, task_id)
        assert task is not None
        self._record_op(
            conn,
            entity="tasks",
            entity_id=task_id,
            kind="upsert",
            payload=task,
            request={"action": "legacy_import", "taskId": task_id},
            timestamp_ms=ts,
        )
        return True

    def _import_subtasks(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        raw_nodes: Any,
        *,
        parent_id: str | None,
        depth: int,
        fallback_ts: int,
    ) -> None:
        if depth >= MAX_SUBTASK_DEPTH or not isinstance(raw_nodes, list):
            return
        for order, raw in enumerate(raw_nodes):
            if not isinstance(raw, Mapping):
                continue
            subtask_id = str(raw.get("id") or "").strip()
            if not subtask_id:
                continue
            title = str(raw.get("title") or "").strip()
            children = (
                raw.get("children") if isinstance(raw.get("children"), list) else []
            )
            ts = _safe_timestamp(raw.get("updatedAtMs"), fallback=fallback_ts)
            conn.execute(
                """INSERT INTO succes_subtasks
                   (id,task_id,parent_id,title,done,is_group,order_index,updated_at_ms,deleted_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,NULL)
                   ON CONFLICT(id) DO UPDATE SET
                   task_id=excluded.task_id,parent_id=excluded.parent_id,
                   title=excluded.title,done=excluded.done,is_group=excluded.is_group,
                   order_index=excluded.order_index,updated_at_ms=excluded.updated_at_ms,
                   deleted_at_ms=NULL""",
                (
                    subtask_id,
                    task_id,
                    parent_id,
                    title[:200],
                    int(bool(raw.get("done"))),
                    int(bool(children)),
                    order,
                    ts,
                ),
            )
            self._import_subtasks(
                conn,
                task_id,
                children,
                parent_id=subtask_id,
                depth=depth + 1,
                fallback_ts=ts,
            )


__all__ = [
    "MAX_SUBTASK_DEPTH",
    "PRIORITIES",
    "SuccesError",
    "SuccesNotFound",
    "SuccesStore",
    "now_ms",
]
