"""Abstract realtime voice session."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Optional

EventKind = Literal[
    "ready",
    "audio",
    "transcript",
    "interrupted",
    "error",
    "closed",
    "tool",
]


@dataclass(slots=True)
class SessionEvent:
    """Normalized event emitted by a provider session toward the UI."""

    kind: EventKind
    text: str = ""
    role: str = ""  # "user" | "assistant"
    final: bool = False
    # Un partiel REMPLACE le texte affiché au lieu de s'y ajouter. Gemini et
    # OpenAI envoient des deltas — chaque morceau prolonge le précédent. Une
    # transcription locale relit tout le tampon à chaque passe et peut donc
    # RÉVISER ce qu'elle avait compris : « est » devient « était ». Un delta
    # ne sait pas exprimer ça, et concaténer donnerait « QuelleQuelle heure ».
    replace: bool = False
    audio_b64: str = ""
    sample_rate: int = 24000
    detail: str = ""
    tool_name: str = ""
    tool_ok: bool = False
    raw: Optional[dict[str, Any]] = field(default=None, repr=False)


class RealtimeVoiceSession(ABC):
    """Provider-agnostic duplex voice session."""

    provider_id: str = ""
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000

    @abstractmethod
    async def connect(self) -> None:
        """Open the provider connection and finish setup."""

    @abstractmethod
    async def send_audio(self, pcm16: bytes) -> None:
        """Send a chunk of mono PCM16 at ``input_sample_rate``."""

    @abstractmethod
    async def send_text(self, text: str) -> None:
        """Optional text turn (debug / typed barge)."""

    @abstractmethod
    async def interrupt(self) -> None:
        """Cancel current model speech (barge-in)."""

    @abstractmethod
    def events(self) -> AsyncIterator[SessionEvent]:
        """Async iterator of normalized session events."""

    @abstractmethod
    async def close(self) -> None:
        """Tear down the provider connection."""


__all__ = ["EventKind", "RealtimeVoiceSession", "SessionEvent"]
