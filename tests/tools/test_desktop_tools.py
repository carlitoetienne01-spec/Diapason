"""Tests for desktop automation tools (mocked subprocess)."""

from __future__ import annotations

from unittest.mock import patch

from diapason.tools.desktop_tools import FocusAppTool, OpenUriTool, PasteToFrontmostTool


def test_open_uri_darwin():
    tool = OpenUriTool()
    with patch("diapason.tools.desktop_tools.sys.platform", "darwin"):
        with patch("diapason.tools.desktop_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            result = tool.execute(uri="https://example.com")
    assert result.success
    run.assert_called()


def test_focus_app_requires_name():
    tool = FocusAppTool()
    result = tool.execute(app_name="")
    assert result.success is False


def test_paste_to_frontmost_empty():
    tool = PasteToFrontmostTool()
    assert tool.execute(text="").success is False


def test_agent_paste_requires_confirmation():
    assert PasteToFrontmostTool().spec.requires_confirmation is True


def test_looks_like_url_and_normalize():
    from diapason.tools.desktop_tools import (
        looks_like_url,
        normalize_url,
        web_search_url,
    )

    assert looks_like_url("youtube.com")
    assert looks_like_url("https://example.com/x")
    assert not looks_like_url("Cursor")
    assert normalize_url("www.google.com").startswith("https://")
    assert "q=" in web_search_url("meteo paris")


def test_open_anything_url(monkeypatch):
    from diapason.tools.desktop_tools import OpenAnythingTool

    tool = OpenAnythingTool()
    with patch("diapason.tools.desktop_tools.sys.platform", "darwin"):
        with patch("diapason.tools.desktop_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            result = tool.execute(target="youtube.com", kind="url")
    assert result.success
    assert "youtube.com" in result.content.lower() or result.success


def test_open_anything_search(monkeypatch):
    from diapason.tools.desktop_tools import OpenAnythingTool

    tool = OpenAnythingTool()
    with patch("diapason.tools.desktop_tools.sys.platform", "darwin"):
        with patch("diapason.tools.desktop_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            result = tool.execute(target="meteo paris", kind="search")
    assert result.success
    assert run.called
    # first arg to open should include google search
    cmd = run.call_args[0][0]
    assert any("google.com" in str(c) for c in cmd)


def test_open_anything_app(monkeypatch):
    from diapason.tools.desktop_tools import OpenAnythingTool

    tool = OpenAnythingTool()
    with patch("diapason.tools.desktop_tools.sys.platform", "darwin"):
        with patch(
            "diapason.tools.desktop_tools.resolve_mac_app_name",
            return_value="Safari",
        ):
            with patch("diapason.tools.desktop_tools._run") as run:
                run.return_value.returncode = 0
                run.return_value.stderr = ""
                run.return_value.stdout = ""
                result = tool.execute(target="Safari", kind="app")
    assert result.success
    assert run.called


class TestUserBrowsingBoundary:
    """User-commanded browsing is NOT assistant egress (core/local_mode.py).

    The guard used to block « ouvre youtube » for the very users local-only
    is meant to serve. Handing a URL to the user's own browser is the same
    gesture as dictation pasting their words into a cloud-backed app.
    """

    def test_open_in_browser_works_under_local_only(self, monkeypatch):
        import diapason.core.config as config_mod
        from diapason.tools import desktop_tools

        class _Privacy:
            local_only = True

        class _Cfg:
            privacy = _Privacy()

        monkeypatch.setattr(config_mod, "load_config", lambda: _Cfg())

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)

            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            return R()

        monkeypatch.setattr(desktop_tools, "_run", fake_run)
        monkeypatch.setattr(desktop_tools.sys, "platform", "darwin")
        result = desktop_tools.open_in_browser(
            "https://www.youtube.com/results?search_query=kompa"
        )
        assert result.success, result.content
        assert any("youtube.com" in str(c) for c in calls)
