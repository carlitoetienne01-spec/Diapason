"""What dictation needs to work, as inspectable data.

Every failure we hit getting dictation running looked identical from the
outside — "nothing happens" — and each had a different cause: a missing
permission, a missing model, an agent that was not loaded. The checks are
therefore *individually reportable*: the setup wizard, the doctor command and
any future UI all read the same list, and each item says what is wrong AND
what to do about it.

Pure enough to test: each check returns a verdict, and only the probes it
calls touch the system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List


@dataclass(frozen=True)
class Check:
    """One requirement, its state, and the single next action."""

    name: str
    ok: bool
    detail: str
    fix: str = ""
    blocking: bool = True

    @property
    def symbol(self) -> str:
        return "✓" if self.ok else ("✗" if self.blocking else "!")


def check_permissions() -> List[Check]:
    """The three TCC grants, reported separately.

    Separately, because they fail separately and each has its own pane —
    lumping them into one "permissions OK" line is what made the microphone
    failure so hard to see.
    """
    from openjarvis.desktop import permissions

    probes: List[tuple[str, Callable[[], bool], str, str]] = [
        (
            "Input Monitoring",
            permissions.input_monitoring_ok,
            "hear the dictation key",
            "System Settings › Privacy & Security › Input Monitoring",
        ),
        (
            "Microphone",
            permissions.microphone_ok,
            "record your voice",
            "System Settings › Privacy & Security › Microphone",
        ),
        (
            "Accessibility",
            permissions.accessibility_ok,
            "paste into the app in front",
            "System Settings › Privacy & Security › Accessibility",
        ),
    ]
    out: List[Check] = []
    for name, probe, purpose, pane in probes:
        ok = probe()
        out.append(
            Check(
                name=name,
                ok=ok,
                detail=f"needed to {purpose}",
                fix="" if ok else f"Enable this app in {pane}, then restart it.",
            )
        )
    return out


def check_model(config=None) -> Check:
    """Is a speech backend actually resolvable right now?"""
    try:
        from openjarvis.core.config import load_config
        from openjarvis.speech._discovery import get_speech_backend

        cfg = config or load_config()
        backend = get_speech_backend(cfg)
        model = str(getattr(cfg.speech, "model", "") or "?")
        if backend is None:
            return Check(
                name="Speech model",
                ok=False,
                detail="no backend could be resolved",
                fix=(
                    "Run `jarvis model pull small`, or set [privacy] "
                    "local_only = false to allow a cloud backend."
                ),
            )
        return Check(
            name="Speech model",
            ok=True,
            detail=f"{type(backend).__name__} ({model})",
        )
    except Exception as exc:  # noqa: BLE001 - report, never crash setup
        return Check(
            name="Speech model",
            ok=False,
            detail=f"could not check: {exc}",
            fix="Run `jarvis doctor` for details.",
        )


def check_service() -> Check:
    """Is the background agent installed and loaded?"""
    try:
        from openjarvis.desktop import launch_agent

        loaded = launch_agent.is_loaded()
        return Check(
            name="Background service",
            ok=loaded,
            detail="running at login" if loaded else "not installed",
            fix="" if loaded else "Run `jarvis dictate-service install`.",
            blocking=False,  # dictation works in the foreground without it
        )
    except Exception as exc:  # noqa: BLE001
        return Check(
            name="Background service",
            ok=False,
            detail=f"could not check: {exc}",
            blocking=False,
        )


def check_hotkey(config=None) -> Check:
    """Is the configured hotkey one the tap can actually bind?"""
    from openjarvis.desktop.keycodes import SUPPORTED_HOTKEYS, normalize_hotkey

    try:
        from openjarvis.core.config import load_config

        cfg = config or load_config()
        raw = str(getattr(cfg.dictation, "hotkey", "") or "control")
    except Exception:  # noqa: BLE001
        raw = "control"
    key = normalize_hotkey(raw)
    coerced = key != raw.strip().lower()
    return Check(
        name="Hotkey",
        ok=not coerced,
        detail=f"hold {key.capitalize()}"
        + (f" (config says {raw!r}, which is not a bare modifier)" if coerced else ""),
        fix=(
            f"Run `jarvis config set dictation.hotkey {key}` "
            f"(one of: {', '.join(SUPPORTED_HOTKEYS)})."
            if coerced
            else ""
        ),
        blocking=False,  # it still works, it just says something misleading
    )


def run_all(config=None) -> List[Check]:
    """Every check, in the order a first-time user should fix them."""
    checks: List[Check] = []
    checks.extend(check_permissions())
    checks.append(check_model(config))
    checks.append(check_hotkey(config))
    checks.append(check_service())
    return checks


def blocking_failures(checks: List[Check]) -> List[Check]:
    return [c for c in checks if not c.ok and c.blocking]


def is_ready(checks: List[Check]) -> bool:
    """Ready means: dictation would work right now if you held the key."""
    return not blocking_failures(checks)
