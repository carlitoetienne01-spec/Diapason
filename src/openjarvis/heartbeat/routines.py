"""Routines catalog (ROUTINES.json) — Diapason-style cron jobs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from openjarvis.heartbeat.markdown import default_workspace_dir

logger = logging.getLogger(__name__)

BUILTIN_ROUTINES: list[dict[str, Any]] = [
    {
        "id": "morning-digest",
        "name": "Morning digest",
        "cron": "0 7 * * 1-5",
        "kind": "morning-digest",
        "enabled": True,
        "builtin": True,
        "deliver": {"notify": True, "speak": False},
    },
    {
        "id": "calendar-ping",
        "name": "Calendar ping",
        "cron": "*/15 8-18 * * 1-5",
        "kind": "prompt",
        "enabled": True,
        "builtin": True,
        "payload": {
            "prompt": (
                "Using calendar tools only: if I have a meeting starting within "
                "20 minutes, summarize title and start time. If none, reply exactly: SILENT."
            )
        },
        "deliver": {"notify": True, "speak": False},
    },
    {
        "id": "idle-check",
        "name": "Hourly idle nudge",
        "cron": "0 * * * *",
        "kind": "reminder",
        "enabled": False,
        "builtin": True,
        "payload": {
            "message": "Quick check-in: stretch, water, or glance at your next meeting."
        },
        # Only fire when the Mac has been idle ≥ 20 minutes
        "preCheck": {"idleMinSeconds": 1200},
        "deliver": {"notify": True, "speak": False},
    },
]


@dataclass
class Routine:
    id: str
    name: str = ""
    cron: str = "0 7 * * *"
    kind: str = "prompt"
    enabled: bool = True
    builtin: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    deliver: dict[str, Any] = field(default_factory=dict)
    pre_check: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Routine:
        return cls(
            id=str(d.get("id") or "").strip(),
            name=str(d.get("name") or d.get("id") or "").strip(),
            cron=str(d.get("cron") or "0 7 * * *").strip(),
            kind=str(d.get("kind") or "prompt").strip(),
            enabled=bool(d.get("enabled", True)),
            builtin=bool(d.get("builtin", False)),
            payload=dict(d.get("payload") or {}),
            deliver=dict(d.get("deliver") or {}),
            pre_check=dict(d.get("preCheck") or d.get("pre_check") or {}),
            raw=dict(d),
        )

    def to_dict(self) -> dict[str, Any]:
        out = {
            "id": self.id,
            "name": self.name,
            "cron": self.cron,
            "kind": self.kind,
            "enabled": self.enabled,
            "builtin": self.builtin,
        }
        if self.payload:
            out["payload"] = self.payload
        if self.deliver:
            out["deliver"] = self.deliver
        if self.pre_check:
            out["preCheck"] = self.pre_check
        return out


def routines_path(workspace: Path | str | None = None) -> Path:
    root = Path(workspace).expanduser() if workspace else default_workspace_dir()
    return root / "ROUTINES.json"


def state_path(workspace: Path | str | None = None) -> Path:
    root = Path(workspace).expanduser() if workspace else default_workspace_dir()
    return root / "ROUTINES_STATE.json"


def ensure_routines_file(workspace: Path | str | None = None) -> Path:
    path = routines_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        payload = {"version": 1, "routines": BUILTIN_ROUTINES, "deletedBuiltins": []}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_routines(workspace: Path | str | None = None) -> list[Routine]:
    path = ensure_routines_file(workspace)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read routines: %s", exc)
        return [Routine.from_dict(d) for d in BUILTIN_ROUTINES]

    deleted = set(data.get("deletedBuiltins") or [])
    items = data.get("routines") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []

    by_id: dict[str, Routine] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        r = Routine.from_dict(raw)
        if not r.id:
            continue
        by_id[r.id] = r

    # Merge missing builtins (unless deleted)
    for builtin in BUILTIN_ROUTINES:
        bid = builtin["id"]
        if bid in deleted or bid in by_id:
            continue
        by_id[bid] = Routine.from_dict(builtin)

    return list(by_id.values())


def save_routines(routines: list[Routine], workspace: Path | str | None = None) -> Path:
    path = ensure_routines_file(workspace)
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        deleted = existing.get("deletedBuiltins") or []
    except Exception:
        deleted = []
    payload = {
        "version": 1,
        "routines": [r.to_dict() for r in routines],
        "deletedBuiltins": deleted,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def get_routine(routine_id: str, workspace: Path | str | None = None) -> Optional[Routine]:
    for r in load_routines(workspace):
        if r.id == routine_id:
            return r
    return None


def set_routine_enabled(
    routine_id: str, enabled: bool, workspace: Path | str | None = None
) -> Optional[Routine]:
    routines = load_routines(workspace)
    found = None
    for r in routines:
        if r.id == routine_id:
            r.enabled = enabled
            found = r
            break
    if found is None:
        return None
    save_routines(routines, workspace)
    return found


def load_state(workspace: Path | str | None = None) -> dict[str, Any]:
    path = state_path(workspace)
    if not path.exists():
        return {"history": [], "last_run": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"history": [], "last_run": {}}


def record_run(
    routine_id: str,
    *,
    success: bool,
    result: str = "",
    skipped: bool = False,
    workspace: Path | str | None = None,
) -> None:
    from datetime import datetime, timezone

    path = state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = load_state(workspace)
    history = list(state.get("history") or [])
    entry = {
        "id": routine_id,
        "at": datetime.now(timezone.utc).isoformat(),
        "success": success,
        "skipped": skipped,
        "result": (result or "")[:500],
    }
    history.append(entry)
    state["history"] = history[-200:]
    last = dict(state.get("last_run") or {})
    last[routine_id] = entry
    state["last_run"] = last
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "BUILTIN_ROUTINES",
    "Routine",
    "ensure_routines_file",
    "get_routine",
    "load_routines",
    "load_state",
    "record_run",
    "routines_path",
    "save_routines",
    "set_routine_enabled",
    "state_path",
]
