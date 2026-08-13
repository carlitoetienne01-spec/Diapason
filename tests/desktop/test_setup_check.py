"""Setup checks — each failure must be individually visible and actionable."""

from __future__ import annotations

from unittest.mock import patch

from diapason.desktop import setup_check
from diapason.desktop.setup_check import (
    Check,
    blocking_failures,
    check_hotkey,
    check_permissions,
    is_ready,
)

_PERM = "diapason.desktop.permissions"


def test_permissions_are_reported_one_by_one():
    """Lumping them into one line is what hid the microphone failure."""
    with patch(f"{_PERM}.input_monitoring_ok", return_value=True):
        with patch(f"{_PERM}.microphone_ok", return_value=False):
            with patch(f"{_PERM}.accessibility_ok", return_value=True):
                checks = check_permissions()

    by_name = {c.name: c for c in checks}
    assert by_name["Input Monitoring"].ok is True
    assert by_name["Microphone"].ok is False
    assert by_name["Accessibility"].ok is True


def test_a_failed_check_says_what_to_do():
    with patch(f"{_PERM}.input_monitoring_ok", return_value=False):
        with patch(f"{_PERM}.microphone_ok", return_value=True):
            with patch(f"{_PERM}.accessibility_ok", return_value=True):
                checks = check_permissions()

    failed = next(c for c in checks if not c.ok)
    assert "Input Monitoring" in failed.fix
    assert "restart" in failed.fix.lower()


def test_a_passing_check_offers_no_pointless_advice():
    with patch(f"{_PERM}.input_monitoring_ok", return_value=True):
        with patch(f"{_PERM}.microphone_ok", return_value=True):
            with patch(f"{_PERM}.accessibility_ok", return_value=True):
                checks = check_permissions()
    assert all(c.fix == "" for c in checks)


def test_symbols_distinguish_blocking_from_advisory():
    assert Check("x", True, "").symbol == "✓"
    assert Check("x", False, "", blocking=True).symbol == "✗"
    assert Check("x", False, "", blocking=False).symbol == "!"


def test_readiness_ignores_non_blocking_problems():
    """No background service still lets you dictate in the foreground."""
    checks = [
        Check("Perm", True, ""),
        Check("Background service", False, "not installed", blocking=False),
    ]
    assert is_ready(checks) is True
    assert blocking_failures(checks) == []


def test_readiness_fails_on_a_blocking_problem():
    checks = [Check("Microphone", False, "", blocking=True)]
    assert is_ready(checks) is False
    assert len(blocking_failures(checks)) == 1


def test_hotkey_check_flags_a_non_bare_modifier():
    """The 'Cmd+Alt+Space' case: it works, but the config lies about it."""

    class _Cfg:
        class dictation:  # noqa: N801
            hotkey = "Cmd+Alt+Space"

    c = check_hotkey(_Cfg())
    assert c.ok is False
    assert c.blocking is False  # dictation still works
    assert "control" in c.fix


def test_hotkey_check_passes_on_a_bare_modifier():
    class _Cfg:
        class dictation:  # noqa: N801
            hotkey = "control"

    c = check_hotkey(_Cfg())
    assert c.ok is True
    assert c.fix == ""


def test_model_check_reports_a_missing_backend_with_a_fix():
    with patch("diapason.speech._discovery.get_speech_backend", return_value=None):
        c = setup_check.check_model()
    assert c.ok is False
    assert "model pull" in c.fix


def test_checks_never_raise_even_when_a_probe_explodes():
    """A setup screen that crashes is worse than one reporting a failure."""
    with patch(
        "diapason.speech._discovery.get_speech_backend",
        side_effect=RuntimeError("boom"),
    ):
        c = setup_check.check_model()
    assert c.ok is False
    assert "boom" in c.detail
