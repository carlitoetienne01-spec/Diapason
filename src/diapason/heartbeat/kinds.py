"""Routine kind handlers (morning-digest, reminder, prompt, …)."""

from __future__ import annotations

import logging
from typing import Any

from diapason.heartbeat.quiet import in_quiet_hours
from diapason.heartbeat.routines import Routine, record_run

logger = logging.getLogger(__name__)


def _quiet_from_config(config: Any = None) -> bool:
    try:
        from diapason.core.config import load_config

        cfg = config or load_config()
        hb = getattr(cfg, "heartbeat", None)
        if hb is None:
            return False
        return in_quiet_hours(
            enabled=bool(getattr(hb, "quiet_hours_enabled", True)),
            start=str(getattr(hb, "quiet_hours_start", "22:00")),
            end=str(getattr(hb, "quiet_hours_end", "07:00")),
        )
    except Exception:
        return False


def _should_deliver(
    routine: Routine, *, force: bool = False, config: Any = None
) -> bool:
    if force:
        return True
    if _quiet_from_config(config):
        return False
    return True


def _precheck_idle(routine: Routine, *, force: bool = False) -> tuple[bool, str]:
    """Honor preCheck.idleMinSeconds / idleMaxSeconds (macOS HID idle)."""
    if force:
        return True, ""
    pc = routine.pre_check or {}
    idle_min = pc.get("idleMinSeconds", pc.get("idle_min_seconds"))
    idle_max = pc.get("idleMaxSeconds", pc.get("idle_max_seconds"))
    if idle_min is None and idle_max is None:
        return True, ""
    try:
        from diapason.desktop.idle import idle_seconds

        secs = idle_seconds()
    except Exception:
        secs = None
    if secs is None:
        # Unknown idle → skip idle-gated routines (safer than false-firing)
        return False, "idle_unknown"
    if idle_min is not None and secs < float(idle_min):
        return False, f"idle_below_min ({secs:.0f}<{idle_min})"
    if idle_max is not None and secs > float(idle_max):
        return False, f"idle_above_max ({secs:.0f}>{idle_max})"
    return True, ""


def run_routine(
    routine: Routine,
    *,
    system: Any = None,
    force: bool = False,
    workspace: str | None = None,
    config: Any = None,
) -> dict[str, Any]:
    """Execute one routine. Returns structured result."""
    if not routine.enabled and not force:
        record_run(
            routine.id,
            success=True,
            result="disabled",
            skipped=True,
            workspace=workspace,
        )
        return {"ok": True, "skipped": True, "reason": "disabled", "content": ""}

    ok_idle, idle_reason = _precheck_idle(routine, force=force)
    if not ok_idle:
        record_run(
            routine.id,
            success=True,
            result=idle_reason,
            skipped=True,
            workspace=workspace,
        )
        return {"ok": True, "skipped": True, "reason": idle_reason, "content": ""}

    quiet = _quiet_from_config(config) and not force
    kind = (routine.kind or "prompt").strip().lower()

    try:
        if kind == "morning-digest":
            content = _run_morning_digest(system=system, speak=False)
        elif kind == "reminder":
            content = str(
                (routine.payload or {}).get("message")
                or (routine.payload or {}).get("prompt")
                or routine.name
                or "Reminder"
            )
        elif kind in ("prompt", "calendar-ping", "calendar_ping"):
            content = _run_prompt(routine, system=system)
        elif kind == "shell":
            content = "shell kind disabled by default (set allow_shell in config)."
            record_run(
                routine.id,
                success=False,
                result=content,
                skipped=True,
                workspace=workspace,
            )
            return {
                "ok": False,
                "skipped": True,
                "reason": "shell_denied",
                "content": content,
            }
        else:
            content = f"Unknown routine kind: {kind}"

        # SILENT short-circuit (calendar ping with nothing due)
        if (content or "").strip().upper() == "SILENT":
            record_run(
                routine.id,
                success=True,
                result="SILENT",
                skipped=True,
                workspace=workspace,
            )
            return {"ok": True, "skipped": True, "reason": "silent", "content": ""}

        deliver = _should_deliver(routine, force=force, config=config)
        if quiet:
            # Still ran; suppress ambient delivery
            record_run(
                routine.id,
                success=True,
                result=f"[quiet] {content}",
                skipped=False,
                workspace=workspace,
            )
            return {
                "ok": True,
                "skipped": False,
                "quiet": True,
                "delivered": False,
                "content": content,
            }

        record_run(
            routine.id,
            success=True,
            result=content,
            skipped=False,
            workspace=workspace,
        )
        return {
            "ok": True,
            "skipped": False,
            "quiet": False,
            "delivered": deliver,
            "content": content,
        }
    except Exception as exc:
        logger.exception("routine %s failed", routine.id)
        record_run(
            routine.id,
            success=False,
            result=str(exc),
            skipped=False,
            workspace=workspace,
        )
        return {"ok": False, "skipped": False, "content": str(exc), "error": str(exc)}


def _run_morning_digest(*, system: Any = None, speak: bool = False) -> str:
    # Prefer cached digest text; optionally trigger generation via agent
    try:
        from diapason.agents.digest_store import DigestStore

        store = DigestStore()
        artifact = store.get_today() or store.get_latest()
        if artifact and artifact.text:
            text = artifact.text
            store.close()
            return text[:4000]
        store.close()
    except Exception:
        logger.debug("digest store unavailable", exc_info=True)

    if system is not None:
        try:
            return str(
                system.ask(
                    "Generate my morning digest (text only).", agent="morning_digest"
                )
            )[:4000]
        except Exception as exc:
            return f"Morning digest failed: {exc}"

    return (
        "No morning digest available. Run: diapason digest --fresh "
        "(or enable [digest] + connectors)."
    )


def _run_prompt(routine: Routine, *, system: Any = None) -> str:
    prompt = str(
        (routine.payload or {}).get("prompt") or (routine.raw or {}).get("prompt") or ""
    ).strip()
    if not prompt:
        return "SILENT"
    if system is None:
        # Dry-run without system: treat calendar-style prompts as silent
        if "SILENT" in prompt.upper():
            return "SILENT"
        return f"[dry-run] {prompt[:200]}"
    try:
        out = str(system.ask(prompt, agent="simple")).strip()
        return out or "SILENT"
    except Exception as exc:
        return f"Prompt routine failed: {exc}"


__all__ = ["run_routine"]
