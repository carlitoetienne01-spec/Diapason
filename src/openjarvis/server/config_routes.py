"""Config get/set HTTP API (writes ~/.openjarvis/config.toml)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class ConfigSetRequest(BaseModel):
    key: str = Field(..., description="Dotted config key, e.g. desktop.vision.enabled")
    value: Any = Field(..., description="New value (bool/int/float/str)")


def _config_path() -> Path:
    from openjarvis.core.config import DEFAULT_CONFIG_DIR, get_config_path

    env = os.environ.get("OPENJARVIS_CONFIG")
    if env:
        return Path(env).expanduser()
    try:
        return get_config_path()
    except Exception:
        return DEFAULT_CONFIG_DIR / "config.toml"


def set_config_value(key: str, value: Any) -> Any:
    """Validate, coerce, write TOML, clear load_config cache. Returns typed value."""
    import tomlkit

    from openjarvis.core.config import load_config, validate_config_key

    target_type = validate_config_key(key)
    if isinstance(value, str):
        if target_type is bool:
            low = value.lower()
            if low in ("true", "1", "yes"):
                typed: Any = True
            elif low in ("false", "0", "no"):
                typed = False
            else:
                raise ValueError(f"Invalid bool: {value!r}")
        elif target_type is int:
            typed = int(value)
        elif target_type is float:
            typed = float(value)
        else:
            typed = value
    else:
        typed = value
        if target_type is bool:
            typed = bool(value)
        elif target_type is int:
            typed = int(value)
        elif target_type is float:
            typed = float(value)

    path = _config_path()
    if path.exists():
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()
        path.parent.mkdir(parents=True, exist_ok=True)

    parts = key.split(".")
    current = doc
    for part in parts[:-1]:
        if part not in current:
            current.add(part, tomlkit.table())
        current = current[part]
    current[parts[-1]] = typed
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    try:
        load_config.cache_clear()
    except Exception:
        pass
    return typed


def get_config_snippet() -> Dict[str, Any]:
    """Return settings useful for the desktop Settings UI."""
    from openjarvis.core.config import load_config

    cfg = load_config()
    v = cfg.desktop.vision
    d = cfg.dictation
    w = cfg.speech.wakeword
    return {
        "desktop": {
            "vision": {
                "enabled": v.enabled,
                "allow_cloud": v.allow_cloud,
                "model": v.model,
                "share_interval_s": v.share_interval_s,
                "share_max_minutes": v.share_max_minutes,
                "monitor": v.monitor,
            }
        },
        "dictation": {
            "polish": d.polish,
            "dictionary": d.dictionary,
            "llm_polish": d.llm_polish,
            "email_mode": d.email_mode,
            "auto_learn": bool(getattr(d, "auto_learn", True)),
        },
        "speech": {
            "wakeword": {
                "enabled": w.enabled,
                "text_gate": w.text_gate,
                "backend": w.backend,
                "sensitivity": w.sensitivity,
            }
        },
        "heartbeat": {
            "enabled": cfg.heartbeat.enabled,
            "interval_seconds": cfg.heartbeat.interval_seconds,
        },
        "routines": {"enabled": cfg.routines.enabled},
    }


def create_config_router() -> APIRouter:
    router = APIRouter(prefix="/v1/config", tags=["config"])

    @router.get("")
    def get_config() -> Dict[str, Any]:
        return get_config_snippet()

    @router.post("/set")
    def post_set(body: ConfigSetRequest) -> Dict[str, Any]:
        # Allow-list keys the UI may change
        allowed_prefixes = (
            "desktop.vision.",
            "dictation.",
            "speech.wakeword.",
            "heartbeat.",
            "routines.",
        )
        key = (body.key or "").strip()
        if not any(key.startswith(p) for p in allowed_prefixes):
            raise HTTPException(400, f"Key not writable via API: {key}")
        try:
            typed = set_config_value(key, body.value)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "key": key, "value": typed}

    return router
