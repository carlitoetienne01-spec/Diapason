"""Authenticated REST API for the native Succès module."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from diapason.succes.dates import normalize_time, resolve_date_expression
from diapason.succes.store import SuccesError, SuccesNotFound, SuccesStore
from diapason.succes.workspace import HABIT_FREQUENCIES, SuccesWorkspaceStore

router = APIRouter(prefix="/v1/succes", tags=["succes"])
_store: SuccesStore | None = None


def get_store() -> SuccesStore:
    global _store
    if _store is None:
        _store = SuccesWorkspaceStore()
    return _store


def set_store_for_tests(store: SuccesStore | None) -> None:
    global _store
    _store = store


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    date: str = ""
    time: str = ""
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    projectId: str = ""
    category: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=2000)
    emoji: str = Field(default="", max_length=16)
    opId: str | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    date: str | None = None
    time: str | None = None
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    projectId: str | None = None
    category: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    emoji: str | None = Field(default=None, max_length=16)
    order: int | None = None
    opId: str | None = None


class DoneBody(BaseModel):
    done: bool
    opId: str | None = None


class RescheduleBody(BaseModel):
    date: str = Field(min_length=1, max_length=80)
    opId: str | None = None


class SubtaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    parentId: str | None = None
    opId: str | None = None


class DeleteBody(BaseModel):
    confirmed: bool = False
    opId: str | None = None


class LegacyImportBody(BaseModel):
    snapshot: dict[str, Any]
    source: str = Field(default="Life OS PHP/Flutter", max_length=120)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    color: str = Field(default="#6366f1", max_length=7)
    icon: str = Field(default="", max_length=16)
    startDate: str = ""
    endDate: str = ""
    opId: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    color: str | None = Field(default=None, max_length=7)
    icon: str | None = Field(default=None, max_length=16)
    startDate: str | None = None
    endDate: str | None = None
    opId: str | None = None


class HabitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    icon: str = Field(default="", max_length=16)
    color: str = Field(default="#6366f1", max_length=7)
    frequency: Literal["daily", "weekly", "monthly"] = "daily"
    startDate: str = ""
    endDate: str = ""
    weeklyDays: list[int] = Field(default_factory=list)
    monthWeekSlots: list[int | Literal["last"]] = Field(default_factory=list)
    monthWeekDay: int = Field(default=1, ge=0, le=6)
    reminderTime: str = ""
    opId: str | None = None


class HabitPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=7)
    frequency: Literal["daily", "weekly", "monthly"] | None = None
    startDate: str | None = None
    endDate: str | None = None
    weeklyDays: list[int] | None = None
    monthWeekSlots: list[int | Literal["last"]] | None = None
    monthWeekDay: int | None = Field(default=None, ge=0, le=6)
    reminderTime: str | None = None
    opId: str | None = None


class HabitLogBody(BaseModel):
    date: str
    done: bool
    opId: str | None = None


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=100_000)
    opId: str | None = None


class NotePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=100_000)
    opId: str | None = None


def _domain_error(exc: SuccesError) -> HTTPException:
    return HTTPException(
        status_code=404 if isinstance(exc, SuccesNotFound) else 409, detail=str(exc)
    )


def _resolved_date(value: str, *, allow_empty: bool = True) -> str:
    if not value.strip() and allow_empty:
        return ""
    resolution = resolve_date_expression(value)
    if resolution.status == "ambiguous":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ambiguous_date",
                "message": (
                    "Cette date peut désigner deux jours. Choisissez une date précise."
                ),
                "options": list(resolution.options),
            },
        )
    if resolution.status != "exact" or not resolution.value:
        raise HTTPException(status_code=422, detail="Je n'ai pas reconnu cette date.")
    return resolution.value


@router.get("/tasks")
async def list_tasks(
    date: str | None = None,
    include_done: bool = True,
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    try:
        tasks = get_store().list_tasks(
            scheduled_date=_resolved_date(date) if date is not None else None,
            include_done=include_done,
            search=search,
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"tasks": tasks, "count": len(tasks)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    try:
        return get_store().get_task(task_id)
    except SuccesError as exc:
        raise _domain_error(exc) from exc


@router.post("/tasks", status_code=201)
async def create_task(body: TaskCreate) -> dict[str, Any]:
    data = body.model_dump(exclude={"opId"})
    data["date"] = _resolved_date(body.date)
    try:
        data["time"] = normalize_time(body.time)
        task = get_store().create_task(data, op_id=body.opId)
    except (SuccesError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"task": task, "persistence": "local"}


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskPatch) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True, exclude={"opId"})
    if "date" in patch:
        patch["date"] = _resolved_date(str(patch["date"]))
    if "time" in patch:
        try:
            patch["time"] = normalize_time(str(patch["time"]))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        task = get_store().update_task(task_id, patch, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"task": task, "persistence": "local"}


@router.post("/tasks/{task_id}/done")
async def set_task_done(task_id: str, body: DoneBody) -> dict[str, Any]:
    try:
        task = get_store().set_task_done(task_id, body.done, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"task": task, "persistence": "local"}


@router.post("/tasks/{task_id}/reschedule")
async def reschedule_task(task_id: str, body: RescheduleBody) -> dict[str, Any]:
    scheduled_date = _resolved_date(body.date, allow_empty=False)
    try:
        task = get_store().reschedule_task(task_id, scheduled_date, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    warning = (
        "Cette tâche a déjà été reportée plusieurs fois. Voulez-vous la découper ?"
        if task["postponedCount"] >= 4
        else None
    )
    return {"task": task, "warning": warning, "persistence": "local"}


@router.post("/tasks/{task_id}/subtasks", status_code=201)
async def create_subtask(task_id: str, body: SubtaskCreate) -> dict[str, Any]:
    try:
        task = get_store().add_subtask(
            task_id, body.title, parent_id=body.parentId, op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"task": task, "persistence": "local"}


@router.post("/tasks/{task_id}/subtasks/{subtask_id}/done")
async def set_subtask_done(
    task_id: str, subtask_id: str, body: DoneBody
) -> dict[str, Any]:
    try:
        task = get_store().set_subtask_done(
            task_id, subtask_id, body.done, op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"task": task, "persistence": "local"}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, body: DeleteBody) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "confirmation_required",
                "message": "Confirmez la suppression de cette tâche.",
            },
        )
    try:
        get_store().delete_task(task_id, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"deleted": True, "id": task_id, "persistence": "local"}


@router.get("/planner")
async def planner(date: str) -> dict[str, Any]:
    scheduled_date = _resolved_date(date, allow_empty=False)
    tasks = get_store().list_tasks(scheduled_date=scheduled_date, include_done=True)
    return {
        "date": scheduled_date,
        "tasks": tasks,
        "summary": {
            "total": len(tasks),
            "completed": sum(1 for task in tasks if task["done"]),
            "open": sum(1 for task in tasks if not task["done"]),
        },
    }


def _workspace_store() -> SuccesWorkspaceStore:
    store = get_store()
    if not isinstance(store, SuccesWorkspaceStore):
        # Test stores created before phase two remain valid for task-only routes.
        raise HTTPException(
            status_code=503, detail="Le module Succès complet n'est pas initialisé."
        )
    return store


@router.get("/projects")
async def list_projects(
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    projects = _workspace_store().list_projects(search=search)
    return {"projects": projects, "count": len(projects)}


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate) -> dict[str, Any]:
    try:
        project = _workspace_store().create_project(
            body.model_dump(exclude={"opId"}), op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"project": project, "persistence": "local"}


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectPatch) -> dict[str, Any]:
    try:
        project = _workspace_store().update_project(
            project_id,
            body.model_dump(exclude_none=True, exclude={"opId"}),
            op_id=body.opId,
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"project": project, "persistence": "local"}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, body: DeleteBody) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "confirmation_required",
                "message": "Confirmez la suppression de ce projet.",
            },
        )
    try:
        _workspace_store().delete_project(project_id, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"deleted": True, "id": project_id, "persistence": "local"}


@router.get("/habits")
async def list_habits(date: str | None = None) -> dict[str, Any]:
    try:
        habits = _workspace_store().list_habits(
            on_date=_resolved_date(date) if date is not None else None
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {
        "habits": habits,
        "count": len(habits),
        "frequencies": sorted(HABIT_FREQUENCIES),
    }


@router.post("/habits", status_code=201)
async def create_habit(body: HabitCreate) -> dict[str, Any]:
    data = body.model_dump(exclude={"opId"})
    if data["startDate"]:
        data["startDate"] = _resolved_date(data["startDate"])
    if data["endDate"]:
        data["endDate"] = _resolved_date(data["endDate"])
    try:
        habit = _workspace_store().create_habit(data, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"habit": habit, "persistence": "local"}


@router.patch("/habits/{habit_id}")
async def update_habit(habit_id: str, body: HabitPatch) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True, exclude={"opId"})
    for key in ("startDate", "endDate"):
        if key in data and data[key]:
            data[key] = _resolved_date(str(data[key]))
    try:
        habit = _workspace_store().update_habit(habit_id, data, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"habit": habit, "persistence": "local"}


@router.post("/habits/{habit_id}/log")
async def set_habit_done(habit_id: str, body: HabitLogBody) -> dict[str, Any]:
    log_date = _resolved_date(body.date, allow_empty=False)
    try:
        habit = _workspace_store().set_habit_done(
            habit_id, log_date, body.done, op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"habit": habit, "persistence": "local"}


@router.delete("/habits/{habit_id}")
async def delete_habit(habit_id: str, body: DeleteBody) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "confirmation_required",
                "message": "Confirmez la suppression de cette habitude.",
            },
        )
    try:
        _workspace_store().delete_habit(habit_id, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"deleted": True, "id": habit_id, "persistence": "local"}


@router.get("/notes")
async def list_notes(
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    notes = _workspace_store().list_notes(search=search)
    return {"notes": notes, "count": len(notes)}


@router.post("/notes", status_code=201)
async def create_note(body: NoteCreate) -> dict[str, Any]:
    try:
        note = _workspace_store().create_note(
            body.model_dump(exclude={"opId"}), op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"note": note, "persistence": "local"}


@router.patch("/notes/{note_id}")
async def update_note(note_id: str, body: NotePatch) -> dict[str, Any]:
    try:
        note = _workspace_store().update_note(
            note_id,
            body.model_dump(exclude_none=True, exclude={"opId"}),
            op_id=body.opId,
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"note": note, "persistence": "local"}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, body: DeleteBody) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "confirmation_required",
                "message": "Confirmez la suppression de cette note.",
            },
        )
    try:
        _workspace_store().delete_note(note_id, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"deleted": True, "id": note_id, "persistence": "local"}


@router.get("/dashboard")
async def dashboard(date: str | None = None) -> dict[str, Any]:
    return _workspace_store().dashboard(
        on_date=_resolved_date(date) if date is not None else None
    )


@router.get("/sync/status")
async def sync_status() -> dict[str, Any]:
    return get_store().sync_status()


@router.get("/sync/operations")
async def sync_operations(after: int = 0, limit: int = 500) -> dict[str, Any]:
    return get_store().list_operations(after=after, limit=limit)


@router.post("/import/legacy")
async def import_legacy(body: LegacyImportBody) -> dict[str, Any]:
    try:
        summary = get_store().import_legacy_snapshot(body.snapshot, source=body.source)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {
        "summary": summary,
        "message": (
            "La sauvegarde a été archivée et les données de la phase 1 ont été "
            "importées sans écraser les versions plus récentes."
        ),
    }


__all__ = ["get_store", "router", "set_store_for_tests"]
