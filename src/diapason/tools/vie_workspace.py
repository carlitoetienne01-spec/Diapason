"""DIA tools for private Diapason projects, habits and notes."""

from __future__ import annotations

from datetime import date
from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec
from diapason.tools._vie_magasin import MagasinParesseux
from diapason.vie.dates import resolve_date_expression
from diapason.vie.store import VieError
from diapason.vie.workspace import NOTE_CONTENT_MAX, VieWorkspaceStore


def _result(
    name: str, success: bool, content: str, metadata: dict[str, Any]
) -> ToolResult:
    return ToolResult(
        tool_name=name,
        success=success,
        content=content,
        metadata=metadata,
    )


def _resolve_date(value: Any, *, optional: bool = True) -> str:
    raw = str(value or "").strip()
    if not raw and optional:
        return ""
    resolution = resolve_date_expression(raw)
    if resolution.status == "ambiguous":
        raise VieError(
            "Cette date est ambiguë. Demandez de choisir entre "
            + " et ".join(resolution.options)
            + "."
        )
    if resolution.status != "exact" or not resolution.value:
        raise VieError("Je n'ai pas reconnu cette date. Demandez une date précise.")
    return resolution.value


@ToolRegistry.register("vie_workspace")
class VieWorkspaceTool(MagasinParesseux, BaseTool):
    """Routine workspace actions. Destructive operations are intentionally absent."""

    tool_id = "vie_workspace"
    is_local = True

    def __init__(self, store: VieWorkspaceStore | None = None) -> None:
        self._magasin = store
        self._fabrique = VieWorkspaceStore

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vie_workspace",
            description=(
                "Manage private local Diapason projects, habits and notes. Supports "
                "overview, list/create/update, and habit check-ins. Deletion and bulk "
                "changes are deliberately unavailable. Use exact IDs returned by lists."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "overview",
                            "list_projects",
                            "create_project",
                            "update_project",
                            "list_habits",
                            "create_habit",
                            "update_habit",
                            "toggle_habit",
                            "list_notes",
                            "create_note",
                            "update_note",
                        ],
                    },
                    "item_id": {"type": "string"},
                    "name": {"type": "string", "maxLength": 200},
                    "title": {"type": "string", "maxLength": 200},
                    "description": {"type": "string", "maxLength": 4000},
                    "content": {"type": "string", "maxLength": NOTE_CONTENT_MAX},
                    "date": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "frequency": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly"],
                    },
                    "weekly_days": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    },
                    "done": {"type": "boolean"},
                    "search": {"type": "string", "maxLength": 200},
                },
                "required": ["action"],
            },
            category="vie",
            metadata={"risk": "routine_write", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        action = str(params.get("action") or "")
        try:
            payload = self._execute(action, params)
        except (VieError, ValueError) as exc:
            return _result(
                self.spec.name,
                False,
                str(exc),
                {"persistence": "unchanged"},
            )
        return _result(
            self.spec.name,
            True,
            str(payload.pop("message")),
            {**payload, "persistence": "local"},
        )

    def _execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "overview":
            target = _resolve_date(params.get("date")) or date.today().isoformat()
            return {
                "message": f"Vue du {target} chargée.",
                "overview": self._store.dashboard(on_date=target),
            }
        if action == "list_projects":
            items = self._store.list_projects(search=str(params.get("search") or ""))
            return {"message": f"{len(items)} projet(s) trouvé(s).", "projects": items}
        if action == "create_project":
            project = self._store.create_project(
                {
                    "name": params.get("name"),
                    "description": params.get("description"),
                    "startDate": _resolve_date(params.get("start_date")),
                    "endDate": _resolve_date(params.get("end_date")),
                }
            )
            return {"message": f"Projet créé : {project['name']}", "project": project}
        if action == "update_project":
            item_id = self._required_id(params)
            patch = {
                key: value
                for key, value in {
                    "name": params.get("name"),
                    "description": params.get("description"),
                    "startDate": _resolve_date(params.get("start_date")),
                    "endDate": _resolve_date(params.get("end_date")),
                }.items()
                if value not in (None, "")
            }
            project = self._store.update_project(item_id, patch)
            return {
                "message": f"Projet mis à jour : {project['name']}",
                "project": project,
            }
        if action == "list_habits":
            target = _resolve_date(params.get("date")) or date.today().isoformat()
            items = self._store.list_habits(on_date=target)
            return {"message": f"{len(items)} habitude(s) trouvée(s).", "habits": items}
        if action == "create_habit":
            habit = self._store.create_habit(
                {
                    "name": params.get("name"),
                    "frequency": params.get("frequency") or "daily",
                    "weeklyDays": params.get("weekly_days") or [],
                    "startDate": _resolve_date(params.get("start_date")),
                    "endDate": _resolve_date(params.get("end_date")),
                }
            )
            return {"message": f"Habitude créée : {habit['name']}", "habit": habit}
        if action == "update_habit":
            item_id = self._required_id(params)
            patch: dict[str, Any] = {}
            if params.get("name") is not None:
                patch["name"] = params["name"]
            if params.get("frequency") is not None:
                patch["frequency"] = params["frequency"]
            if params.get("weekly_days") is not None:
                patch["weeklyDays"] = params["weekly_days"]
            habit = self._store.update_habit(item_id, patch)
            return {
                "message": f"Habitude mise à jour : {habit['name']}",
                "habit": habit,
            }
        if action == "toggle_habit":
            item_id = self._required_id(params)
            target = _resolve_date(params.get("date")) or date.today().isoformat()
            habit = self._store.set_habit_done(
                item_id, target, bool(params.get("done", True))
            )
            state = "terminée" if habit["done"] else "rouverte"
            return {"message": f"Habitude {state} : {habit['name']}", "habit": habit}
        if action == "list_notes":
            items = self._store.list_notes(search=str(params.get("search") or ""))
            return {"message": f"{len(items)} note(s) trouvée(s).", "notes": items}
        if action == "create_note":
            note = self._store.create_note(
                {"title": params.get("title"), "content": params.get("content") or ""}
            )
            return {"message": f"Note créée : {note['title']}", "note": note}
        if action == "update_note":
            item_id = self._required_id(params)
            patch = {
                key: value
                for key, value in {
                    "title": params.get("title"),
                    "content": params.get("content"),
                }.items()
                if value is not None
            }
            note = self._store.update_note(item_id, patch)
            return {"message": f"Note mise à jour : {note['title']}", "note": note}
        raise VieError(f"Action inconnue : {action}")

    @staticmethod
    def _required_id(params: dict[str, Any]) -> str:
        item_id = str(params.get("item_id") or "").strip()
        if not item_id:
            raise VieError("L'identifiant exact de l'élément est obligatoire.")
        return item_id


@ToolRegistry.register("vie_delete_item")
class VieDeleteItemTool(MagasinParesseux, BaseTool):
    """Delete one exact phase-two entity after native user approval."""

    tool_id = "vie_delete_item"
    is_local = True

    def __init__(self, store: VieWorkspaceStore | None = None) -> None:
        self._magasin = store
        self._fabrique = VieWorkspaceStore

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vie_delete_item",
            description=(
                "Delete exactly one private Diapason project, habit or note by "
                "exact ID. "
                "This sensitive action must wait for native user approval."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "entity": {"type": "string", "enum": ["project", "habit", "note"]},
                    "item_id": {"type": "string"},
                },
                "required": ["entity", "item_id"],
            },
            category="vie",
            requires_confirmation=True,
            metadata={"risk": "impactful", "reversible": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        entity = str(params.get("entity") or "")
        item_id = str(params.get("item_id") or "").strip()
        if not item_id:
            return _result(
                self.spec.name,
                False,
                "L'identifiant exact de l'élément est obligatoire.",
                {"persistence": "unchanged"},
            )
        try:
            if entity == "project":
                label = self._store.get_project(item_id)["name"]
                self._store.delete_project(item_id)
            elif entity == "habit":
                label = self._store.get_habit(item_id)["name"]
                self._store.delete_habit(item_id)
            elif entity == "note":
                label = self._store.get_note(item_id)["title"]
                self._store.delete_note(item_id)
            else:
                raise VieError("Le type doit être project, habit ou note.")
        except VieError as exc:
            return _result(
                self.spec.name,
                False,
                str(exc),
                {"persistence": "unchanged"},
            )
        return _result(
            self.spec.name,
            True,
            f"Élément supprimé : {label}",
            {"deletedId": item_id, "entity": entity, "persistence": "local"},
        )


__all__ = ["VieDeleteItemTool", "VieWorkspaceTool"]
