"""Authenticated REST API for the native Succès module."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from diapason.succes.dates import normalize_time, resolve_date_expression
from diapason.succes.store import SuccesError, SuccesNotFound, SuccesStore

router = APIRouter(prefix="/v1/succes", tags=["succes"])
_store: SuccesStore | None = None


def get_store() -> SuccesStore:
    global _store
    if _store is None:
        _store = SuccesStore()
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
