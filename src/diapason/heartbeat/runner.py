"""Heartbeat tick — drain one pending HEARTBEAT.md task."""

from __future__ import annotations

import logging
from typing import Any, Optional

from diapason.heartbeat.markdown import (
    append_changelog,
    ensure_heartbeat_file,
    mark_done,
    pending_now,
)
from diapason.heartbeat.quiet import in_quiet_hours

logger = logging.getLogger(__name__)


def _workspace_from_config(config: Any = None) -> Optional[str]:
    try:
        from diapason.core.config import load_config

        cfg = config or load_config()
        hb = getattr(cfg, "heartbeat", None)
        if hb is None:
            return None
        path = str(getattr(hb, "workspace_dir", "") or "").strip()
        return path or None
    except Exception:
        return None


def run_heartbeat_tick(
    *,
    system: Any = None,
    force: bool = False,
    workspace: str | None = None,
    config: Any = None,
) -> dict[str, Any]:
    """Process the first pending ## Now item. No-op if empty."""
    try:
        from diapason.core.config import load_config

        cfg = config or load_config()
        hb = getattr(cfg, "heartbeat", None)
        enabled = True if hb is None else bool(getattr(hb, "enabled", True))
        if not enabled and not force:
            return {"ok": True, "skipped": True, "reason": "disabled", "content": ""}
        quiet = in_quiet_hours(
            enabled=bool(getattr(hb, "quiet_hours_enabled", True)) if hb else True,
            start=str(getattr(hb, "quiet_hours_start", "22:00") if hb else "22:00"),
            end=str(getattr(hb, "quiet_hours_end", "07:00") if hb else "07:00"),
        )
        allowlist = []
        if hb is not None:
            raw = str(getattr(hb, "tool_allowlist", "") or "")
            allowlist = [t.strip() for t in raw.split(",") if t.strip()]
    except Exception:
        quiet = False
        allowlist = []

    ws = workspace or _workspace_from_config(config)
    ensure_heartbeat_file(ws)
    pending = pending_now(ws)
    if not pending:
        return {"ok": True, "skipped": True, "reason": "empty", "content": ""}

    task = pending[0]
    content = ""
    try:
        if system is not None:
            tools = allowlist or None
            content = str(
                system.ask(
                    (
                        "You are handling a heartbeat queue item. "
                        "Do the following briefly and safely. "
                        "Do not send email/SMS. Do not invent facts.\n\n"
                        f"TASK: {task.text}"
                    ),
                    agent="simple",
                    tools=tools,
                )
            )
        else:
            content = f"Acknowledged heartbeat task: {task.text}"
    except Exception as exc:
        logger.exception("heartbeat task failed")
        content = f"Heartbeat task failed: {exc}"
        append_changelog(f"FAILED {task.text} — {exc}", ws)
        return {
            "ok": False,
            "skipped": False,
            "task": task.text,
            "content": content,
            "error": str(exc),
        }

    mark_done(task, ws)
    note = content.strip().splitlines()[0][:160] if content.strip() else "done"
    append_changelog(f"DONE {task.text} — {note}", ws)

    return {
        "ok": True,
        "skipped": False,
        "task": task.text,
        "content": content,
        "quiet": quiet and not force,
        "delivered": not (quiet and not force),
    }


__all__ = ["run_heartbeat_tick"]
