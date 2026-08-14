"""Projects, habits and notes for the native Succès workspace.

The phase-two entities use the same local-first operation log as tasks.  They
stay on the Mac, keep tombstones for later replication, and materialize data
that phase one deliberately preserved inside archived Life OS snapshots.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from diapason.succes.dates import normalize_time
from diapason.succes.store import (
    SuccesError,
    SuccesNotFound,
    SuccesStore,
    _clean_text,
    _safe_timestamp,
    _validate_iso_date,
    now_ms,
)

HABIT_FREQUENCIES = frozenset({"daily", "weekly", "monthly"})
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS succes_habits (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6366f1',
    frequency TEXT NOT NULL DEFAULT 'daily',
    created_date TEXT NOT NULL,
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    weekly_days_json TEXT NOT NULL DEFAULT '[]',
    month_week_slots_json TEXT NOT NULL DEFAULT '[]',
    month_week_day INTEGER NOT NULL DEFAULT 1,
    reminder_time TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS succes_habits_active_idx
    ON succes_habits(deleted_at_ms, updated_at_ms);
CREATE TABLE IF NOT EXISTS succes_habit_logs (
    habit_id TEXT NOT NULL REFERENCES succes_habits(id),
    log_date TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(habit_id, log_date)
);
CREATE INDEX IF NOT EXISTS succes_habit_logs_date_idx
    ON succes_habit_logs(log_date, done);
CREATE TABLE IF NOT EXISTS succes_notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS succes_notes_active_idx
    ON succes_notes(deleted_at_ms, updated_at_ms DESC);
PRAGMA user_version = 2;
"""


def _color(value: Any) -> str:
    raw = str(value or "#6366f1").strip()
    if not _COLOR_RE.fullmatch(raw):
        raise SuccesError("La couleur doit être au format hexadécimal #RRGGBB.")
    return raw.lower()


def _weekly_days(value: Any) -> list[int]:
    source = value if isinstance(value, list) else []
    days = sorted({int(item) for item in source if str(item).isdigit()})
    if any(day < 0 or day > 6 for day in days):
        raise SuccesError("Les jours hebdomadaires doivent être compris entre 0 et 6.")
    return days


def _month_slots(value: Any) -> list[int | str]:
    source = value if isinstance(value, list) else []
    slots: list[int | str] = []
    for item in source:
        if str(item) == "last":
            slots.append("last")
        elif str(item).isdigit() and 1 <= int(item) <= 4:
            slots.append(int(item))
        else:
            raise SuccesError(
                "Les occurrences mensuelles doivent être 1, 2, 3, 4 ou last."
            )
    return list(dict.fromkeys(slots))


def _sunday_weekday(value: date) -> int:
    return (value.weekday() + 1) % 7


def _is_last_weekday(value: date) -> bool:
    return (value + timedelta(days=7)).month != value.month


class SuccesWorkspaceStore(SuccesStore):
    """Task store extended with the remaining phase-two workspace entities."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__(db_path)
        with self._connect() as conn:
            conn.executescript(_WORKSPACE_SCHEMA)
            conn.commit()
        self.materialize_archived_snapshots()

    def _replayed_entity(
        self,
        conn: sqlite3.Connection,
        op_id: str | None,
        request: Mapping[str, Any],
        loader: Callable[[sqlite3.Connection, str], dict[str, Any] | None],
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
        entity_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
        return loader(conn, entity_id) if entity_id else payload

    # Projects ---------------------------------------------------------

    @staticmethod
    def _project_dict(
        row: sqlite3.Row, task_total: int, task_done: int
    ) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "color": row["color"],
            "icon": row["icon"],
            "startDate": row["start_date"],
            "endDate": row["end_date"],
            "createdAt": row["created_date"],
            "updatedAtMs": row["updated_at_ms"],
            "deletedAtMs": row["deleted_at_ms"],
            "taskTotal": task_total,
            "taskCompleted": task_done,
        }

    def _load_project(
        self, conn: sqlite3.Connection, project_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_projects WHERE id=? AND deleted_at_ms IS NULL",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        counts = conn.execute(
            """SELECT COUNT(*) total, COALESCE(SUM(done),0) completed
               FROM succes_tasks WHERE project_id=? AND deleted_at_ms IS NULL""",
            (project_id,),
        ).fetchone()
        return self._project_dict(row, int(counts["total"]), int(counts["completed"]))

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            project = self._load_project(conn, project_id)
        if project is None:
            raise SuccesNotFound("Ce projet n'existe pas ou a été supprimé.")
        return project

    def list_projects(self, *, search: str = "") -> list[dict[str, Any]]:
        query = "%" + search.strip().lower() + "%"
        with self._connect() as conn:
            ids = [
                row["id"]
                for row in conn.execute(
                    """SELECT id FROM succes_projects
                       WHERE deleted_at_ms IS NULL AND lower(name) LIKE ?
                       ORDER BY updated_at_ms DESC""",
                    (query,),
                ).fetchall()
            ]
            return [
                item
                for project_id in ids
                if (item := self._load_project(conn, project_id))
            ]

    def create_project(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        name = _clean_text(
            data.get("name"), field="Le nom du projet", maximum=200, required=True
        )
        description = _clean_text(
            data.get("description"), field="La description", maximum=4000
        )
        start_date = _validate_iso_date(
            str(data.get("startDate") or ""), "La date de début"
        )
        end_date = _validate_iso_date(str(data.get("endDate") or ""), "La date de fin")
        if start_date and end_date and end_date < start_date:
            raise SuccesError("La date de fin doit suivre la date de début.")
        request = {
            "action": "create_project",
            "name": name,
            "description": description,
            "color": _color(data.get("color")),
            "icon": _clean_text(data.get("icon"), field="L'icône", maximum=16),
            "startDate": start_date,
            "endDate": end_date,
        }
        project_id = str(data.get("id") or uuid.uuid4())
        timestamp = _safe_timestamp(data.get("updatedAtMs"))
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_project)
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_projects
                   (id,name,description,color,icon,start_date,end_date,created_date,
                    updated_at_ms,deleted_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    project_id,
                    name,
                    description,
                    request["color"],
                    request["icon"],
                    start_date,
                    end_date,
                    str(data.get("createdAt") or date.today().isoformat()),
                    timestamp,
                ),
            )
            project = self._load_project(conn, project_id)
            assert project is not None
            self._record_op(
                conn,
                entity="projects",
                entity_id=project_id,
                kind="upsert",
                payload=project,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            return project

    def update_project(
        self,
        project_id: str,
        patch: Mapping[str, Any],
        *,
        op_id: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_project(project_id)
        merged = {**current, **patch, "id": project_id}
        name = _clean_text(
            merged.get("name"), field="Le nom du projet", maximum=200, required=True
        )
        description = _clean_text(
            merged.get("description"), field="La description", maximum=4000
        )
        start_date = _validate_iso_date(
            str(merged.get("startDate") or ""), "La date de début"
        )
        end_date = _validate_iso_date(
            str(merged.get("endDate") or ""), "La date de fin"
        )
        if start_date and end_date and end_date < start_date:
            raise SuccesError("La date de fin doit suivre la date de début.")
        request = {
            "action": "update_project",
            "projectId": project_id,
            "patch": dict(patch),
        }
        timestamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_project)
            if replay is not None:
                return replay
            if self._load_project(conn, project_id) is None:
                raise SuccesNotFound("Ce projet n'existe pas ou a été supprimé.")
            conn.execute(
                """UPDATE succes_projects SET name=?,description=?,color=?,icon=?,
                   start_date=?,end_date=?,updated_at_ms=? WHERE id=?""",
                (
                    name,
                    description,
                    _color(merged.get("color")),
                    _clean_text(merged.get("icon"), field="L'icône", maximum=16),
                    start_date,
                    end_date,
                    timestamp,
                    project_id,
                ),
            )
            project = self._load_project(conn, project_id)
            assert project is not None
            self._record_op(
                conn,
                entity="projects",
                entity_id=project_id,
                kind="upsert",
                payload=project,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            return project

    def delete_project(self, project_id: str, *, op_id: str | None = None) -> None:
        project = self.get_project(project_id)
        timestamp = now_ms()
        request = {"action": "delete_project", "projectId": project_id}
        with self._transaction() as conn:
            if (
                op_id
                and conn.execute(
                    "SELECT 1 FROM succes_operations WHERE op_id=?", (op_id,)
                ).fetchone()
            ):
                return
            conn.execute(
                "UPDATE succes_projects SET deleted_at_ms=?,updated_at_ms=? WHERE id=?",
                (timestamp, timestamp, project_id),
            )
            self._record_op(
                conn,
                entity="projects",
                entity_id=project_id,
                kind="delete",
                payload={**project, "deletedAtMs": timestamp},
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )

    # Habits -----------------------------------------------------------

    @staticmethod
    def _habit_base(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "icon": row["icon"],
            "color": row["color"],
            "frequency": row["frequency"],
            "createdAt": row["created_date"],
            "startDate": row["start_date"],
            "endDate": row["end_date"],
            "weeklyDays": json.loads(row["weekly_days_json"]),
            "monthWeekSlots": json.loads(row["month_week_slots_json"]),
            "monthWeekDay": row["month_week_day"],
            "reminderTime": row["reminder_time"],
            "updatedAtMs": row["updated_at_ms"],
            "deletedAtMs": row["deleted_at_ms"],
        }

    def _load_habit(
        self, conn: sqlite3.Connection, habit_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_habits WHERE id=? AND deleted_at_ms IS NULL",
            (habit_id,),
        ).fetchone()
        return self._habit_base(row) if row is not None else None

    @staticmethod
    def _habit_due(habit: Mapping[str, Any], on_date: date) -> bool:
        iso = on_date.isoformat()
        if habit.get("startDate") and iso < str(habit["startDate"]):
            return False
        if habit.get("endDate") and iso > str(habit["endDate"]):
            return False
        frequency = str(habit.get("frequency") or "daily")
        if frequency == "daily":
            return True
        weekday = _sunday_weekday(on_date)
        if frequency == "weekly":
            days = habit.get("weeklyDays") or []
            return not days or weekday in days
        slots = habit.get("monthWeekSlots") or []
        if weekday != int(habit.get("monthWeekDay") or 1) or not slots:
            return False
        occurrence = ((on_date.day - 1) // 7) + 1
        return occurrence in slots or ("last" in slots and _is_last_weekday(on_date))

    def _habit_done(self, conn: sqlite3.Connection, habit_id: str, iso: str) -> bool:
        row = conn.execute(
            "SELECT done FROM succes_habit_logs WHERE habit_id=? AND log_date=?",
            (habit_id, iso),
        ).fetchone()
        return bool(row and row["done"])

    def _habit_streak(
        self, conn: sqlite3.Connection, habit: Mapping[str, Any], on_date: date
    ) -> int:
        streak = 0
        cursor = on_date
        for _ in range(366):
            if self._habit_due(habit, cursor):
                if not self._habit_done(conn, str(habit["id"]), cursor.isoformat()):
                    break
                streak += 1
            cursor -= timedelta(days=1)
        return streak

    def get_habit(self, habit_id: str, *, on_date: str | None = None) -> dict[str, Any]:
        iso = _validate_iso_date(on_date or date.today().isoformat())
        target = date.fromisoformat(iso)
        with self._connect() as conn:
            habit = self._load_habit(conn, habit_id)
            if habit is None:
                raise SuccesNotFound("Cette habitude n'existe pas ou a été supprimée.")
            habit["due"] = self._habit_due(habit, target)
            habit["done"] = self._habit_done(conn, habit_id, iso)
            habit["streak"] = self._habit_streak(conn, habit, target)
            habit["date"] = iso
            return habit

    def list_habits(self, *, on_date: str | None = None) -> list[dict[str, Any]]:
        iso = _validate_iso_date(on_date or date.today().isoformat())
        target = date.fromisoformat(iso)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM succes_habits WHERE deleted_at_ms IS NULL
                   ORDER BY updated_at_ms DESC"""
            ).fetchall()
            habits: list[dict[str, Any]] = []
            for row in rows:
                habit = self._habit_base(row)
                habit["due"] = self._habit_due(habit, target)
                habit["done"] = self._habit_done(conn, str(habit["id"]), iso)
                habit["streak"] = self._habit_streak(conn, habit, target)
                habit["date"] = iso
                habits.append(habit)
            return habits

    def _validated_habit(self, data: Mapping[str, Any]) -> dict[str, Any]:
        frequency = str(data.get("frequency") or "daily").lower()
        if frequency not in HABIT_FREQUENCIES:
            raise SuccesError("La fréquence doit être daily, weekly ou monthly.")
        days = _weekly_days(data.get("weeklyDays"))
        slots = _month_slots(data.get("monthWeekSlots"))
        if frequency == "weekly" and not days:
            raise SuccesError(
                "Choisissez au moins un jour pour l'habitude hebdomadaire."
            )
        if frequency == "monthly" and not slots:
            raise SuccesError("Choisissez au moins une occurrence mensuelle.")
        month_day = int(data.get("monthWeekDay") or 1)
        if month_day < 0 or month_day > 6:
            raise SuccesError("Le jour mensuel doit être compris entre 0 et 6.")
        start = _validate_iso_date(str(data.get("startDate") or ""), "La date de début")
        end = _validate_iso_date(str(data.get("endDate") or ""), "La date de fin")
        if start and end and end < start:
            raise SuccesError("La date de fin doit suivre la date de début.")
        try:
            reminder = normalize_time(str(data.get("reminderTime") or ""))
        except ValueError as exc:
            raise SuccesError(str(exc)) from exc
        return {
            "name": _clean_text(
                data.get("name"),
                field="Le nom de l'habitude",
                maximum=200,
                required=True,
            ),
            "icon": _clean_text(data.get("icon"), field="L'icône", maximum=16),
            "color": _color(data.get("color")),
            "frequency": frequency,
            "startDate": start or date.today().isoformat(),
            "endDate": end,
            "weeklyDays": days if frequency == "weekly" else [],
            "monthWeekSlots": slots if frequency == "monthly" else [],
            "monthWeekDay": month_day,
            "reminderTime": reminder,
        }

    def create_habit(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        clean = self._validated_habit(data)
        request = {"action": "create_habit", **clean}
        habit_id = str(data.get("id") or uuid.uuid4())
        timestamp = _safe_timestamp(data.get("updatedAtMs"))
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_habit)
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_habits
                   (id,name,icon,color,frequency,created_date,start_date,end_date,
                    weekly_days_json,month_week_slots_json,month_week_day,
                    reminder_time,updated_at_ms,deleted_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    habit_id,
                    clean["name"],
                    clean["icon"],
                    clean["color"],
                    clean["frequency"],
                    str(data.get("createdAt") or date.today().isoformat()),
                    clean["startDate"],
                    clean["endDate"],
                    json.dumps(clean["weeklyDays"]),
                    json.dumps(clean["monthWeekSlots"]),
                    clean["monthWeekDay"],
                    clean["reminderTime"],
                    timestamp,
                ),
            )
            habit = self._load_habit(conn, habit_id)
            assert habit is not None
            self._record_op(
                conn,
                entity="habits",
                entity_id=habit_id,
                kind="upsert",
                payload=habit,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
        return self.get_habit(habit_id)

    def update_habit(
        self, habit_id: str, patch: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        current = self.get_habit(habit_id)
        clean = self._validated_habit({**current, **patch})
        request = {"action": "update_habit", "habitId": habit_id, "patch": dict(patch)}
        timestamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_habit)
            if replay is not None:
                return self.get_habit(habit_id)
            if self._load_habit(conn, habit_id) is None:
                raise SuccesNotFound("Cette habitude n'existe pas ou a été supprimée.")
            conn.execute(
                """UPDATE succes_habits SET name=?,icon=?,color=?,frequency=?,
                   start_date=?,end_date=?,weekly_days_json=?,month_week_slots_json=?,
                   month_week_day=?,reminder_time=?,updated_at_ms=? WHERE id=?""",
                (
                    clean["name"],
                    clean["icon"],
                    clean["color"],
                    clean["frequency"],
                    clean["startDate"],
                    clean["endDate"],
                    json.dumps(clean["weeklyDays"]),
                    json.dumps(clean["monthWeekSlots"]),
                    clean["monthWeekDay"],
                    clean["reminderTime"],
                    timestamp,
                    habit_id,
                ),
            )
            habit = self._load_habit(conn, habit_id)
            assert habit is not None
            self._record_op(
                conn,
                entity="habits",
                entity_id=habit_id,
                kind="upsert",
                payload=habit,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
        return self.get_habit(habit_id)

    def set_habit_done(
        self,
        habit_id: str,
        log_date: str,
        done: bool,
        *,
        op_id: str | None = None,
    ) -> dict[str, Any]:
        self.get_habit(habit_id, on_date=log_date)
        iso = _validate_iso_date(log_date)
        request = {
            "action": "set_habit_done",
            "habitId": habit_id,
            "date": iso,
            "done": bool(done),
        }
        timestamp = now_ms()
        with self._transaction() as conn:
            if op_id:
                row = conn.execute(
                    "SELECT request_json FROM succes_operations WHERE op_id=?", (op_id,)
                ).fetchone()
                if row:
                    if row["request_json"] != self._canonical_json(request):
                        raise SuccesError(
                            "Cet identifiant d'opération a déjà été utilisé "
                            "avec d'autres paramètres."
                        )
                    return self.get_habit(habit_id, on_date=iso)
            conn.execute(
                """INSERT INTO succes_habit_logs(habit_id,log_date,done,updated_at_ms)
                   VALUES (?,?,?,?) ON CONFLICT(habit_id,log_date) DO UPDATE SET
                   done=excluded.done,updated_at_ms=excluded.updated_at_ms""",
                (habit_id, iso, int(done), timestamp),
            )
            payload = {"id": f"{habit_id}_{iso}", **request, "updatedAtMs": timestamp}
            self._record_op(
                conn,
                entity="habit_logs",
                entity_id=payload["id"],
                kind="habitlog_set",
                payload=payload,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
        return self.get_habit(habit_id, on_date=iso)

    def delete_habit(self, habit_id: str, *, op_id: str | None = None) -> None:
        habit = self.get_habit(habit_id)
        timestamp = now_ms()
        request = {"action": "delete_habit", "habitId": habit_id}
        with self._transaction() as conn:
            if (
                op_id
                and conn.execute(
                    "SELECT 1 FROM succes_operations WHERE op_id=?", (op_id,)
                ).fetchone()
            ):
                return
            conn.execute(
                "UPDATE succes_habits SET deleted_at_ms=?,updated_at_ms=? WHERE id=?",
                (timestamp, timestamp, habit_id),
            )
            self._record_op(
                conn,
                entity="habits",
                entity_id=habit_id,
                kind="delete",
                payload={**habit, "deletedAtMs": timestamp},
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )

    # Notes ------------------------------------------------------------

    @staticmethod
    def _note_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "updatedAtMs": row["updated_at_ms"],
            "deletedAtMs": row["deleted_at_ms"],
        }

    def _load_note(
        self, conn: sqlite3.Connection, note_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_notes WHERE id=? AND deleted_at_ms IS NULL",
            (note_id,),
        ).fetchone()
        return self._note_dict(row) if row is not None else None

    def get_note(self, note_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            note = self._load_note(conn, note_id)
        if note is None:
            raise SuccesNotFound("Cette note n'existe pas ou a été supprimée.")
        return note

    def list_notes(self, *, search: str = "") -> list[dict[str, Any]]:
        query = "%" + search.strip().lower() + "%"
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM succes_notes WHERE deleted_at_ms IS NULL
                   AND (lower(title) LIKE ? OR lower(content) LIKE ?)
                   ORDER BY updated_at_ms DESC""",
                (query, query),
            ).fetchall()
        return [self._note_dict(row) for row in rows]

    @staticmethod
    def _note_fields(data: Mapping[str, Any]) -> tuple[str, str]:
        title = _clean_text(
            data.get("title"), field="Le titre de la note", maximum=200, required=True
        )
        content = str(data.get("content") or "")
        if len(content) > 100_000:
            raise SuccesError(
                "Le contenu de la note ne peut pas dépasser 100 000 caractères."
            )
        return title, content

    def create_note(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        title, content = self._note_fields(data)
        request = {"action": "create_note", "title": title, "content": content}
        note_id = str(data.get("id") or uuid.uuid4())
        timestamp = _safe_timestamp(data.get("updatedAtMs"))
        iso_time = str(data.get("updatedAt") or date.today().isoformat())
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_note)
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_notes
                   (id,title,content,created_at,updated_at,updated_at_ms,deleted_at_ms)
                   VALUES (?,?,?,?,?,?,NULL)""",
                (
                    note_id,
                    title,
                    content,
                    str(data.get("createdAt") or date.today().isoformat()),
                    iso_time,
                    timestamp,
                ),
            )
            note = self._load_note(conn, note_id)
            assert note is not None
            self._record_op(
                conn,
                entity="notes",
                entity_id=note_id,
                kind="upsert",
                payload=note,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            return note

    def update_note(
        self, note_id: str, patch: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        current = self.get_note(note_id)
        title, content = self._note_fields({**current, **patch})
        request = {"action": "update_note", "noteId": note_id, "patch": dict(patch)}
        timestamp = now_ms()
        iso_time = date.today().isoformat()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_note)
            if replay is not None:
                return replay
            if self._load_note(conn, note_id) is None:
                raise SuccesNotFound("Cette note n'existe pas ou a été supprimée.")
            conn.execute(
                """UPDATE succes_notes SET title=?,content=?,updated_at=?,
                   updated_at_ms=? WHERE id=?""",
                (title, content, iso_time, timestamp, note_id),
            )
            note = self._load_note(conn, note_id)
            assert note is not None
            self._record_op(
                conn,
                entity="notes",
                entity_id=note_id,
                kind="upsert",
                payload=note,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            return note

    def delete_note(self, note_id: str, *, op_id: str | None = None) -> None:
        note = self.get_note(note_id)
        timestamp = now_ms()
        request = {"action": "delete_note", "noteId": note_id}
        with self._transaction() as conn:
            if (
                op_id
                and conn.execute(
                    "SELECT 1 FROM succes_operations WHERE op_id=?", (op_id,)
                ).fetchone()
            ):
                return
            conn.execute(
                "UPDATE succes_notes SET deleted_at_ms=?,updated_at_ms=? WHERE id=?",
                (timestamp, timestamp, note_id),
            )
            self._record_op(
                conn,
                entity="notes",
                entity_id=note_id,
                kind="delete",
                payload={**note, "deletedAtMs": timestamp},
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )

    # Dashboard and migration ----------------------------------------

    def dashboard(self, *, on_date: str | None = None) -> dict[str, Any]:
        iso = _validate_iso_date(on_date or date.today().isoformat())
        tasks = self.list_tasks(scheduled_date=iso, include_done=True)
        habits = self.list_habits(on_date=iso)
        due = [habit for habit in habits if habit["due"]]
        return {
            "date": iso,
            "tasks": {
                "total": len(tasks),
                "completed": sum(bool(task["done"]) for task in tasks),
            },
            "habits": {
                "due": len(due),
                "completed": sum(bool(habit["done"]) for habit in due),
            },
            "projects": len(self.list_projects()),
            "notes": len(self.list_notes()),
        }

    def materialize_archived_snapshots(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT snapshot_json FROM succes_imports ORDER BY imported_at_ms"
            ).fetchall()
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            self._materialize_workspace_snapshot(snapshot)

    def import_legacy_snapshot(
        self, snapshot: Mapping[str, Any], *, source: str = "Life OS PHP/Flutter"
    ) -> dict[str, Any]:
        summary = super().import_legacy_snapshot(snapshot, source=source)
        workspace = self._materialize_workspace_snapshot(snapshot)
        return {**summary, **workspace}

    def _materialize_workspace_snapshot(
        self, snapshot: Mapping[str, Any]
    ) -> dict[str, int]:
        state = (
            snapshot.get("state")
            if isinstance(snapshot.get("state"), Mapping)
            else snapshot
        )
        if not isinstance(state, Mapping):
            return {"habitsImported": 0, "notesImported": 0, "habitLogsImported": 0}
        summary = {"habitsImported": 0, "notesImported": 0, "habitLogsImported": 0}
        with self._transaction() as conn:
            for raw in (
                state.get("habits", []) if isinstance(state.get("habits"), list) else []
            ):
                if not isinstance(raw, Mapping):
                    continue
                habit_id = str(raw.get("id") or "").strip()
                if not habit_id or not str(raw.get("name") or "").strip():
                    continue
                timestamp = _safe_timestamp(raw.get("updatedAtMs"), fallback=0)
                current = conn.execute(
                    "SELECT updated_at_ms FROM succes_habits WHERE id=?", (habit_id,)
                ).fetchone()
                if current and current["updated_at_ms"] >= timestamp:
                    continue
                try:
                    clean = self._validated_habit(raw)
                except SuccesError:
                    continue
                conn.execute(
                    """INSERT INTO succes_habits
                       (id,name,icon,color,frequency,created_date,start_date,end_date,
                        weekly_days_json,month_week_slots_json,month_week_day,
                        reminder_time,updated_at_ms,deleted_at_ms)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                       ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                       icon=excluded.icon,color=excluded.color,frequency=excluded.frequency,
                       created_date=excluded.created_date,start_date=excluded.start_date,
                       end_date=excluded.end_date,weekly_days_json=excluded.weekly_days_json,
                       month_week_slots_json=excluded.month_week_slots_json,
                       month_week_day=excluded.month_week_day,
                       reminder_time=excluded.reminder_time,
                       updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL""",
                    (
                        habit_id,
                        clean["name"],
                        clean["icon"],
                        clean["color"],
                        clean["frequency"],
                        str(raw.get("createdAt") or clean["startDate"]),
                        clean["startDate"],
                        clean["endDate"],
                        json.dumps(clean["weeklyDays"]),
                        json.dumps(clean["monthWeekSlots"]),
                        clean["monthWeekDay"],
                        clean["reminderTime"],
                        timestamp,
                    ),
                )
                summary["habitsImported"] += 1
            for raw in (
                state.get("notes", []) if isinstance(state.get("notes"), list) else []
            ):
                if not isinstance(raw, Mapping):
                    continue
                note_id = str(raw.get("id") or "").strip()
                if not note_id or not str(raw.get("title") or "").strip():
                    continue
                timestamp = _safe_timestamp(raw.get("updatedAtMs"), fallback=0)
                current = conn.execute(
                    "SELECT updated_at_ms FROM succes_notes WHERE id=?", (note_id,)
                ).fetchone()
                if current and current["updated_at_ms"] >= timestamp:
                    continue
                try:
                    title, content = self._note_fields(raw)
                except SuccesError:
                    continue
                conn.execute(
                    """INSERT INTO succes_notes
                       (id,title,content,created_at,updated_at,updated_at_ms,deleted_at_ms)
                       VALUES (?,?,?,?,?,?,NULL) ON CONFLICT(id) DO UPDATE SET
                       title=excluded.title,content=excluded.content,
                       created_at=excluded.created_at,updated_at=excluded.updated_at,
                       updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL""",
                    (
                        note_id,
                        title,
                        content,
                        str(raw.get("createdAt") or ""),
                        str(raw.get("updatedAt") or ""),
                        timestamp,
                    ),
                )
                summary["notesImported"] += 1
            logs = (
                state.get("habitLogs")
                if isinstance(state.get("habitLogs"), Mapping)
                else {}
            )
            logs_at = (
                state.get("habitLogsAt")
                if isinstance(state.get("habitLogsAt"), Mapping)
                else {}
            )
            for key, value in logs_at.items():
                raw_key = str(key)
                habit_id, separator, iso = raw_key.rpartition("_")
                if not separator or not habit_id:
                    continue
                try:
                    _validate_iso_date(iso)
                except SuccesError:
                    continue
                if not conn.execute(
                    "SELECT 1 FROM succes_habits WHERE id=? AND deleted_at_ms IS NULL",
                    (habit_id,),
                ).fetchone():
                    continue
                timestamp = _safe_timestamp(value, fallback=0)
                current = conn.execute(
                    """SELECT updated_at_ms FROM succes_habit_logs
                       WHERE habit_id=? AND log_date=?""",
                    (habit_id, iso),
                ).fetchone()
                if current and current["updated_at_ms"] >= timestamp:
                    continue
                conn.execute(
                    """INSERT INTO succes_habit_logs
                       (habit_id,log_date,done,updated_at_ms)
                       VALUES (?,?,?,?) ON CONFLICT(habit_id,log_date) DO UPDATE SET
                       done=excluded.done,updated_at_ms=excluded.updated_at_ms""",
                    (habit_id, iso, int(bool(logs.get(key))), timestamp),
                )
                summary["habitLogsImported"] += 1
        return summary


__all__ = ["HABIT_FREQUENCIES", "SuccesWorkspaceStore"]
