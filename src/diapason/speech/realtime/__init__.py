"""Realtime duplex voice sessions (Gemini Live / OpenAI Realtime)."""

from diapason.speech.realtime.base import RealtimeVoiceSession, SessionEvent
from diapason.speech.realtime.factory import create_realtime_session

__all__ = [
    "RealtimeVoiceSession",
    "SessionEvent",
    "create_realtime_session",
]
