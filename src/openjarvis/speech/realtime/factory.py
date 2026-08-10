"""Factory for realtime voice providers."""

from __future__ import annotations

from typing import Optional, Sequence

from openjarvis.speech.realtime.base import RealtimeVoiceSession


def create_realtime_session(
    provider: str,
    *,
    model: str = "",
    voice: str = "",
    instructions: str = "",
    language: str = "",
    api_key: Optional[str] = None,
    enable_tools: bool = True,
    max_tool_steps: int = 12,
    allowed_tools: Optional[Sequence[str]] = None,
) -> RealtimeVoiceSession:
    """Create a provider session. Raises ``ValueError`` for unknown providers."""
    name = (provider or "").strip().lower()
    common = dict(
        api_key=api_key,
        instructions=instructions,
        language=language,
        enable_tools=enable_tools,
        max_tool_steps=max_tool_steps,
        allowed_tools=allowed_tools,
    )
    if name in ("gemini", "gemini_live", "google"):
        from openjarvis.speech.realtime.gemini_live import GeminiLiveSession

        return GeminiLiveSession(
            model=model or "gemini-2.0-flash-live-001",
            voice=voice or "Zephyr",
            **common,
        )
    if name in ("openai", "openai_realtime", "gpt-realtime"):
        from openjarvis.speech.realtime.openai_realtime import OpenAIRealtimeSession

        return OpenAIRealtimeSession(
            model=model or "gpt-4o-realtime-preview",
            voice=voice or "alloy",
            **common,
        )
    raise ValueError(
        f"Unknown realtime voice provider: {provider!r} "
        "(expected 'gemini' or 'openai')"
    )


__all__ = ["create_realtime_session"]
