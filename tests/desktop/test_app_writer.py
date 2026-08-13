from __future__ import annotations

from unittest.mock import MagicMock

from diapason.core.types import ToolResult
from diapason.desktop.app_writer import write_text


def test_named_app_prefers_accessibility(monkeypatch):
    opened = ToolResult(
        tool_name="open_anything",
        content="ok",
        success=True,
        metadata={"app": "Notes"},
    )
    monkeypatch.setattr(
        "diapason.tools.desktop_tools.open_application",
        lambda _: opened,
    )
    monkeypatch.setattr(
        "diapason.desktop.frontmost.wait_until_frontmost",
        lambda *_, **__: True,
    )
    monkeypatch.setattr("diapason.desktop.accessibility.insert_text", lambda _: True)
    paste = MagicMock()
    monkeypatch.setattr("diapason.tools.desktop_tools.PasteToFrontmostTool", paste)

    result = write_text("secret text", app_name="Notes")

    assert result.success is True
    assert result.method == "accessibility"
    assert result.verified is True
    paste.assert_not_called()


def test_clipboard_preserving_fallback(monkeypatch):
    monkeypatch.setattr("diapason.desktop.accessibility.insert_text", lambda _: False)
    tool = MagicMock()
    tool.execute.return_value = ToolResult(
        tool_name="paste_to_frontmost",
        content="pasted",
        success=True,
    )
    monkeypatch.setattr(
        "diapason.tools.desktop_tools.PasteToFrontmostTool",
        MagicMock(return_value=tool),
    )

    result = write_text("hello")

    assert result.success is True
    assert result.method == "clipboard"
    tool.execute.assert_called_once_with(text="hello")
