"""Closed, typed Succès task tools available to DIA."""

from __future__ import annotations

from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.succes.dates import normalize_time, resolve_date_expression
from diapason.succes.store import SuccesError, SuccesStore
from diapason.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("succes_tasks")
class SuccesTasksTool(BaseTool):
    """Routine, reversible task operations. Deletion is intentionally absent."""

    tool_id = "succes_tasks"
    is_local = True

    def __init__(self, store: SuccesStore | None = None) -> None:
        self._store = store or SuccesStore()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="succes_tasks",
            description=(
                "Manage the user's private Succès tasks on this Mac. Supports listing, "
                "creating, completing/reopening, rescheduling, and adding or toggling "
                "subtasks. Never claims remote sync. Deletion and bulk changes "
                "are not allowed."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "create",
                            "complete",
                            "reopen",
                            "reschedule",
                            "add_subtask",
                            "toggle_subtask",
                        ],
                    },
                    "task_id": {"type": "string"},
                    "title": {"type": "string", "maxLength": 200},
                    "date": {
                        "type": "string",
                        "description": "Exact or spoken date, e.g. 2026-08-14, demain.",
                    },
                    "time": {"type": "string", "description": "Optional HH:mm."},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                    },
                    "notes": {"type": "string", "maxLength": 2000},
                    "subtask_id": {"type": "string"},
                    "subtask_title": {"type": "string", "maxLength": 200},
                    "parent_id": {"type": "string"},
                    "done": {"type": "boolean"},
                },
                "required": ["action"],
            },
            category="succes",
            metadata={"risk": "routine_write", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        action = str(params.get("action") or "")
        try:
            if action == "list":
                scheduled = self._resolve_optional_date(params.get("date"))
                tasks = self._store.list_tasks(
                    scheduled_date=scheduled,
                    include_done=bool(params.get("done", True)),
                )
                return self._ok(
                    f"{len(tasks)} tâche(s) trouvée(s).",
                    {"tasks": tasks, "persistence": "local"},
                )
            if action == "create":
                title = str(params.get("title") or "").strip()
                if not title:
                    return self._fail("Le titre de la tâche est obligatoire.")
                scheduled = self._resolve_optional_date(params.get("date"))
                task = self._store.create_task(
                    {
                        "title": title,
                        "date": scheduled or "",
                        "time": normalize_time(str(params.get("time") or "")),
                        "priority": params.get("priority") or "medium",
                        "notes": params.get("notes") or "",
                    }
                )
                return self._ok(
                    f"Tâche créée : {task['title']}",
                    {"task": task, "persistence": "local"},
                )
            task_id = str(params.get("task_id") or "").strip()
            if not task_id:
                return self._fail("L'identifiant exact de la tâche est obligatoire.")
            if action in {"complete", "reopen"}:
                task = self._store.set_task_done(task_id, action == "complete")
                verb = "terminée" if task["done"] else "rouverte"
                return self._ok(
                    f"Tâche {verb} : {task['title']}",
                    {"task": task, "persistence": "local"},
                )
            if action == "reschedule":
                scheduled = self._resolve_required_date(params.get("date"))
                task = self._store.reschedule_task(task_id, scheduled)
                warning = (
                    " Cette tâche a été reportée au moins quatre fois; "
                    "proposez de la découper."
                    if task["postponedCount"] >= 4
                    else ""
                )
                return self._ok(
                    f"Tâche reportée au {scheduled}.{warning}",
                    {"task": task, "persistence": "local"},
                )
            if action == "add_subtask":
                title = str(params.get("subtask_title") or "").strip()
                if not title:
                    return self._fail("Le titre de la sous-tâche est obligatoire.")
                task = self._store.add_subtask(
                    task_id, title, parent_id=str(params.get("parent_id") or "") or None
                )
                return self._ok(
                    f"Sous-tâche ajoutée à {task['title']}.",
                    {"task": task, "persistence": "local"},
                )
            if action == "toggle_subtask":
                subtask_id = str(params.get("subtask_id") or "").strip()
                if not subtask_id:
                    return self._fail(
                        "L'identifiant exact de la sous-tâche est obligatoire."
                    )
                task = self._store.set_subtask_done(
                    task_id, subtask_id, bool(params.get("done", True))
                )
                return self._ok(
                    f"Sous-tâche mise à jour dans {task['title']}.",
                    {"task": task, "persistence": "local"},
                )
            return self._fail(f"Action Succès inconnue : {action}")
        except (SuccesError, ValueError) as exc:
            return self._fail(str(exc))

    @staticmethod
    def _resolve_required_date(value: Any) -> str:
        resolution = resolve_date_expression(str(value or ""))
        if resolution.status == "ambiguous":
            raise SuccesError(
                "Cette date est ambiguë. Demandez à l'utilisateur de choisir entre "
                + " et ".join(resolution.options)
                + "."
            )
        if resolution.status != "exact" or not resolution.value:
            raise SuccesError(
                "Je n'ai pas reconnu cette date. Demandez une date précise."
            )
        return resolution.value

    @classmethod
    def _resolve_optional_date(cls, value: Any) -> str | None:
        if not str(value or "").strip():
            return None
        return cls._resolve_required_date(value)

    def _ok(self, content: str, metadata: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=content,
            metadata=metadata,
        )

    def _fail(self, content: str) -> ToolResult:
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=content,
            metadata={"persistence": "unchanged"},
        )


@ToolRegistry.register("succes_delete_task")
class SuccesDeleteTaskTool(BaseTool):
    """Single-task deletion, always routed through Diapason approval."""

    tool_id = "succes_delete_task"
    is_local = True

    def __init__(self, store: SuccesStore | None = None) -> None:
        self._store = store or SuccesStore()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="succes_delete_task",
            description=(
                "Delete exactly one private Succès task by its exact ID. This is a "
                "sensitive action and must wait for the user's approval. Never infer "
                "an ID and never use it for bulk deletion."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Exact task ID returned by succes_tasks list.",
                    }
                },
                "required": ["task_id"],
            },
            category="succes",
            requires_confirmation=True,
            metadata={"risk": "impactful", "reversible": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        task_id = str(params.get("task_id") or "").strip()
        if not task_id:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="L'identifiant exact de la tâche est obligatoire.",
                metadata={"persistence": "unchanged"},
            )
        try:
            task = self._store.get_task(task_id)
            self._store.delete_task(task_id)
        except SuccesError as exc:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=str(exc),
                metadata={"persistence": "unchanged"},
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Tâche supprimée : {task['title']}",
            metadata={"deletedId": task_id, "persistence": "local"},
        )


__all__ = ["SuccesDeleteTaskTool", "SuccesTasksTool"]
