"""Authenticated REST API for the native Succès module."""

from __future__ import annotations

from threading import Lock
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from diapason.succes.continuity import SuccesContinuityStore
from diapason.succes.dates import normalize_time, resolve_date_expression
from diapason.succes.notes_resume import resumer_note
from diapason.succes.store import (
    SuccesError,
    SuccesNoteConflict,
    SuccesNotFound,
    SuccesStore,
)
from diapason.succes.sync import MAX_SYNC_BATCH, SuccesSyncStore
from diapason.succes.workspace import (
    HABIT_FREQUENCIES,
    NOTE_CONTENT_MAX,
    NOTE_DOC_LANGS,
    NOTE_FONTS,
    NOTE_PAGE_BACKGROUNDS,
    NOTE_PAGE_FORMATS,
    NOTE_PAGE_MARGINS,
    NOTE_PAGE_ORIENTATIONS,
    NOTE_PAGE_SIZES,
    SuccesWorkspaceStore,
)

# 19/09/2026 : les routes SQLite et sync réseau étaient async sans await.
# Elles bloquaient le chat et la voix sur la boucle commune. Les handlers
# synchrones passent par le pool Starlette ; le contrat HTTP reste identique.
router = APIRouter(prefix="/v1/succes", tags=["succes"])
_store: SuccesStore | None = None
_store_lock = Lock()


def get_store() -> SuccesStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = SuccesSyncStore()
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
    parentTaskId: str = ""
    category: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=2000)
    # Le CARNET de la tâche, distinct de `notes` : la consigne se lit avant,
    # le carnet s'écrit pendant. Plus long, parce qu'il s'accumule.
    journal: str = Field(default="", max_length=20000)
    emoji: str = Field(default="", max_length=16)
    # L'étape (pipeline) et la cadence (cycle) ; validées contre le projet.
    stage: str = Field(default="", max_length=40)
    cadence: dict[str, Any] | None = None
    # La durée estimée en jours d'une tâche du réseau (18 sept. 2026) : un
    # ENTIER, jamais un flottant — le client Dart signe des enveloppes
    # canoniques où `1e-07` (Python) et `1e-7` (Dart) divergent. 0 = pas
    # d'estimation. `strict` : « 1.5 » n'est pas arrondi en silence.
    estimateDays: int = Field(default=0, ge=0, le=3650, strict=True)
    # Le magasin lit « done » depuis toujours ; la route le laissait tomber en
    # silence, si bien qu'un client important une tâche déjà terminée la
    # récupérait ouverte, sans le moindre message.
    done: bool = False
    opId: str | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    date: str | None = None
    time: str | None = None
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    projectId: str | None = None
    parentTaskId: str | None = None
    category: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    journal: str | None = Field(default=None, max_length=20000)
    emoji: str | None = Field(default=None, max_length=16)
    order: int | None = None
    stage: str | None = Field(default=None, max_length=40)
    cadence: dict[str, Any] | None = None
    estimateDays: int | None = Field(default=None, ge=0, le=3650, strict=True)
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


# `DeleteBody` vit dans `succes/corps.py` : `finances_routes.py` en a besoin
# AU NIVEAU DE SON MODULE, faute de quoi FastAPI ne peut pas résoudre
# l'annotation et `/openapi.json` rend 500. Le ré-exporter ici garde les
# importateurs existants intacts.
from diapason.succes.corps import DeleteBody  # noqa: E402


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
    structure: Literal["flat", "tree", "mindmap", "pipeline", "network", "cycle"] = (
        "flat"
    )
    structureConfig: dict[str, Any] = Field(default_factory=dict)
    kitId: str = Field(default="", max_length=80)
    opId: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    color: str | None = Field(default=None, max_length=7)
    icon: str | None = Field(default=None, max_length=16)
    startDate: str | None = None
    endDate: str | None = None
    structure: (
        Literal["flat", "tree", "mindmap", "pipeline", "network", "cycle"] | None
    ) = None
    structureConfig: dict[str, Any] | None = None
    opId: str | None = None


class EdgeCreate(BaseModel):
    fromTaskId: str = Field(min_length=1, max_length=80)
    toTaskId: str = Field(min_length=1, max_length=80)
    opId: str | None = None


class CycleResetBody(BaseModel):
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
    content: str = Field(default="", max_length=NOTE_CONTENT_MAX)
    pageFormat: str = "a4"
    pageSize: str = "a4"
    pageOrientation: str = "portrait"
    pageMargins: str = "normales"
    pageBackground: str = "default"
    fontFamily: str = "Special Elite"
    docLang: str = "fr"
    color: str = "#6366f1"
    # La page où l'on s'est arrêté de lire. Zéro : aucun marqueur.
    readingMark: int = Field(default=0, ge=0, le=100_000)
    category: str = Field(default="", max_length=60)
    projectId: str = ""
    opId: str | None = None


class NotePatch(BaseModel):
    expectedContentHash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    appendContent: str | None = Field(default=None, max_length=NOTE_CONTENT_MAX)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=NOTE_CONTENT_MAX)
    pageFormat: str | None = None
    pageSize: str | None = None
    pageOrientation: str | None = None
    pageMargins: str | None = None
    pageBackground: str | None = None
    fontFamily: str | None = None
    docLang: str | None = None
    color: str | None = None
    # `exclude_none` laisse passer 0 : effacer le marqueur est une action, et
    # elle doit pouvoir se dire. Seul `null` veut dire « ne touche pas ».
    readingMark: int | None = Field(default=None, ge=0, le=100_000)
    # La chaîne vide se dit aussi : « sans catégorie », « sans projet ».
    category: str | None = Field(default=None, max_length=60)
    projectId: str | None = None
    opId: str | None = None


class TemplateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    emoji: str = Field(default="", max_length=16)
    frequency: Literal["daily", "weekly", "monthly"] = "weekly"
    daysOfWeek: list[int] = Field(default_factory=list)
    weeklyDays: list[int] = Field(default_factory=list)
    monthWeekSlots: list[int | Literal["last"]] = Field(default_factory=list)
    monthWeekDow: int = Field(default=1, ge=0, le=6)
    projectId: str = ""
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    templateKind: Literal["task", "habit"] = "task"
    startDate: str
    endDate: str
    active: bool = True
    opId: str | None = None


class TemplatePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    emoji: str | None = Field(default=None, max_length=16)
    frequency: Literal["daily", "weekly", "monthly"] | None = None
    daysOfWeek: list[int] | None = None
    weeklyDays: list[int] | None = None
    monthWeekSlots: list[int | Literal["last"]] | None = None
    monthWeekDow: int | None = Field(default=None, ge=0, le=6)
    projectId: str | None = None
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    templateKind: Literal["task", "habit"] | None = None
    startDate: str | None = None
    endDate: str | None = None
    active: bool | None = None
    opId: str | None = None


class MaterializeBody(BaseModel):
    startDate: str
    endDate: str


class QuoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    author: str = Field(default="", max_length=200)
    category: Literal[
        "philosophie", "bienetre", "developpement", "sagesse", "motivation", "autre"
    ] = "autre"
    opId: str | None = None


class PairingCreate(BaseModel):
    deviceName: str = Field(min_length=1, max_length=80)


class PairingRedeem(BaseModel):
    pairingToken: str = Field(min_length=32, max_length=160)


class SyncExchangeBody(BaseModel):
    peerToken: str = Field(min_length=32, max_length=200)
    cursor: int = Field(default=0, ge=0)
    operations: list[dict[str, Any]] = Field(
        default_factory=list, max_length=MAX_SYNC_BATCH
    )


class SyncRelayBody(BaseModel):
    url: str = Field(min_length=8, max_length=500)


class SyncJoinBody(BaseModel):
    pairingToken: str = Field(min_length=32, max_length=160)
    relayUrl: str | None = Field(default=None, max_length=500)
    deviceName: str = Field(default="", max_length=80)


def _sync_store() -> SuccesSyncStore:
    store = get_store()
    if not isinstance(store, SuccesSyncStore):
        raise HTTPException(
            status_code=503,
            detail="Le moteur de synchronisation Succès n'est pas disponible.",
        )
    return store


def _domain_error(exc: SuccesError) -> HTTPException:
    if isinstance(exc, SuccesNoteConflict):
        return HTTPException(409, detail={"code": "note_conflict", "message": str(exc)})
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
def list_tasks(
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
def get_task(task_id: str) -> dict[str, Any]:
    try:
        return get_store().get_task(task_id)
    except SuccesError as exc:
        raise _domain_error(exc) from exc


@router.post("/tasks", status_code=201)
def create_task(body: TaskCreate) -> dict[str, Any]:
    data = body.model_dump(exclude={"opId"})
    data["date"] = _resolved_date(body.date)
    try:
        data["time"] = normalize_time(body.time)
        task = get_store().create_task(data, op_id=body.opId)
    except (SuccesError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"task": task, "persistence": "local"}


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: TaskPatch) -> dict[str, Any]:
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
def set_task_done(task_id: str, body: DoneBody) -> dict[str, Any]:
    try:
        task = get_store().set_task_done(task_id, body.done, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"task": task, "persistence": "local"}


@router.post("/tasks/{task_id}/reschedule")
def reschedule_task(task_id: str, body: RescheduleBody) -> dict[str, Any]:
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


@router.post("/tasks/{task_id}/reschedule-series")
def reschedule_task_series(task_id: str, body: RescheduleBody) -> dict[str, Any]:
    scheduled_date = _resolved_date(body.date, allow_empty=False)
    try:
        result = get_store().reschedule_series(task_id, scheduled_date, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {**result, "persistence": "local"}


@router.post("/tasks/{task_id}/subtasks", status_code=201)
def create_subtask(task_id: str, body: SubtaskCreate) -> dict[str, Any]:
    try:
        task = get_store().add_subtask(
            task_id, body.title, parent_id=body.parentId, op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"task": task, "persistence": "local"}


@router.post("/tasks/{task_id}/subtasks/{subtask_id}/done")
def set_subtask_done(task_id: str, subtask_id: str, body: DoneBody) -> dict[str, Any]:
    try:
        task = get_store().set_subtask_done(
            task_id, subtask_id, body.done, op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"task": task, "persistence": "local"}


@router.delete("/tasks/{task_id}/subtasks/{subtask_id}")
def delete_subtask(task_id: str, subtask_id: str, body: DeleteBody) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "confirmation_required",
                "message": "Confirmez la suppression de cette sous-tâche.",
            },
        )
    try:
        task = get_store().delete_subtask(task_id, subtask_id, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"task": task, "persistence": "local"}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, body: DeleteBody) -> dict[str, Any]:
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
def planner(date: str) -> dict[str, Any]:
    scheduled_date = _resolved_date(date, allow_empty=False)
    store = get_store()
    quote = None
    if isinstance(store, SuccesContinuityStore):
        store.materialize_templates(scheduled_date, scheduled_date)
        quote = store.quote_for_date(scheduled_date)
    tasks = store.list_tasks(scheduled_date=scheduled_date, include_done=True)
    return {
        "date": scheduled_date,
        "tasks": tasks,
        "quote": quote,
        "summary": {
            "total": len(tasks),
            "completed": sum(1 for task in tasks if task["done"]),
            "open": sum(1 for task in tasks if not task["done"]),
        },
    }


@router.get("/planner/pastilles")
def planner_pastilles(start: str, end: str) -> dict[str, Any]:
    """Les points du petit calendrier, exacts et en lecture seule.

    Route synchrone (`def`) : elle ne fait que du SQLite — Starlette
    l'exécute dans un fil, la boucle d'événements reste libre.
    """
    store = get_store()
    if not isinstance(store, SuccesContinuityStore):
        raise HTTPException(
            status_code=503, detail="Le module Succès complet n'est pas initialisé."
        )
    return store.pastilles_planner(
        _resolved_date(start, allow_empty=False),
        _resolved_date(end, allow_empty=False),
    )


def _workspace_store() -> SuccesWorkspaceStore:
    store = get_store()
    if not isinstance(store, SuccesWorkspaceStore):
        # Test stores created before phase two remain valid for task-only routes.
        raise HTTPException(
            status_code=503, detail="Le module Succès complet n'est pas initialisé."
        )
    return store


def _continuity_store() -> SuccesContinuityStore:
    store = get_store()
    if not isinstance(store, SuccesContinuityStore):
        raise HTTPException(
            status_code=503,
            detail="Les récurrences et le bilan Succès ne sont pas initialisés.",
        )
    return store


class OrdreParIds(BaseModel):
    ids: list[str] = Field(max_length=5000)


@router.put("/projects/ordre")
def reorder_projects(body: OrdreParIds) -> dict[str, Any]:
    """Fixe l'ordre manuel des projets (leur rang dans `ids`)."""
    changed = _workspace_store().reorder_projects(body.ids)
    return {"reordered": len(changed)}


@router.get("/projects")
def list_projects(
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    projects = _workspace_store().list_projects(search=search)
    return {"projects": projects, "count": len(projects)}


@router.get("/project-kits")
def list_project_kits() -> dict[str, Any]:
    from diapason.succes.project_kits import list_project_kits as _list_kits

    kits = _list_kits()
    return {"kits": kits, "count": len(kits)}


@router.get("/project-structures")
def list_project_structures() -> dict[str, Any]:
    """Les cinq formes qu'un projet peut prendre, pour le sélecteur."""
    from diapason.succes.structures import STRUCTURE_CATALOG

    return {"structures": list(STRUCTURE_CATALOG)}


@router.get("/projects/{project_id}/edges")
def list_task_edges(project_id: str) -> dict[str, Any]:
    try:
        edges = _workspace_store().list_task_edges(project_id)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"edges": edges, "count": len(edges)}


@router.post("/projects/{project_id}/edges", status_code=201)
def create_task_edge(project_id: str, body: EdgeCreate) -> dict[str, Any]:
    try:
        edge = _workspace_store().create_task_edge(
            project_id, body.fromTaskId, body.toTaskId, op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"edge": edge, "persistence": "local"}


@router.delete("/projects/{project_id}/edges/{from_task_id}/{to_task_id}")
def delete_task_edge(
    project_id: str, from_task_id: str, to_task_id: str
) -> dict[str, Any]:
    try:
        _workspace_store().delete_task_edge(project_id, from_task_id, to_task_id)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"deleted": True}


@router.post("/projects/{project_id}/cycle/reset")
def reset_project_cycle(
    project_id: str, body: CycleResetBody | None = None
) -> dict[str, Any]:
    try:
        result = _workspace_store().reset_cycle(
            project_id, op_id=body.opId if body else None
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return result


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate) -> dict[str, Any]:
    try:
        project = _workspace_store().create_project(
            body.model_dump(exclude={"opId"}), op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"project": project, "persistence": "local"}


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: ProjectPatch) -> dict[str, Any]:
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
def delete_project(project_id: str, body: DeleteBody) -> dict[str, Any]:
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
def list_habits(date: str | None = None) -> dict[str, Any]:
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


@router.get("/habits/logs")
def list_habit_logs(
    from_date: str = Query(alias="from", min_length=1, max_length=80),
    to_date: str = Query(alias="to", min_length=1, max_length=80),
    habit_id: str | None = Query(default=None, alias="habitId", max_length=80),
) -> dict[str, Any]:
    try:
        start = _resolved_date(from_date, allow_empty=False)
        end = _resolved_date(to_date, allow_empty=False)
        logs = _workspace_store().list_habit_logs(
            from_date=start, to_date=end, habit_id=habit_id or None
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"from": start, "to": end, "logs": logs, "count": len(logs)}


@router.post("/habits", status_code=201)
def create_habit(body: HabitCreate) -> dict[str, Any]:
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
def update_habit(habit_id: str, body: HabitPatch) -> dict[str, Any]:
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
def set_habit_done(habit_id: str, body: HabitLogBody) -> dict[str, Any]:
    log_date = _resolved_date(body.date, allow_empty=False)
    try:
        habit = _workspace_store().set_habit_done(
            habit_id, log_date, body.done, op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"habit": habit, "persistence": "local"}


@router.delete("/habits/{habit_id}")
def delete_habit(habit_id: str, body: DeleteBody) -> dict[str, Any]:
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


class CategoriesOrdre(BaseModel):
    names: list[str] = Field(max_length=200)


class CategorieRenommage(BaseModel):
    ancien: str = Field(min_length=1, max_length=60)
    nouveau: str = Field(default="", max_length=60)


@router.get("/notes/categories")
def list_note_categories() -> dict[str, Any]:
    """Les catégories vivantes, dans l'ordre choisi. Route synchrone : SQLite."""
    return {"categories": _workspace_store().list_note_categories()}


@router.put("/notes/categories/ordre")
def order_note_categories(body: CategoriesOrdre) -> dict[str, Any]:
    return {"categories": _workspace_store().order_note_categories(body.names)}


@router.post("/notes/categories/renommer")
def rename_note_category(body: CategorieRenommage) -> dict[str, Any]:
    count = _workspace_store().rename_note_category(body.ancien, body.nouveau)
    return {"renamed": count, "categories": _workspace_store().list_note_categories()}


@router.put("/notes/ordre")
def reorder_notes(body: OrdreParIds) -> dict[str, Any]:
    """Fixe l'ordre manuel des notes citées (leur rang dans `ids`)."""
    changed = _workspace_store().reorder_notes(body.ids)
    return {"reordered": len(changed)}


@router.get("/notes/resumes")
def note_summaries(
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    notes = _workspace_store().list_notes(search=search)
    return {"notes": [resumer_note(note) for note in notes], "count": len(notes)}


@router.get("/notes/{note_id}")
def get_note(note_id: str) -> dict[str, Any]:
    try:
        return {"note": _workspace_store().get_note(note_id)}
    except SuccesError as exc:
        raise _domain_error(exc) from exc


@router.get("/notes")
def list_notes(
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    notes = _workspace_store().list_notes(search=search)
    return {
        "notes": notes,
        "count": len(notes),
        "pageFormats": sorted(NOTE_PAGE_FORMATS),
        "pageSizes": sorted(NOTE_PAGE_SIZES),
        "pageOrientations": sorted(NOTE_PAGE_ORIENTATIONS),
        "pageMargins": sorted(NOTE_PAGE_MARGINS),
        "pageBackgrounds": sorted(NOTE_PAGE_BACKGROUNDS),
        "fonts": sorted(NOTE_FONTS),
        "docLangs": sorted(NOTE_DOC_LANGS),
    }


@router.post("/notes", status_code=201)
def create_note(body: NoteCreate) -> dict[str, Any]:
    try:
        note = _workspace_store().create_note(
            body.model_dump(exclude={"opId"}), op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"note": note, "persistence": "local"}


@router.patch("/notes/{note_id}")
def update_note(note_id: str, body: NotePatch) -> dict[str, Any]:
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
def delete_note(note_id: str, body: DeleteBody) -> dict[str, Any]:
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
def dashboard(date: str | None = None) -> dict[str, Any]:
    return _workspace_store().dashboard(
        on_date=_resolved_date(date) if date is not None else None
    )


@router.get("/templates")
def list_templates(include_inactive: bool = True) -> dict[str, Any]:
    items = _continuity_store().list_templates(include_inactive=include_inactive)
    return {"templates": items, "count": len(items)}


@router.post("/templates", status_code=201)
def create_template(body: TemplateCreate) -> dict[str, Any]:
    data = body.model_dump(exclude={"opId"})
    data["startDate"] = _resolved_date(body.startDate, allow_empty=False)
    data["endDate"] = _resolved_date(body.endDate, allow_empty=False)
    try:
        item = _continuity_store().create_template(data, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"template": item, "persistence": "local"}


@router.patch("/templates/{template_id}")
def update_template(template_id: str, body: TemplatePatch) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True, exclude={"opId"})
    for key in ("startDate", "endDate"):
        if key in patch:
            patch[key] = _resolved_date(str(patch[key]), allow_empty=False)
    try:
        item = _continuity_store().update_template(template_id, patch, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"template": item, "persistence": "local"}


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, body: DeleteBody) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "confirmation_required",
                "message": "Confirmez la suppression de ce modèle et de ses instances.",
            },
        )
    try:
        result = _continuity_store().delete_template(template_id, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {**result, "persistence": "local"}


@router.post("/templates/materialize")
def materialize_templates(body: MaterializeBody) -> dict[str, Any]:
    try:
        return _continuity_store().materialize_templates(
            _resolved_date(body.startDate, allow_empty=False),
            _resolved_date(body.endDate, allow_empty=False),
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc


@router.get("/quotes")
def list_quotes(category: str = "") -> dict[str, Any]:
    items = _continuity_store().list_quotes(category=category)
    return {"quotes": items, "count": len(items)}


@router.post("/quotes", status_code=201)
def create_quote(body: QuoteCreate) -> dict[str, Any]:
    try:
        item = _continuity_store().create_quote(
            body.model_dump(exclude={"opId"}), op_id=body.opId
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"quote": item, "persistence": "local"}


@router.delete("/quotes/{quote_id}")
def delete_quote(quote_id: str, body: DeleteBody) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "confirmation_required",
                "message": "Confirmez la suppression de cette citation.",
            },
        )
    try:
        _continuity_store().delete_quote(quote_id, op_id=body.opId)
    except SuccesError as exc:
        raise _domain_error(exc) from exc
    return {"deleted": True, "id": quote_id, "persistence": "local"}


@router.get("/year-review")
def year_review(year: int, month: int | None = None) -> dict[str, Any]:
    try:
        return _continuity_store().year_review(year, month=month)
    except SuccesError as exc:
        raise _domain_error(exc) from exc


@router.get("/export")
def export_succes() -> dict[str, Any]:
    return _continuity_store().export_state()


@router.get("/sync/status")
def sync_status() -> dict[str, Any]:
    return get_store().sync_status()


@router.get("/sync/operations")
def sync_operations(after: int = 0, limit: int = 500) -> dict[str, Any]:
    return get_store().list_operations(after=after, limit=limit)


@router.post("/sync/pairings")
def create_sync_pairing(body: PairingCreate) -> dict[str, Any]:
    """Prepare a ten-minute invitation from the authenticated local app."""
    try:
        return _sync_store().create_pairing(body.deviceName)
    except SuccesError as exc:
        raise _domain_error(exc) from exc


@router.post("/sync/pair")
def redeem_sync_pairing(body: PairingRedeem) -> dict[str, Any]:
    """Redeem a pairing token (auth = valid invitation; no API key required)."""
    try:
        return _sync_store().redeem_pairing(body.pairingToken)
    except SuccesError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/sync/exchange")
def exchange_sync_operations(body: SyncExchangeBody) -> dict[str, Any]:
    """Exchange operations authenticated by the peer sync token in the body."""
    peer = _sync_store().peer_for_token(body.peerToken)
    if peer is None:
        raise HTTPException(
            status_code=401, detail="Cet appareil n'est pas autorisé à synchroniser."
        )
    try:
        return _sync_store().exchange(
            str(peer["id"]), after=body.cursor, operations=body.operations
        )
    except SuccesError as exc:
        raise _domain_error(exc) from exc


@router.put("/sync/relay")
def set_sync_relay(body: SyncRelayBody) -> dict[str, Any]:
    try:
        return _sync_store().set_relay_url(body.url)
    except SuccesError as exc:
        raise _domain_error(exc) from exc


@router.delete("/sync/relay")
def clear_sync_relay() -> dict[str, Any]:
    return _sync_store().clear_relay_url()


@router.post("/sync/join")
def join_sync_remote(body: SyncJoinBody) -> dict[str, Any]:
    """Redeem a remote invitation and store guest credentials locally."""
    try:
        return _sync_store().join_remote(
            body.pairingToken,
            relay_url=body.relayUrl,
            device_name=body.deviceName,
        )
    except SuccesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync/run")
def run_sync_exchange() -> dict[str, Any]:
    """Guest round-trip: push local ops, pull host ops through the relay."""
    try:
        return _sync_store().run_exchange()
    except SuccesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/sync/guest")
def clear_sync_guest() -> dict[str, Any]:
    return _sync_store().clear_guest_session()


@router.delete("/sync/peers/{peer_id}")
def revoke_sync_peer(peer_id: str) -> dict[str, Any]:
    revoked = _sync_store().revoke_peer(peer_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Cet appareil n'existe pas.")
    return {"revoked": True, "peerId": peer_id}


@router.post("/import/legacy")
def import_legacy(body: LegacyImportBody) -> dict[str, Any]:
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


from diapason.succes.finances_routes import register_finances_routes  # noqa: E402

register_finances_routes(
    router,
    get_store=get_store,
    domain_error=_domain_error,
    resolved_date=_resolved_date,
)

from diapason.succes.photos_routes import register_photos_routes  # noqa: E402

register_photos_routes(router, get_store=get_store, domain_error=_domain_error)


__all__ = ["get_store", "router", "set_store_for_tests"]
