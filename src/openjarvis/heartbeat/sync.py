"""Sync heartbeat + routines into TaskScheduler (deterministic task IDs)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from openjarvis.heartbeat.markdown import ensure_heartbeat_file
from openjarvis.heartbeat.routines import ensure_routines_file, load_routines

logger = logging.getLogger(__name__)

HEARTBEAT_TASK_ID = "heartbeat:tick"
HEARTBEAT_PROMPT = "[HEARTBEAT TICK]"


def _upsert_task(
    scheduler: Any,
    *,
    task_id: str,
    prompt: str,
    schedule_type: str,
    schedule_value: str,
    metadata: dict[str, Any],
    agent: str = "simple",
    tools: str = "",
    active: bool = True,
) -> str:
    existing = None
    try:
        for t in scheduler.list_tasks():
            if t.id == task_id:
                existing = t
                break
    except Exception:
        existing = None

    if existing is not None:
        d = existing.to_dict()
        d["prompt"] = prompt
        d["schedule_type"] = schedule_type
        d["schedule_value"] = schedule_value
        d["metadata"] = metadata
        d["agent"] = agent
        d["tools"] = tools
        d["status"] = "active" if active else "paused"
        # Recompute next_run
        from openjarvis.scheduler.scheduler import ScheduledTask

        task = ScheduledTask.from_dict(d)
        task.next_run = scheduler._compute_next_run(task)  # noqa: SLF001
        d = task.to_dict()
        scheduler._store.save_task(d)  # noqa: SLF001
        return task_id

    task = scheduler.create_task(
        prompt=prompt,
        schedule_type=schedule_type,
        schedule_value=schedule_value,
        agent=agent,
        tools=tools,
        metadata=metadata,
    )
    d = task.to_dict()
    d["id"] = task_id
    d["status"] = "active" if active else "paused"
    scheduler._store.save_task(d)  # noqa: SLF001
    return task_id


def sync_heartbeat_and_routines(
    scheduler: Any,
    config: Any = None,
    *,
    workspace: str | None = None,
) -> dict[str, Any]:
    """Upsert heartbeat:tick + routine:{id} tasks. Returns summary."""
    try:
        from openjarvis.core.config import load_config

        cfg = config or load_config()
    except Exception:
        cfg = config

    hb = getattr(cfg, "heartbeat", None) if cfg is not None else None
    rt = getattr(cfg, "routines", None) if cfg is not None else None
    ws = workspace or (
        str(getattr(hb, "workspace_dir", "") or "").strip() or None if hb else None
    )

    ensure_heartbeat_file(ws)
    ensure_routines_file(ws)

    summary: dict[str, Any] = {"heartbeat": None, "routines": []}

    hb_enabled = bool(getattr(hb, "enabled", False)) if hb is not None else False
    interval = int(getattr(hb, "interval_seconds", 1800) if hb is not None else 1800)
    summary["heartbeat"] = _upsert_task(
        scheduler,
        task_id=HEARTBEAT_TASK_ID,
        prompt=HEARTBEAT_PROMPT,
        schedule_type="interval",
        schedule_value=str(max(60, interval)),
        metadata={"openjarvis_kind": "heartbeat"},
        active=hb_enabled,
    )

    routines_enabled = bool(getattr(rt, "enabled", True)) if rt is not None else True
    for routine in load_routines(ws):
        task_id = f"routine:{routine.id}"
        active = routines_enabled and routine.enabled
        _upsert_task(
            scheduler,
            task_id=task_id,
            prompt=f"[ROUTINE:{routine.id}]",
            schedule_type="cron",
            schedule_value=routine.cron,
            metadata={
                "openjarvis_kind": "routine",
                "routine_id": routine.id,
                "kind": routine.kind,
            },
            active=active,
        )
        summary["routines"].append({"id": routine.id, "active": active, "task_id": task_id})

    logger.info(
        "Synced heartbeat=%s routines=%d",
        summary["heartbeat"],
        len(summary["routines"]),
    )
    return summary


__all__ = [
    "HEARTBEAT_PROMPT",
    "HEARTBEAT_TASK_ID",
    "sync_heartbeat_and_routines",
]
