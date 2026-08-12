"""The tool budget is per-TURN on every provider, not a session ration."""

from __future__ import annotations

from diapason.speech.realtime.tools import VoiceToolBudget


def test_reset_rearms_the_budget():
    b = VoiceToolBudget(max_steps=2)
    b.consume(), b.consume()
    assert not b.allow()
    b.reset()
    assert b.allow()


def test_gemini_user_speech_rearms_the_budget():
    from diapason.speech.realtime.gemini_live import GeminiLiveSession

    session = GeminiLiveSession.__new__(GeminiLiveSession)
    session._budget = VoiceToolBudget(max_steps=1)
    session._budget.consume()
    assert not session._budget.allow()
    # turnComplete is the boundary a real session actually delivers — the
    # setup never opts in to inputTranscription.
    session._parse_server_message({"serverContent": {"turnComplete": True}})
    assert session._budget.allow()


def test_openai_user_speech_rearms_the_budget():
    from diapason.speech.realtime.openai_realtime import OpenAIRealtimeSession

    session = OpenAIRealtimeSession.__new__(OpenAIRealtimeSession)
    session._budget = VoiceToolBudget(max_steps=1)
    session._budget.consume()
    assert not session._budget.allow()
    session._parse_event({"type": "input_audio_buffer.speech_started"})
    assert session._budget.allow()
