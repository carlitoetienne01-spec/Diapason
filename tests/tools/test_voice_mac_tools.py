"""Tests for macOS voice tools (mocked)."""

from __future__ import annotations

from unittest.mock import patch

from diapason.tools.voice_mac_tools import (
    CalendarQueryTool,
    FindFilesTool,
    MailComposeTool,
    MessagesComposeTool,
    SpotifyPlayTool,
)


def test_calendar_query_non_darwin():
    tool = CalendarQueryTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "linux"):
        result = tool.execute(when="today")
    assert result.success is False


def test_calendar_query_darwin_ok():
    tool = CalendarQueryTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "Events for today:\n09:00 — Standup\n"
            run.return_value.stderr = ""
            result = tool.execute(when="today")
    assert result.success
    assert "Standup" in result.content


def test_spotify_play_search_uri():
    tool = SpotifyPlayTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            result = tool.execute(query="rock", action="search")
    assert result.success
    cmd = run.call_args[0][0]
    assert any("spotify:search:" in str(c) for c in cmd)


def test_find_files_empty_query():
    tool = FindFilesTool()
    assert tool.execute(query="").success is False


def test_find_files_mdfind():
    tool = FindFilesTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools.shutil.which", return_value="mdfind"):
            with patch("diapason.tools.voice_mac_tools._run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "/Users/x/Documents/facture.pdf\n"
                run.return_value.stderr = ""
                result = tool.execute(query="facture", limit=5)
    assert result.success
    assert "facture.pdf" in result.content


def test_mail_compose_draft_not_sent():
    tool = MailComposeTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "ok"
            run.return_value.stderr = ""
            result = tool.execute(
                to="ada@example.com",
                subject="Hello",
                body="Hi Ada",
                send=True,  # must be ignored by tool (no send path)
            )
    assert result.success
    assert result.metadata.get("sent") is False
    assert "Not sent" in result.content
    script = run.call_args[0][0][2]
    assert "ada@example.com" in script
    assert "send newMessage" not in script.lower()


def test_mail_compose_mailto_fallback():
    tool = MailComposeTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            fail = type("R", (), {"returncode": 1, "stdout": "", "stderr": "denied"})()
            ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            run.side_effect = [fail, ok]
            result = tool.execute(to="bob@example.com", subject="Hi")
    assert result.success
    assert result.metadata.get("via") == "mailto"
    assert result.metadata.get("sent") is False


def test_messages_compose_opens_sms_uri():
    tool = MessagesComposeTool()
    with patch("diapason.tools.voice_mac_tools.sys.platform", "darwin"):
        with patch("diapason.tools.voice_mac_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            result = tool.execute(recipient="+15551234567", body="Salut")
    assert result.success
    assert result.metadata.get("sent") is False
    cmd = run.call_args[0][0]
    assert cmd[0] == "open"
    assert any(str(c).startswith("sms:") for c in cmd)


def test_messages_compose_requires_recipient():
    tool = MessagesComposeTool()
    assert tool.execute(recipient="").success is False
