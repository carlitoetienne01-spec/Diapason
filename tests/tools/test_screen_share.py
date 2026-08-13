"""Tests for continuous screen-share start/stop."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from diapason.desktop.screen_share import (
    get_screen_share,
    reset_screen_share_for_tests,
)
from diapason.tools.screen_vision_tools import (
    ScreenShareStartTool,
    ScreenShareStatusTool,
    ScreenShareStopTool,
    reset_rate_limit_for_tests,
)


def test_share_session_start_stop():
    reset_screen_share_for_tests()
    calls = {"n": 0}

    def describe(**kwargs):
        calls["n"] += 1
        return f"frame-{calls['n']}"

    share = get_screen_share()
    out = share.start(
        monitor=1,
        interval_s=60.0,  # don't loop during test
        max_minutes=30.0,
        describe_fn=describe,
    )
    assert out["ok"] is True
    assert out["active"] is True
    assert "frame-1" in out["summary"]
    assert share.is_active()

    st = share.status()
    assert st["active"] is True
    assert st["frames"] >= 1

    stop = share.stop(reason="user")
    assert stop["active"] is False
    assert "stopped" in stop["message"].lower() or "plus" in stop["message"].lower()
    assert share.is_active() is False


def test_share_tools_with_config(monkeypatch):
    reset_screen_share_for_tests()
    reset_rate_limit_for_tests()

    cfg = SimpleNamespace(
        enabled=True,
        monitor=1,
        share_interval_s=60.0,
        share_max_minutes=30.0,
    )
    frames = {"n": 0}

    def fake_describe(**kwargs):
        frames["n"] += 1
        from diapason.core.types import ToolResult

        return ToolResult(
            tool_name="screen_describe",
            content=f"desk-{frames['n']}",
            success=True,
        )

    with patch("diapason.tools.screen_vision_tools._vision_config", return_value=cfg):
        with patch(
            "diapason.tools.screen_vision_tools.describe_screen",
            side_effect=fake_describe,
        ):
            start = ScreenShareStartTool().execute()
            assert start.success
            assert (
                "share" in start.content.lower()
                or "écran" in start.content.lower()
                or "screen" in start.content.lower()
            )

            status = ScreenShareStatusTool().execute()
            assert status.success
            assert status.metadata.get("active") is True

            stop = ScreenShareStopTool().execute()
            assert stop.success
            status2 = ScreenShareStatusTool().execute()
            assert status2.metadata.get("active") is False


def test_share_start_disabled():
    reset_screen_share_for_tests()
    with patch(
        "diapason.tools.screen_vision_tools._vision_config",
        return_value=SimpleNamespace(enabled=False),
    ):
        result = ScreenShareStartTool().execute()
    assert result.success is False
    assert "disabled" in result.content.lower()


def test_voice_allowlist_share_tools():
    import diapason.tools.screen_vision_tools  # noqa: F401
    from diapason.speech.realtime.tools import (
        DEFAULT_VOICE_TOOL_IDS,
        list_voice_tool_ids,
    )

    for tid in (
        "screen_share_start",
        "screen_share_stop",
        "screen_share_status",
    ):
        assert tid in DEFAULT_VOICE_TOOL_IDS
        assert tid in list_voice_tool_ids()
