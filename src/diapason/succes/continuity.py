"""Recurring plans, quotes and year review for the native Succès domain.

This module translates the remaining Life OS business rules into Diapason's
existing SQLite/operation-log architecture.  It deliberately stays local;
remote replication is a separate, explicitly configured phase.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from diapason.succes.store import (
    PRIORITIES,
    SuccesError,
    SuccesNotFound,
    _clean_text,
    _safe_timestamp,
    _validate_iso_date,
    now_ms,
)
from diapason.succes.workspace import SuccesWorkspaceStore, _month_slots, _weekly_days

TEMPLATE_FREQUENCIES = frozenset({"daily", "weekly", "monthly"})
TEMPLATE_KINDS = frozenset({"task", "habit"})
QUOTE_CATEGORIES = frozenset(
    {"philosophie", "bienetre", "developpement", "sagesse", "motivation", "autre"}
)

_CONTINUITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS succes_task_templates (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '',
    frequency TEXT NOT NULL DEFAULT 'weekly',
    days_of_week_json TEXT NOT NULL DEFAULT '[]',
    weekly_days_json TEXT NOT NULL DEFAULT '[]',
    month_week_slots_json TEXT NOT NULL DEFAULT '[]',
    month_week_dow INTEGER NOT NULL DEFAULT 1,
    project_id TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'medium',
    template_kind TEXT NOT NULL DEFAULT 'task',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    linked_habit_id TEXT NOT NULL DEFAULT '',
    created_date TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS succes_templates_active_idx
    ON succes_task_templates(deleted_at_ms, active, start_date, end_date);
CREATE TABLE IF NOT EXISTS succes_quotes (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'autre',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS succes_quotes_active_idx
    ON succes_quotes(deleted_at_ms, category, updated_at_ms DESC);
CREATE TABLE IF NOT EXISTS succes_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
PRAGMA user_version = 3;
"""


def _period_matches(iso: str, year: int, month: int | None) -> bool:
    prefix = f"{year:04d}" if month is None else f"{year:04d}-{month:02d}"
    return bool(iso) and iso.startswith(prefix)


def _timestamp_iso(value: int) -> str:
    if value <= 0:
        return ""
    try:
        return datetime.fromtimestamp(value / 1000).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


class SuccesContinuityStore(SuccesWorkspaceStore):
    """Succès store completed with recurrence and retrospective services."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__(db_path)
        with self._connect() as conn:
            conn.executescript(_CONTINUITY_SCHEMA)
            conn.commit()
        self.materialize_continuity_archives()

    # Recurring templates --------------------------------------------

    @staticmethod
    def _template_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "emoji": row["emoji"],
            "frequency": row["frequency"],
            "daysOfWeek": json.loads(row["days_of_week_json"]),
            "weeklyDays": json.loads(row["weekly_days_json"]),
            "monthWeekSlots": json.loads(row["month_week_slots_json"]),
            "monthWeekDow": row["month_week_dow"],
            "projectId": row["project_id"],
            "priority": row["priority"],
            "templateKind": row["template_kind"],
            "startDate": row["start_date"],
            "endDate": row["end_date"],
            "active": bool(row["active"]),
            "linkedHabitId": row["linked_habit_id"],
            "createdAt": row["created_date"],
            "updatedAtMs": row["updated_at_ms"],
            "deletedAtMs": row["deleted_at_ms"],
        }

    def _load_template(
        self, conn: sqlite3.Connection, template_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_task_templates WHERE id=? AND deleted_at_ms IS NULL",
            (template_id,),
        ).fetchone()
        return self._template_dict(row) if row is not None else None

    def get_template(self, template_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            item = self._load_template(conn, template_id)
        if item is None:
            raise SuccesNotFound("Ce modèle récurrent n'existe pas ou a été supprimé.")
        return item

    def list_templates(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        where = "deleted_at_ms IS NULL"
        if not include_inactive:
            where += " AND active=1"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM succes_task_templates WHERE {where} "
                "ORDER BY active DESC, updated_at_ms DESC"
            ).fetchall()
        return [self._template_dict(row) for row in rows]

    @staticmethod
    def _validated_template(data: Mapping[str, Any]) -> dict[str, Any]:
        title = _clean_text(
            data.get("title"), field="Le titre du modèle", maximum=200, required=True
        )
        frequency = str(data.get("frequency") or "weekly").lower()
        if frequency not in TEMPLATE_FREQUENCIES:
            raise SuccesError("La fréquence doit être daily, weekly ou monthly.")
        kind = str(data.get("templateKind") or data.get("kind") or "task").lower()
        if kind not in TEMPLATE_KINDS:
            raise SuccesError("Le type du modèle doit être task ou habit.")
        priority = str(data.get("priority") or "medium").lower()
        if priority not in PRIORITIES:
            raise SuccesError("La priorité du modèle n'est pas valide.")
        start = _validate_iso_date(str(data.get("startDate") or ""), "La date de début")
        end = _validate_iso_date(str(data.get("endDate") or ""), "La date de fin")
        if not start or not end:
            raise SuccesError("Les dates de début et de fin sont obligatoires.")
        if end < start:
            raise SuccesError("La date de fin doit suivre la date de début.")
        dow = int(data.get("monthWeekDow", 1))
        if dow < 0 or dow > 6:
            raise SuccesError("Le jour mensuel doit être compris entre 0 et 6.")
        days = _weekly_days(data.get("daysOfWeek"))
        weekly = _weekly_days(data.get("weeklyDays"))
        slots = _month_slots(data.get("monthWeekSlots"))
        if frequency == "weekly" and not (weekly or days):
            raise SuccesError(
                "Choisissez au moins un jour pour le modèle hebdomadaire."
            )
        if frequency == "monthly" and not slots:
            raise SuccesError("Choisissez au moins une occurrence mensuelle.")
        return {
            "title": title,
            "emoji": _clean_text(data.get("emoji"), field="L'icône", maximum=16),
            "frequency": frequency,
            "daysOfWeek": days,
            "weeklyDays": weekly,
            "monthWeekSlots": slots,
            "monthWeekDow": dow,
            "projectId": str(data.get("projectId") or ""),
            "priority": priority,
            "templateKind": kind,
            "startDate": start,
            "endDate": end,
            "active": bool(data.get("active", True)),
        }

    def create_template(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        clean = self._validated_template(data)
        template_id = str(data.get("id") or f"tpl_{uuid.uuid4().hex[:12]}")
        timestamp = _safe_timestamp(data.get("updatedAtMs"))
        request = {"action": "create_template", **clean}
        linked_habit_id = (
            f"template-habit-{template_id}" if clean["templateKind"] == "habit" else ""
        )
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_template)
            if replay is not None:
                return replay
            if conn.execute(
                "SELECT 1 FROM succes_task_templates WHERE id=?", (template_id,)
            ).fetchone():
                raise SuccesError("Un modèle avec cet identifiant existe déjà.")
            conn.execute(
                """INSERT INTO succes_task_templates
                   (id,title,emoji,frequency,days_of_week_json,weekly_days_json,
                    month_week_slots_json,month_week_dow,project_id,priority,
                    template_kind,start_date,end_date,active,linked_habit_id,
                    created_date,updated_at_ms,deleted_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
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
                    linked_habit_id,
                    str(data.get("createdAt") or date.today().isoformat()),
                    timestamp,
                ),
            )
            item = self._load_template(conn, template_id)
            assert item is not None
            self._record_op(
                conn,
                entity="todo_templates",
                entity_id=template_id,
                kind="upsert",
                payload=item,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
        if clean["templateKind"] == "habit":
            self._reconcile_template_habit(self.get_template(template_id))
        return self.get_template(template_id)

    def update_template(
        self, template_id: str, patch: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        current = self.get_template(template_id)
        clean = self._validated_template({**current, **patch})
        timestamp = _safe_timestamp(patch.get("updatedAtMs"))
        linked_habit_id = (
            current.get("linkedHabitId") or f"template-habit-{template_id}"
            if clean["templateKind"] == "habit"
            else ""
        )
        request = {
            "action": "update_template",
            "templateId": template_id,
            "patch": dict(patch),
        }
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_template)
            if replay is not None:
                return replay
            conn.execute(
                """UPDATE succes_task_templates SET title=?,emoji=?,frequency=?,
                   days_of_week_json=?,weekly_days_json=?,month_week_slots_json=?,
                   month_week_dow=?,project_id=?,priority=?,template_kind=?,
                   start_date=?,end_date=?,active=?,linked_habit_id=?,updated_at_ms=?
                   WHERE id=? AND deleted_at_ms IS NULL""",
                (
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
                    linked_habit_id,
                    timestamp,
                    template_id,
                ),
            )
            conn.execute(
                """UPDATE succes_tasks
                   SET title=?,emoji=?,priority=?,project_id=?,updated_at_ms=?
                   WHERE template_id=? AND done=0 AND deleted_at_ms IS NULL""",
                (
                    clean["title"],
                    clean["emoji"],
                    clean["priority"],
                    clean["projectId"],
                    timestamp,
                    template_id,
                ),
            )
            item = self._load_template(conn, template_id)
            assert item is not None
            self._record_op(
                conn,
                entity="todo_templates",
                entity_id=template_id,
                kind="upsert",
                payload=item,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            task_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM succes_tasks WHERE template_id=? AND done=0 "
                    "AND deleted_at_ms IS NULL",
                    (template_id,),
                ).fetchall()
            ]
            for task_id in task_ids:
                task = self._load_task(conn, task_id)
                if task:
                    self._record_op(
                        conn,
                        entity="tasks",
                        entity_id=task_id,
                        kind="upsert",
                        payload=task,
                        request=request,
                        timestamp_ms=timestamp,
                    )
        if current["templateKind"] == "habit" and clean["templateKind"] != "habit":
            self._remove_linked_habit(str(current.get("linkedHabitId") or ""))
        elif clean["templateKind"] == "habit":
            self._reconcile_template_habit(self.get_template(template_id))
        return self.get_template(template_id)

    @staticmethod
    def _matches_template(template: Mapping[str, Any], target: date) -> bool:
        iso = target.isoformat()
        if (
            not template.get("active")
            or iso < template["startDate"]
            or iso > template["endDate"]
        ):
            return False
        frequency = template["frequency"]
        sunday_day = (target.weekday() + 1) % 7
        if frequency == "daily":
            return True
        if frequency == "weekly":
            days = template["weeklyDays"] or template["daysOfWeek"]
            return sunday_day in days
        occurrence = ((target.day - 1) // 7) + 1
        is_last = (target + timedelta(days=7)).month != target.month
        slots = template["monthWeekSlots"]
        return sunday_day == template["monthWeekDow"] and (
            occurrence in slots or (is_last and "last" in slots)
        )

    def materialize_templates(self, start_date: str, end_date: str) -> dict[str, Any]:
        start_iso = _validate_iso_date(start_date, "La date de début")
        end_iso = _validate_iso_date(end_date, "La date de fin")
        if not start_iso or not end_iso or end_iso < start_iso:
            raise SuccesError("La période de matérialisation n'est pas valide.")
        start, end = date.fromisoformat(start_iso), date.fromisoformat(end_iso)
        if (end - start).days > 370:
            raise SuccesError("La période ne peut pas dépasser 370 jours.")
        templates = [
            item
            for item in self.list_templates(include_inactive=False)
            if item["templateKind"] == "task"
        ]
        created: list[dict[str, Any]] = []
        timestamp = now_ms()
        with self._transaction() as conn:
            cursor = start
            while cursor <= end:
                for template in templates:
                    if not self._matches_template(template, cursor):
                        continue
                    task_id = f"tpl_{template['id']}_{cursor.isoformat()}"
                    if conn.execute(
                        "SELECT 1 FROM succes_tasks WHERE id=?", (task_id,)
                    ).fetchone():
                        continue
                    conn.execute(
                        """INSERT INTO succes_tasks
                           (id,title,done,priority,scheduled_date,scheduled_time,
                            project_id,category,notes,emoji,template_id,group_id,
                            order_index,created_date,completed_date,postponed_count,
                            updated_at_ms,deleted_at_ms)
                           VALUES (?,?,0,?,?,'',?,'','',?,?,'',0,?,'',0,?,NULL)""",
                        (
                            task_id,
                            template["title"],
                            template["priority"],
                            cursor.isoformat(),
                            template["projectId"],
                            template["emoji"],
                            template["id"],
                            date.today().isoformat(),
                            timestamp,
                        ),
                    )
                    task = self._load_task(conn, task_id)
                    assert task is not None
                    request = {
                        "action": "materialize_template",
                        "templateId": template["id"],
                        "date": cursor.isoformat(),
                    }
                    self._record_op(
                        conn,
                        entity="tasks",
                        entity_id=task_id,
                        kind="upsert",
                        payload=task,
                        request=request,
                        timestamp_ms=timestamp,
                    )
                    created.append(task)
                cursor += timedelta(days=1)
        return {
            "created": created,
            "count": len(created),
            "startDate": start_iso,
            "endDate": end_iso,
        }

    def _reconcile_template_habit(self, template: Mapping[str, Any]) -> None:
        habit_id = str(
            template.get("linkedHabitId") or f"template-habit-{template['id']}"
        )
        priority_colors = {"high": "#ef4444", "urgent": "#ef4444", "low": "#22c55e"}
        payload = {
            "id": habit_id,
            "name": template["title"],
            "icon": template["emoji"],
            "color": priority_colors.get(template["priority"], "#8b5cf6"),
            "frequency": template["frequency"],
            "weeklyDays": template["weeklyDays"] or template["daysOfWeek"],
            "monthWeekSlots": template["monthWeekSlots"],
            "monthWeekDay": template["monthWeekDow"],
            "startDate": template["startDate"],
            "endDate": template["endDate"],
        }
        try:
            self.get_habit(habit_id)
        except SuccesNotFound:
            self.create_habit(payload)
        else:
            self.update_habit(habit_id, payload)

    def _remove_linked_habit(self, habit_id: str) -> None:
        if not habit_id:
            return
        try:
            self.delete_habit(habit_id)
        except SuccesNotFound:
            pass

    def delete_template(
        self, template_id: str, *, op_id: str | None = None
    ) -> dict[str, Any]:
        template = self.get_template(template_id)
        timestamp = now_ms()
        request = {"action": "delete_template", "templateId": template_id}
        deleted_tasks = 0
        with self._transaction() as conn:
            if (
                op_id
                and conn.execute(
                    "SELECT 1 FROM succes_operations WHERE op_id=?", (op_id,)
                ).fetchone()
            ):
                return {"deleted": True, "tasksDeleted": 0, "id": template_id}
            rows = conn.execute(
                """SELECT id FROM succes_tasks
                   WHERE template_id=? AND deleted_at_ms IS NULL""",
                (template_id,),
            ).fetchall()
            for row in rows:
                task_id = row["id"]
                conn.execute(
                    """UPDATE succes_tasks
                       SET deleted_at_ms=?,updated_at_ms=? WHERE id=?""",
                    (timestamp, timestamp, task_id),
                )
                self._record_op(
                    conn,
                    entity="tasks",
                    entity_id=task_id,
                    kind="delete",
                    payload={"id": task_id, "deletedAtMs": timestamp},
                    request=request,
                    timestamp_ms=timestamp,
                )
                deleted_tasks += 1
            conn.execute(
                """UPDATE succes_task_templates
                   SET deleted_at_ms=?,updated_at_ms=? WHERE id=?""",
                (timestamp, timestamp, template_id),
            )
            self._record_op(
                conn,
                entity="todo_templates",
                entity_id=template_id,
                kind="delete",
                payload={**template, "deletedAtMs": timestamp},
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
        self._remove_linked_habit(str(template.get("linkedHabitId") or ""))
        return {"deleted": True, "tasksDeleted": deleted_tasks, "id": template_id}

    # Quotes ----------------------------------------------------------

    @staticmethod
    def _quote_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "text": row["text"],
            "author": row["author"],
            "category": row["category"],
            "updatedAtMs": row["updated_at_ms"],
            "deletedAtMs": row["deleted_at_ms"],
        }

    def _load_quote(
        self, conn: sqlite3.Connection, quote_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_quotes WHERE id=? AND deleted_at_ms IS NULL",
            (quote_id,),
        ).fetchone()
        return self._quote_dict(row) if row is not None else None

    def list_quotes(self, *, category: str = "") -> list[dict[str, Any]]:
        params: tuple[Any, ...] = ()
        where = "deleted_at_ms IS NULL"
        if category:
            where += " AND category=?"
            params = (category,)
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM succes_quotes
                    WHERE {where} ORDER BY updated_at_ms DESC""",
                params,
            ).fetchall()
        return [self._quote_dict(row) for row in rows]

    def quote_for_date(self, iso: str) -> dict[str, Any] | None:
        target = date.fromisoformat(_validate_iso_date(iso))
        quotes = self.list_quotes()
        return quotes[target.toordinal() % len(quotes)] if quotes else None

    def create_quote(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        text = _clean_text(
            data.get("text"), field="La citation", maximum=1000, required=True
        )
        author = _clean_text(data.get("author"), field="L'auteur", maximum=200)
        category = str(data.get("category") or "autre").lower()
        if category not in QUOTE_CATEGORIES:
            category = "autre"
        quote_id = str(data.get("id") or f"quote_{uuid.uuid4().hex[:12]}")
        timestamp = _safe_timestamp(data.get("updatedAtMs"))
        request = {
            "action": "create_quote",
            "text": text,
            "author": author,
            "category": category,
        }
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_quote)
            if replay is not None:
                return replay
            conn.execute(
                "INSERT INTO succes_quotes"
                "(id,text,author,category,updated_at_ms,deleted_at_ms) "
                "VALUES(?,?,?,?,?,NULL)",
                (quote_id, text, author, category, timestamp),
            )
            item = self._load_quote(conn, quote_id)
            assert item is not None
            self._record_op(
                conn,
                entity="quotes",
                entity_id=quote_id,
                kind="upsert",
                payload=item,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            return item

    def delete_quote(self, quote_id: str, *, op_id: str | None = None) -> None:
        with self._connect() as conn:
            item = self._load_quote(conn, quote_id)
        if item is None:
            raise SuccesNotFound("Cette citation n'existe pas ou a été supprimée.")
        timestamp = now_ms()
        request = {"action": "delete_quote", "quoteId": quote_id}
        with self._transaction() as conn:
            conn.execute(
                "UPDATE succes_quotes SET deleted_at_ms=?,updated_at_ms=? WHERE id=?",
                (timestamp, timestamp, quote_id),
            )
            self._record_op(
                conn,
                entity="quotes",
                entity_id=quote_id,
                kind="delete",
                payload={**item, "deletedAtMs": timestamp},
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )

    # Dashboard, year review and export -------------------------------

    def dashboard(self, *, on_date: str | None = None) -> dict[str, Any]:
        iso = _validate_iso_date(on_date or date.today().isoformat())
        target = date.fromisoformat(iso)
        week_start = target - timedelta(days=target.weekday())
        week_dates = [
            (week_start + timedelta(days=index)).isoformat() for index in range(7)
        ]
        all_tasks = self.list_tasks(include_done=True)
        week_tasks = [task for task in all_tasks if task["date"] in week_dates]
        today_tasks = [task for task in all_tasks if task["date"] == iso]
        habits = self.list_habits(on_date=iso)
        due = [habit for habit in habits if habit["due"]]
        projects = self.list_projects()
        weekly_counts = [
            sum(task["date"] == day for task in all_tasks) for day in week_dates
        ]
        return {
            "date": iso,
            "tasks": {
                "todayTotal": len(today_tasks),
                "todayOpen": sum(not task["done"] for task in today_tasks),
                "weekTotal": len(week_tasks),
                "weekCompleted": sum(bool(task["done"]) for task in week_tasks),
                "weeklyCounts": weekly_counts,
            },
            "habits": {
                "due": len(due),
                "completed": sum(bool(habit["done"]) for habit in due),
                "items": due,
            },
            "projects": projects,
            "notes": len(self.list_notes()),
            "quote": self.quote_for_date(iso),
        }

    def _longest_habit_streak(
        self,
        habits: list[dict[str, Any]],
        year: int,
        month: int | None,
    ) -> int:
        """La plus longue série JAMAIS tenue sur la période, pas celle en cours.

        Le bilan prenait le maximum des séries courantes — c'est-à-dire ce que
        `list_habits` calcule pour aujourd'hui. Un bilan sert précisément à
        regarder en arrière : quelqu'un qui a tenu soixante jours au printemps
        puis s'est arrêté lisait « 0 », et son meilleur mois avait disparu du
        seul écran fait pour s'en souvenir.

        La série est mesurée sur les jours DUS : sauter un dimanche pour une
        habitude hebdomadaire n'est pas une rupture, et compter en jours
        calendaires punirait les habitudes non quotidiennes.
        """
        if not habits:
            return 0

        start = date(year, month or 1, 1)
        if month:
            end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
        else:
            end = date(year, 12, 31)
        # Inutile de parcourir un futur qui n'a pas encore eu lieu.
        end = min(end, date.today())
        if end < start:
            return 0

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT habit_id, log_date FROM succes_habit_logs "
                "WHERE done=1 AND log_date BETWEEN ? AND ?",
                (start.isoformat(), end.isoformat()),
            ).fetchall()

        done_by_habit: dict[str, set[str]] = {}
        for row in rows:
            done_by_habit.setdefault(str(row["habit_id"]), set()).add(
                str(row["log_date"])
            )

        best = 0
        for habit in habits:
            done = done_by_habit.get(str(habit["id"]))
            if not done:
                continue
            run = 0
            cursor = start
            while cursor <= end:
                if self._habit_due(habit, cursor):
                    if cursor.isoformat() in done:
                        run += 1
                        best = max(best, run)
                    else:
                        run = 0
                cursor += timedelta(days=1)
        return best

    def year_review(self, year: int, *, month: int | None = None) -> dict[str, Any]:
        current_year = date.today().year
        if year < 1970 or year > current_year + 30:
            raise SuccesError("L'année demandée est hors de la plage autorisée.")
        if month is not None and (month < 1 or month > 12):
            raise SuccesError("Le mois doit être compris entre 1 et 12.")
        tasks = self.list_tasks(include_done=True)
        projects = self.list_projects()
        habits = self.list_habits(on_date=date.today().isoformat())
        task_created = sum(
            bool(task["date"]) and _period_matches(task["createdAt"], year, month)
            for task in tasks
        )
        task_completed = sum(
            bool(task["done"])
            and _period_matches(_timestamp_iso(int(task["updatedAtMs"])), year, month)
            for task in tasks
        )
        project_created = sum(
            _period_matches(project["createdAt"], year, month) for project in projects
        )
        project_completed = 0
        for project in projects:
            linked = [task for task in tasks if task["projectId"] == project["id"]]
            if linked and all(task["done"] for task in linked):
                completed_ms = max(int(task["updatedAtMs"] or 0) for task in linked)
                if completed_ms > 0 and _period_matches(
                    _timestamp_iso(completed_ms), year, month
                ):
                    project_completed += 1
        habit_by_id = {habit["id"]: habit for habit in habits}
        with self._connect() as conn:
            logs = conn.execute(
                "SELECT habit_id,log_date FROM succes_habit_logs WHERE done=1"
            ).fetchall()
        today = date.today().isoformat()
        habit_completed = 0
        for row in logs:
            habit = habit_by_id.get(row["habit_id"])
            log_date = row["log_date"]
            if (
                not habit
                or log_date > today
                or not _period_matches(log_date, year, month)
            ):
                continue
            if log_date < habit["startDate"] or (
                habit["endDate"] and log_date > habit["endDate"]
            ):
                continue
            habit_completed += 1
        activity = [0] * 12
        for task in tasks:
            for iso in {task["createdAt"], task["date"]}:
                if iso and iso.startswith(f"{year:04d}-"):
                    try:
                        activity[int(iso[5:7]) - 1] += 1
                    except (ValueError, IndexError):
                        continue
        return {
            "year": year,
            "month": month,
            "activityByMonth": activity,
            "summary": {
                "tasksCreated": task_created,
                "tasksCompleted": task_completed,
                "habitsCompleted": habit_completed,
                "projectsCreated": project_created,
                "projectsCompleted": project_completed,
            },
            "catalog": {
                "tasksCompletedAllTime": sum(bool(task["done"]) for task in tasks),
                "projects": len(projects),
                "habits": len(habits),
                "longestHabitStreak": self._longest_habit_streak(habits, year, month),
            },
        }

    def export_state(self) -> dict[str, Any]:
        with self._connect() as conn:
            log_rows = conn.execute(
                "SELECT habit_id,log_date,done,updated_at_ms FROM succes_habit_logs"
            ).fetchall()
        return {
            "format": "diapason-succes-v3",
            "exportedAtMs": now_ms(),
            "state": {
                "todos": self.list_tasks(include_done=True),
                "todoTemplates": self.list_templates(),
                "projects": self.list_projects(),
                "habits": self.list_habits(on_date=date.today().isoformat()),
                "habitLogs": {
                    f"{row['habit_id']}_{row['log_date']}": bool(row["done"])
                    for row in log_rows
                },
                "habitLogsAt": {
                    f"{row['habit_id']}_{row['log_date']}": row["updated_at_ms"]
                    for row in log_rows
                },
                "quotes": self.list_quotes(),
                "notes": self.list_notes(),
            },
        }

    # Legacy materialization -----------------------------------------

    def materialize_continuity_archives(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT snapshot_json FROM succes_imports ORDER BY imported_at_ms"
            ).fetchall()
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            self._materialize_continuity_snapshot(snapshot)

    def import_legacy_snapshot(
        self, snapshot: Mapping[str, Any], *, source: str = "Life OS PHP/Flutter"
    ) -> dict[str, Any]:
        summary = super().import_legacy_snapshot(snapshot, source=source)
        return {**summary, **self._materialize_continuity_snapshot(snapshot)}

    def _materialize_continuity_snapshot(
        self, snapshot: Mapping[str, Any]
    ) -> dict[str, int]:
        state = (
            snapshot.get("state")
            if isinstance(snapshot.get("state"), Mapping)
            else snapshot
        )
        if not isinstance(state, Mapping):
            return {"templatesImported": 0, "quotesImported": 0}
        summary = {"templatesImported": 0, "quotesImported": 0}
        for raw in (
            state.get("todoTemplates", [])
            if isinstance(state.get("todoTemplates"), list)
            else []
        ):
            if not isinstance(raw, Mapping):
                continue
            try:
                self.get_template(str(raw.get("id") or ""))
            except SuccesNotFound:
                try:
                    self.create_template(raw)
                except SuccesError:
                    continue
                summary["templatesImported"] += 1
        for raw in (
            state.get("quotes", []) if isinstance(state.get("quotes"), list) else []
        ):
            if not isinstance(raw, Mapping):
                continue
            quote_id = str(raw.get("id") or "")
            with self._connect() as conn:
                exists = self._load_quote(conn, quote_id) if quote_id else None
            if exists:
                continue
            try:
                self.create_quote(raw)
            except SuccesError:
                continue
            summary["quotesImported"] += 1
        return summary


__all__ = [
    "QUOTE_CATEGORIES",
    "TEMPLATE_FREQUENCIES",
    "TEMPLATE_KINDS",
    "SuccesContinuityStore",
]
