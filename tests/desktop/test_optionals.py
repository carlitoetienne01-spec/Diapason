"""Tests for optional desktop parity features."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from diapason.heartbeat.kinds import run_routine
from diapason.heartbeat.routines import Routine
from diapason.tools.voice_mac_tools import MailSendTool, MessagesSendTool


def test_mail_send_requires_confirm():
    r = MailSendTool().execute(confirm=False)
    assert r.success is False
    assert "confirm" in r.content.lower()


def test_messages_send_requires_confirm():
    r = MessagesSendTool().execute(recipient="+15551234567", body="hi", confirm=False)
    assert r.success is False
    assert "confirm" in r.content.lower()


def test_email_mode_auto_uses_frontmost(monkeypatch):
    from diapason.desktop import voice_commands as vc

    class _D:
        polish = True
        dictionary = False
        llm_polish = False
        email_mode = "auto"
        llm_timeout_ms = 500
        dictionary_path = ""

    class _Cfg:
        dictation = _D()

        class speech:
            class wakeword:
                text_gate = False

    monkeypatch.setattr("diapason.core.config.load_config", lambda: _Cfg())
    with patch(
        "diapason.desktop.frontmost.is_email_composer_context",
        return_value=True,
    ):
        out = vc.finalize_dictation(
            "this is a note about the project timeline",
            polish=True,
            llm_polish=False,
        )
    assert out["mode"] == "paste"
    assert out["meta"]["email_mode"] is True


def test_routine_idle_precheck_skips(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("diapason.desktop.idle.idle_seconds", lambda: 30.0)
    routine = Routine(
        id="idle-test",
        name="Idle",
        kind="reminder",
        enabled=True,
        payload={"message": "nudge"},
        pre_check={"idleMinSeconds": 600},
    )
    out = run_routine(routine, force=False, workspace=str(tmp_path))
    assert out["skipped"] is True
    assert "idle" in out["reason"]


def test_routine_idle_precheck_passes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("diapason.desktop.idle.idle_seconds", lambda: 900.0)
    routine = Routine(
        id="idle-test-ok",
        name="Idle",
        kind="reminder",
        enabled=True,
        payload={"message": "nudge"},
        pre_check={"idleMinSeconds": 600},
    )
    with patch("diapason.heartbeat.kinds._quiet_from_config", return_value=False):
        out = run_routine(routine, force=False, workspace=str(tmp_path))
    assert out.get("skipped") is not True or out.get("reason") != "idle_below_min"
    assert out["ok"] is True
    assert "nudge" in (out.get("content") or "")


def test_config_set_roundtrip(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[desktop.vision]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(cfg_path))

    from diapason.core.config import load_config
    from diapason.server.config_routes import get_config_snippet, set_config_value

    load_config.cache_clear()
    typed = set_config_value("desktop.vision.enabled", True)
    assert typed is True
    load_config.cache_clear()
    snippet = get_config_snippet()
    assert snippet["desktop"]["vision"]["enabled"] is True


def test_screen_share_status_route():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from diapason.desktop.screen_share import reset_screen_share_for_tests
    from diapason.server.screen_share_routes import create_screen_share_router

    reset_screen_share_for_tests()
    app = FastAPI()
    app.include_router(create_screen_share_router())
    client = TestClient(app)
    res = client.get("/v1/screen_share/status")
    assert res.status_code == 200
    assert res.json()["active"] is False
