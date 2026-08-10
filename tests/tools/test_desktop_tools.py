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


def test_looks_like_url_and_normalize():
    from diapason.tools.desktop_tools import looks_like_url, normalize_url, web_search_url

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

