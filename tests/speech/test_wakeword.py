"""Tests for wake-word phrase gate and listener."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from openjarvis.speech.wake_phrases import has_wake_word, strip_wake_word
from openjarvis.speech.wakeword import WakeListenConfig, WakeWordListener


def test_has_wake_word_en_fr():
    assert has_wake_word("Hey Jarvis")
    assert has_wake_word("jarvis")
    assert has_wake_word("Dis Jarvis, ouvre Cursor")
    assert has_wake_word("ok jarvis what's up")
    assert has_wake_word("JARVIS")


def test_has_wake_word_rejects_mid_sentence():
    assert not has_wake_word("le jarvis de iron man")
    assert not has_wake_word("I like jarvis movies")
    assert not has_wake_word("")


def test_strip_wake_word():
    assert strip_wake_word("Jarvis, ouvre YouTube") == "ouvre YouTube"
    assert "Cursor" in strip_wake_word("Hey Jarvis ouvre Cursor")
    assert strip_wake_word("Dis Jarvis") == ""


def test_finalize_wake_command(monkeypatch):
    from openjarvis.desktop import voice_commands as vc

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
        "Hey Jarvis ouvre Cursor", polish=True, llm_polish=False, use_dictionary=False
    )
    assert out["mode"] == "command"
    assert out["meta"]["wake_word"] is True
    assert out["action"]["target"] == "Cursor"


def test_finalize_bare_wake_suggests_talk(monkeypatch):
    from openjarvis.desktop.voice_commands import finalize_dictation

    out = finalize_dictation("Hey Jarvis", polish=True, llm_polish=False, use_dictionary=False)
    assert out["mode"] == "wake"
    assert out["meta"]["suggest"] == "talk_open"


def test_listener_check_text_fires_once():
    calls: list[str] = []
    listener = WakeWordListener(
        lambda t: calls.append(t),
        cfg=WakeListenConfig(cooldown_s=0.0),
        once=True,
    )
    assert listener.check_text("Hey Jarvis") is True
    assert listener.check_text("Hey Jarvis") is False  # once
    assert calls == ["Hey Jarvis"]


def test_listener_cooldown():
    calls: list[str] = []
    listener = WakeWordListener(
        lambda t: calls.append(t),
        cfg=WakeListenConfig(cooldown_s=10.0),
        once=False,
    )
    assert listener.check_text("Jarvis") is True
    assert listener.check_text("Jarvis") is False
    assert len(calls) == 1


def test_trigger_poll_route(tmp_path: Path):
    from fastapi.testclient import TestClient
    from openjarvis.channels.local_trigger import LocalTriggerChannel
    from openjarvis.server.trigger_routes import create_trigger_router

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
