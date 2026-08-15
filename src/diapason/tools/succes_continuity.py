"""DIA tools for Succès recurrences, quotes and retrospective insights."""

from __future__ import annotations

from datetime import date
from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.succes.continuity import SuccesContinuityStore
from diapason.succes.dates import resolve_date_expression
from diapason.succes.store import SuccesError
from diapason.tools._stubs import BaseTool, ToolSpec


def _result(
    name: str, success: bool, content: str, metadata: dict[str, Any]
) -> ToolResult:
    return ToolResult(
        tool_name=name, success=success, content=content, metadata=metadata
    )


def _date(value: Any) -> str:
    resolution = resolve_date_expression(str(value or ""))
    if resolution.status != "exact" or not resolution.value:
        raise SuccesError("Une date précise est obligatoire.")
    return resolution.value


@ToolRegistry.register("succes_continuity")
class SuccesContinuityTool(BaseTool):
    """Routine recurrence and review actions; deletion is deliberately separate."""

    tool_id = "succes_continuity"
    is_local = True

    def __init__(self, store: SuccesContinuityStore | None = None) -> None:
        self._store = store or SuccesContinuityStore()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="succes_continuity",
            description=(
                "Manage private Succès recurring task/habit templates and motivational "
                "quotes, materialize a date range, or read the annual/monthly review. "
                "Deletion is unavailable in this routine tool."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list_templates",
                            "create_template",
                            "update_template",
                            "materialize",
                            "list_quotes",
                            "create_quote",
                            "year_review",
                        ],
                    },
                    "item_id": {"type": "string"},
                    "title": {"type": "string", "maxLength": 200},
                    "emoji": {"type": "string", "maxLength": 16},
                    "frequency": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly"],
                    },
                    "template_kind": {"type": "string", "enum": ["task", "habit"]},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                    },
                    "weekly_days": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    },
                    "month_week_slots": {
                        "type": "array",
                        "items": {
                            "anyOf": [
                                {"type": "integer", "minimum": 1, "maximum": 4},
                                {"type": "string", "enum": ["last"]},
                            ]
                        },
                    },
                    "month_week_dow": {"type": "integer", "minimum": 0, "maximum": 6},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "active": {"type": "boolean"},
                    "text": {"type": "string", "maxLength": 1000},
                    "author": {"type": "string", "maxLength": 200},
                    "category": {"type": "string"},
                    "year": {"type": "integer", "minimum": 1970, "maximum": 2100},
                    "month": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "required": ["action"],
            },
            category="succes",
            metadata={"risk": "routine_write", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            payload = self._execute(str(params.get("action") or ""), params)
        except (SuccesError, ValueError) as exc:
            return _result(
                self.spec.name, False, str(exc), {"persistence": "unchanged"}
            )
        return _result(
            self.spec.name,
            True,
            str(payload.pop("message")),
            {**payload, "persistence": "local"},
        )

    def _execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "list_templates":
            items = self._store.list_templates()
            return {
                "message": f"{len(items)} récurrence(s) trouvée(s).",
                "templates": items,
            }
        if action == "create_template":
            item = self._store.create_template(
                self._template_payload(params, require_dates=True)
            )
            return {"message": f"Récurrence créée : {item['title']}", "template": item}
        if action == "update_template":
            item = self._store.update_template(
                self._required_id(params),
                self._template_payload(params, require_dates=False),
            )
            return {
                "message": f"Récurrence mise à jour : {item['title']}",
                "template": item,
            }
        if action == "materialize":
            result = self._store.materialize_templates(
                _date(params.get("start_date")), _date(params.get("end_date"))
            )
            return {"message": f"{result['count']} occurrence(s) créée(s).", **result}
        if action == "list_quotes":
            items = self._store.list_quotes(category=str(params.get("category") or ""))
            return {"message": f"{len(items)} citation(s) trouvée(s).", "quotes": items}
        if action == "create_quote":
            item = self._store.create_quote(
                {
                    "text": params.get("text"),
                    "author": params.get("author"),
                    "category": params.get("category"),
                }
            )
            return {"message": "Citation ajoutée aux mots du jour.", "quote": item}
        if action == "year_review":
            year = int(params.get("year") or date.today().year)
            month = int(params["month"]) if params.get("month") is not None else None
            return {
                "message": f"Bilan {year} calculé.",
                "review": self._store.year_review(year, month=month),
            }
        raise SuccesError(f"Action Succès inconnue : {action}")

    @staticmethod
    def _template_payload(
        params: dict[str, Any], *, require_dates: bool
    ) -> dict[str, Any]:
        mapping = {
            "title": "title",
            "emoji": "emoji",
            "frequency": "frequency",
            "template_kind": "templateKind",
            "priority": "priority",
            "weekly_days": "weeklyDays",
            "month_week_slots": "monthWeekSlots",
            "month_week_dow": "monthWeekDow",
            "active": "active",
        }
        payload = {
            target: params[source]
            for source, target in mapping.items()
            if params.get(source) is not None
        }
        for source, target in (("start_date", "startDate"), ("end_date", "endDate")):
            if params.get(source) is not None:
                payload[target] = _date(params[source])
            elif require_dates:
                raise SuccesError("Les dates de début et de fin sont obligatoires.")
        return payload

    @staticmethod
    def _required_id(params: dict[str, Any]) -> str:
        item_id = str(params.get("item_id") or "").strip()
        if not item_id:
            raise SuccesError("L'identifiant exact de la récurrence est obligatoire.")
        return item_id


@ToolRegistry.register("succes_delete_continuity")
class SuccesDeleteContinuityTool(BaseTool):
    tool_id = "succes_delete_continuity"
    is_local = True

    def __init__(self, store: SuccesContinuityStore | None = None) -> None:
        self._store = store or SuccesContinuityStore()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="succes_delete_continuity",
            description=(
                "Delete one exact Succès recurrence or quote after native approval."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "entity": {"type": "string", "enum": ["template", "quote"]},
                    "item_id": {"type": "string"},
                },
                "required": ["entity", "item_id"],
            },
            category="succes",
            requires_confirmation=True,
            metadata={"risk": "impactful", "reversible": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        entity = str(params.get("entity") or "")
        item_id = str(params.get("item_id") or "").strip()
        try:
            if entity == "template":
                result = self._store.delete_template(item_id)
                content = (
                    f"Récurrence supprimée avec {result['tasksDeleted']} occurrence(s)."
                )
            elif entity == "quote":
                self._store.delete_quote(item_id)
                content = "Citation supprimée."
            else:
                raise SuccesError("Le type doit être template ou quote.")
        except SuccesError as exc:
            return _result(
                self.spec.name, False, str(exc), {"persistence": "unchanged"}
            )
        return _result(
            self.spec.name,
            True,
            content,
            {"entity": entity, "deletedId": item_id, "persistence": "local"},
        )


__all__ = ["SuccesContinuityTool", "SuccesDeleteContinuityTool"]
