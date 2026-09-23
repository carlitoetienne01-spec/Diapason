"""Unit tests for realtime voice helpers (no live network)."""

from __future__ import annotations

import base64

import pytest

from diapason.core.config import DiapasonConfig, SpeechConfig, VoiceRealtimeConfig
from diapason.speech.realtime.base import SessionEvent
from diapason.speech.realtime.bridge import event_to_client_json
from diapason.speech.realtime.factory import create_realtime_session
from diapason.speech.realtime.pcm import b64_to_pcm16, pcm16_to_b64, resample_pcm16


def test_speech_config_has_realtime_defaults():
    cfg = SpeechConfig()
    assert isinstance(cfg.realtime, VoiceRealtimeConfig)
    assert cfg.realtime.enabled is True
    # See test_config.py: local is the shipped default.
    assert cfg.realtime.provider == "local"


def test_jarvis_config_nested_realtime():
    cfg = DiapasonConfig()
    assert cfg.speech.realtime.provider == "local"


def test_pcm_roundtrip():
    raw = b"\x00\x01\xff\xfe" * 8
    assert b64_to_pcm16(pcm16_to_b64(raw)) == raw


def test_resample_same_rate_noop():
    raw = b"\x00\x00" * 16
    assert resample_pcm16(raw, 16000, 16000) == raw


def test_factory_unknown_provider():
    with pytest.raises(ValueError, match="Unknown realtime"):
        create_realtime_session("bogus")


def test_factory_gemini_and_openai():
    g = create_realtime_session("gemini", voice="Zephyr")
    assert g.provider_id == "gemini"
    assert g.input_sample_rate == 16000
    o = create_realtime_session("openai", voice="alloy")
    assert o.provider_id == "openai"
    assert o.input_sample_rate == 24000


def test_oral_prompt_contains_clarification_and_brevity():
    from diapason.speech.realtime.oral_prompt import build_live_agent_template

    text = build_live_agent_template(enable_tools=True)
    # Durcie le 24 août 2026 : une phrase suffit presque toujours, jamais
    # plus de deux — « je déteste les phrases longues », mot pour mot.
    assert "NEVER more than two" in text
    assert "ONE sentence" in text
    assert "clarif" in text.lower()
    assert "calendar_query" in text
    assert "find_files" in text


def test_default_voice_tools_include_jarvis_parity():
    import diapason.tools.desktop_tools  # noqa: F401
    import diapason.tools.voice_mac_tools  # noqa: F401
    import diapason.tools.web_search  # noqa: F401
    from diapason.speech.realtime.tools import (
        DEFAULT_VOICE_TOOL_IDS,
        list_voice_tool_ids,
    )

    for tid in (
        "open_anything",
        "calendar_query",
        "spotify_play",
        "web_search",
        "find_files",
        "mail_compose",
        "messages_compose",
        "screen_describe",
        "screen_share_start",
        "screen_share_stop",
        "screen_share_status",
    ):
        assert tid in DEFAULT_VOICE_TOOL_IDS
    ids = list_voice_tool_ids()
    assert "open_anything" in ids
    assert "calendar_query" in ids
    assert "spotify_play" in ids
    assert "find_files" in ids
    assert "web_search" in ids
    assert "mail_compose" in ids
    assert "messages_compose" in ids
    assert "screen_describe" in ids
    assert "screen_share_start" in ids
    assert "screen_share_stop" in ids


def test_event_to_client_json():
    assert event_to_client_json(SessionEvent(kind="ready")) == {"type": "ready"}
    audio = event_to_client_json(
        SessionEvent(kind="audio", audio_b64="abc", sample_rate=24000)
    )
    assert audio["type"] == "audio"
    assert audio["data"] == "abc"
    tx = event_to_client_json(
        SessionEvent(kind="transcript", role="user", text="hi", final=True)
    )
    assert tx == {
        "type": "transcript",
        "role": "user",
        "text": "hi",
        # `replace` distingue un partiel qui REMPLACE le texte affiché d'un
        # delta qui s'y ajoute. Faux par défaut : les fournisseurs distants
        # envoient des deltas, et cette voie doit rester intacte.
        "replace": False,
        "final": True,
    }
    tool = event_to_client_json(
        SessionEvent(kind="tool", tool_name="focus_app", tool_ok=True, detail="Focused")
    )
    assert tool == {
        "type": "tool",
        "name": "focus_app",
        "ok": True,
        "detail": "Focused",
    }
    # Le niveau de vérification du tour (22/09/2026) : les clés restent celles
    # du chat, en anglais camelCase — le client les lit avec le même
    # `lireVerification`, qui ne connaît qu'elles. Un `level` en français y
    # entrerait comme `undefined`, en silence.
    verif = event_to_client_json(
        SessionEvent(
            kind="verification",
            verification={"level": "verified", "searchTried": True},
        )
    )
    assert verif == {"type": "verification", "level": "verified", "searchTried": True}
    assert event_to_client_json(SessionEvent(kind="verification")) == {
        "type": "verification"
    }, "un événement sans niveau ne fabrique pas de clés vides"
    # 22/09/2026 : une recherche à zéro résultat arrivait au panneau vocal en
    # ok=true, detail="" — indiscernable d'une recherche fructueuse.
    vide = event_to_client_json(
        SessionEvent(
            kind="tool",
            tool_name="web_search",
            tool_ok=True,
            tool_details={"engine": "brave/news", "numResults": 0},
        )
    )
    assert vide == {
        "type": "tool",
        "name": "web_search",
        "ok": True,
        "detail": "",
        "engine": "brave/news",
        "numResults": 0,
    }, "le zéro traverse : c'est le cas pour lequel ces champs existent"
    assert event_to_client_json(
        SessionEvent(kind="tool", tool_name="focus_app", tool_ok=True)
    ) == {"type": "tool", "name": "focus_app", "ok": True, "detail": ""}, (
        "un outil qui ne cherche pas n'ajoute aucune clé"
    )


def test_voice_tool_budget():
    from diapason.speech.realtime.tools import VoiceToolBudget

    b = VoiceToolBudget(2)
    assert b.allow()
    b.consume()
    b.consume()
    assert not b.allow()


def test_voice_tool_allowlist_and_execute_unknown():
    from diapason.speech.realtime.tools import (
        execute_voice_tool,
        gemini_function_declarations,
        list_voice_tool_ids,
    )

    ids = list_voice_tool_ids()
    assert "open_uri" in ids or ids == []  # desktop tools may be registered
    decls = gemini_function_declarations()
    assert isinstance(decls, list)
    denied = execute_voice_tool("rm_rf_everything", {})
    assert denied["ok"] is False
    assert "not allowed" in denied["error"].lower()


def test_openai_tools_schema_shape():
    from diapason.speech.realtime.tools import openai_tools_schema

    tools = openai_tools_schema()
    for t in tools:
        assert t.get("type") == "function"
        assert "function" in t
        assert "name" in t["function"]


def test_gemini_parse_audio_part():
    from diapason.speech.realtime.gemini_live import GeminiLiveSession

    session = GeminiLiveSession(api_key="test")
    payload = {
        "serverContent": {
            "modelTurn": {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "audio/pcm",
                            "data": base64.b64encode(b"\x01\x02").decode(),
                        }
                    }
                ]
            }
        }
    }
    events = session._parse_server_message(payload)
    assert any(e.kind == "audio" for e in events)


def test_openai_parse_audio_delta():
    from diapason.speech.realtime.openai_realtime import OpenAIRealtimeSession

    session = OpenAIRealtimeSession(api_key="test")
    events = session._parse_event({"type": "response.audio.delta", "delta": "qq=="})
    assert len(events) == 1
    assert events[0].kind == "audio"
    assert events[0].audio_b64 == "qq=="


class TestLocalProviderGuard:
    """local_only must let the local provider through and still block remote.

    The guard's original message said realtime voice had "no local one" —
    that is no longer true, and the guard must encode the new reality: the
    danger was never realtime voice, it was the microphone leaving the
    machine.
    """

    def test_local_passes_under_local_only(self, monkeypatch):
        import diapason.core.local_mode as local_mode

        monkeypatch.setattr(local_mode, "local_only", lambda: True)
        from diapason.speech.realtime.factory import create_realtime_session

        session = create_realtime_session("local")
        assert session.provider_id == "local"

    def test_remote_still_refused_under_local_only(self, monkeypatch):
        import diapason.core.local_mode as local_mode

        monkeypatch.setattr(local_mode, "local_only", lambda: True)
        import pytest as _pytest

        from diapason.core.local_mode import LocalOnlyError
        from diapason.speech.realtime.factory import create_realtime_session

        with _pytest.raises(LocalOnlyError):
            create_realtime_session("gemini")

    def test_local_session_needs_no_api_key(self):
        from diapason.speech.realtime.local_voice import LocalVoiceSession

        session = LocalVoiceSession(
            stt=lambda _a: "", llm=lambda _m: None, tts=lambda _t: b""
        )
        assert session.provider_id == "local"
