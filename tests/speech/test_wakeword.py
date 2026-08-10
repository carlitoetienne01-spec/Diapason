"""Tests for wake-word phrase gate and listener."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from diapason.speech.wake_phrases import has_wake_word, strip_wake_word
from diapason.speech.wakeword import WakeListenConfig, WakeWordListener


def test_has_wake_word_en_fr():
    assert has_wake_word("Hey Diapason")
    assert has_wake_word("diapason")
    assert has_wake_word("Dis Diapason, ouvre Cursor")
    assert has_wake_word("ok diapason what's up")
    assert has_wake_word("DIAPASON")


def test_has_wake_word_rejects_mid_sentence():
    assert not has_wake_word("le jarvis de iron man")
    assert not has_wake_word("I like jarvis movies")
    assert not has_wake_word("")


def test_strip_wake_word():
    assert strip_wake_word("Diapason, ouvre YouTube") == "ouvre YouTube"
    assert "Cursor" in strip_wake_word("Hey Diapason ouvre Cursor")
    assert strip_wake_word("Dis Diapason") == ""


def test_finalize_wake_command(monkeypatch):
    from diapason.desktop import voice_commands as vc

    monkeypatch.setattr(
        vc,
        "execute_voice_action",
        lambda action: {
            "handled": True,
            "kind": action.kind,
            "target": action.target,
            "success": True,
            "detail": "ok",
        },
    )
    out = vc.finalize_dictation(
        "Hey Diapason ouvre Cursor", polish=True, llm_polish=False, use_dictionary=False
    )
    assert out["mode"] == "command"
    assert out["meta"]["wake_word"] is True
    assert out["action"]["target"] == "Cursor"


def test_finalize_bare_wake_suggests_talk(monkeypatch):
    from diapason.desktop.voice_commands import finalize_dictation

    out = finalize_dictation("Hey Diapason", polish=True, llm_polish=False, use_dictionary=False)
    assert out["mode"] == "wake"
    assert out["meta"]["suggest"] == "talk_open"


def test_listener_check_text_fires_once():
    calls: list[str] = []
    listener = WakeWordListener(
        lambda t: calls.append(t),
        cfg=WakeListenConfig(cooldown_s=0.0),
        once=True,
    )
    assert listener.check_text("Hey Diapason") is True
    assert listener.check_text("Hey Diapason") is False  # once
    assert calls == ["Hey Diapason"]


def test_listener_cooldown():
    calls: list[str] = []
    listener = WakeWordListener(
        lambda t: calls.append(t),
        cfg=WakeListenConfig(cooldown_s=10.0),
        once=False,
    )
    assert listener.check_text("Diapason") is True
    assert listener.check_text("Diapason") is False
    assert len(calls) == 1


def test_trigger_poll_route(tmp_path: Path):
    from fastapi.testclient import TestClient
    from diapason.channels.local_trigger import LocalTriggerChannel
    from diapason.server.trigger_routes import create_trigger_router

    path = tmp_path / "t.jsonl"
    ch = LocalTriggerChannel(path=path)
    ch.emit("wake", event="talk_open", source="test")

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_trigger_router())
    client = TestClient(app)
    res = client.get("/v1/triggers/poll", params={"since": 0, "path": str(path)})
    assert res.status_code == 200
    data = res.json()
    assert data["events"][0]["event"] == "talk_open"
    assert data["offset"] > 0
