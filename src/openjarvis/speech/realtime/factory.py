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
    """Create a provider session. Raises ``ValueError`` for unknown providers.

    Raises :class:`LocalOnlyError` under ``[privacy] local_only``: every
    realtime provider is remote, so there is no honest degradation here.
    """
    # The gravest path in the codebase: a realtime session streams RAW
    # MICROPHONE PCM to Gemini or OpenAI continuously — not a finished
    # sentence, everything the microphone hears for as long as the socket is
    # open. And the provider is chosen by the CLIENT (a query parameter or the
    # `start` frame in server/voice_live_routes.py), so a guard placed on the
    # caller's default would be bypassed by anyone passing ?provider=openai.
    #
    # The guard therefore sits on the factory, which no provider can avoid,
    # and fires before the session object exists — hence before any API key is
    # read from the environment by a provider constructor.
    from openjarvis.core.local_mode import REFUSAL_HINT, LocalOnlyError, local_only

    if local_only():
        raise LocalOnlyError(
            "Realtime voice needs a remote provider and there is no local one, "
            f"so the microphone stream was refused. {REFUSAL_HINT}"
        )

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
