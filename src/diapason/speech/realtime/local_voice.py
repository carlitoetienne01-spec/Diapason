"""Fully local realtime voice: Whisper → Ollama → Kokoro, nothing leaves.

The other two providers stream the raw microphone to Google or OpenAI; this
one keeps the whole loop on the machine. It is honest about what that buys
and what it costs: turn-based with barge-in rather than full duplex, first
spoken word ~1.5–2.5 s after the user's last syllable (measured: STT ~1 s for
a 4 s French utterance, qwen3.5:9b first token 0.47 s warm, Kokoro RTF 0.28)
— against ~0.5 s for Gemini Live. In exchange: no key, no account, and the
factory's local-only guard can finally let voice through instead of refusing
it wholesale.

Structure: ``send_audio`` only buffers and detects turn boundaries; the
response pipeline (transcribe → stream tokens → speak sentence by sentence)
runs as a cancellable task, because barge-in is nothing more than cancelling
it. The three stages are injectable callables so the turn logic is testable
without a microphone, a model server or a vocoder.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import urllib.request
from typing import Any, AsyncIterator, Callable, List, Optional, Sequence

from diapason.speech.realtime.base import RealtimeVoiceSession, SessionEvent

logger = logging.getLogger(__name__)

INPUT_RATE = 16_000
OUTPUT_RATE = 24_000

# End-of-turn detection on raw RMS of int16/32768 samples. Ordinary speech
# sits near 0.01–0.05 on this scale; an untouched microphone well below.
SPEECH_RMS = 0.008
# How long a pause ends the turn. Shorter clips sentences mid-breath; longer
# makes every exchange feel laggy. 700 ms is where read-aloud French pauses
# land between sentences but not between words.
END_OF_TURN_S = 0.7
# Ignore blips shorter than this — a cough is not a turn.
MIN_SPEECH_S = 0.35

# Sentence boundary for incremental speech: synthesise as soon as a sentence
# is complete instead of waiting for the whole answer — this is what turns
# "LLM total time" into "LLM time to first sentence" in perceived latency.
_SENTENCE_END = re.compile(r"([.!?…:;]+[\s»”)]*\s+|\n+)")

DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_VOICE = "ff_siwis"

# Loaded once per process, not per session: Kokoro takes ~22 s to build its
# pipeline and Whisper several seconds — a per-session cost would make every
# conversation open with half a minute of silence.
_SHARED: dict[str, Any] = {}
_SHARED_LOCK = asyncio.Lock()


def _ollama_base() -> str:
    from diapason.core.env import get as env_get

    return (env_get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")


def ollama_reachable(timeout_s: float = 1.5) -> bool:
    """True when the local model server answers. Never raises."""
    try:
        with urllib.request.urlopen(
            f"{_ollama_base()}/api/tags", timeout=timeout_s
        ) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - unreachable is a normal state
        return False


def _default_stt() -> Callable[[bytes], str]:
    """Whisper, shared across sessions, French pinned via the user's config."""
    from diapason.core.config import load_config
    from diapason.speech.faster_whisper import FasterWhisperBackend

    backend = _SHARED.get("stt")
    if backend is None:
        config = load_config()
        backend = FasterWhisperBackend(
            model_size=str(getattr(config.speech, "model", "") or "small"),
            language=str(getattr(config.speech, "language", "") or ""),
        )
        backend.preload()
        _SHARED["stt"] = backend

    def transcribe(pcm16: bytes) -> str:
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(INPUT_RATE)
            wav.writeframes(pcm16)
        result = backend.transcribe(buf.getvalue(), format="wav")
        return (getattr(result, "text", "") or "").strip()

    return transcribe


def _default_tts(voice: str) -> Callable[[str], bytes]:
    """Kokoro, shared across sessions. Returns PCM16 @ 24 kHz."""
    pipeline = _SHARED.get("tts")
    if pipeline is None:
        from kokoro import KPipeline

        pipeline = KPipeline(lang_code="f")
        _SHARED["tts"] = pipeline

    def speak(text: str) -> bytes:
        import numpy as np

        chunks = [audio for _, _, audio in pipeline(text, voice=voice)]
        if not chunks:
            return b""
        samples = np.concatenate(chunks)
        return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    return speak


def _default_llm(
    model: str, system: str
) -> Callable[[List[dict]], "asyncio.Queue[Optional[str]]"]:
    """Streamed chat against Ollama, tokens delivered through a queue.

    ``think`` is disabled explicitly: qwen3.5 reasons silently first, and in
    a voice conversation that silence IS the latency — measured, it swallowed
    the entire token budget before a single audible word.
    """

    def start(messages: List[dict]) -> "asyncio.Queue[Optional[str]]":
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker() -> None:
            try:
                body = json.dumps(
                    {
                        "model": model,
                        "messages": [{"role": "system", "content": system}]
                        + messages,
                        "stream": True,
                        "think": False,
                        "options": {"num_predict": 320},
                    }
                ).encode()
                request = urllib.request.Request(
                    f"{_ollama_base()}/api/chat",
                    body,
                    {"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    for line in response:
                        data = json.loads(line)
                        token = (data.get("message") or {}).get("content", "")
                        if token:
                            loop.call_soon_threadsafe(queue.put_nowait, token)
                        if data.get("done"):
                            break
            except Exception as exc:  # noqa: BLE001 - surfaced as an event
                logger.debug("local LLM stream failed", exc_info=True)
                loop.call_soon_threadsafe(
                    queue.put_nowait, f"\x00ERROR\x00{exc}"
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, worker)
        return queue

    return start


class LocalVoiceSession(RealtimeVoiceSession):
    """Turn-based local voice with barge-in, behind the realtime contract."""

    provider_id = "local"
    input_sample_rate = INPUT_RATE
    output_sample_rate = OUTPUT_RATE

    def __init__(
        self,
        *,
        model: str = "",
        voice: str = "",
        instructions: str = "",
        language: str = "",
        api_key: Optional[str] = None,  # accepted, unused: nothing to unlock
        enable_tools: bool = True,  # v1 speaks; tools are the next step
        max_tool_steps: int = 12,
        allowed_tools: Optional[Sequence[str]] = None,
        stt: Optional[Callable[[bytes], str]] = None,
        llm: Optional[Callable[[List[dict]], Any]] = None,
        tts: Optional[Callable[[str], bytes]] = None,
    ) -> None:
        self._model = model or DEFAULT_MODEL
        self._voice = voice or DEFAULT_VOICE
        self._instructions = instructions
        self._language = language
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._queue: asyncio.Queue[Optional[SessionEvent]] = asyncio.Queue()
        self._buffer = bytearray()
        self._speech_samples = 0
        self._silence_samples = 0
        self._in_speech = False
        self._respond_task: Optional[asyncio.Task[None]] = None
        self._warm_task: Optional[asyncio.Task[None]] = None
        self._history: List[dict] = []
        self._closed = False

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> None:
        if not ollama_reachable():
            raise RuntimeError(
                "Local voice needs Ollama running (start the Ollama app, "
                "or `ollama serve`)."
            )
        # Ready goes out immediately; the heavy models load under the shared
        # lock in the background. The first reply of the first session may
        # wait for them — every later one finds them warm.
        await self._queue.put(SessionEvent(kind="ready"))
        self._warm_task = asyncio.get_running_loop().create_task(self._warm())

    async def _warm(self) -> None:
        async with _SHARED_LOCK:
            try:
                if self._stt is None:
                    self._stt = await asyncio.to_thread(_default_stt)
                if self._tts is None:
                    self._tts = await asyncio.to_thread(
                        _default_tts, self._voice
                    )
                if self._llm is None:
                    self._llm = _default_llm(self._model, self._system_prompt())
            except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
                logger.exception("local voice warm-up failed")
                await self._queue.put(
                    SessionEvent(kind="error", detail=f"local setup: {exc}")
                )

    def _system_prompt(self) -> str:
        if self._instructions:
            return self._instructions
        try:
            from diapason.speech.realtime.oral_prompt import ORAL_VOICE_RULES

            base = str(ORAL_VOICE_RULES)
        except Exception:  # noqa: BLE001 - a persona is not worth failing over
            base = "You are Diapason, a helpful voice assistant."
        language = self._language or "the language the user speaks"
        return (
            f"{base}\n\nAnswer in {language}. Keep answers short and spoken: "
            "one to three sentences unless asked for more. Everything runs "
            "locally on the user's machine."
        )

    # -- audio ingestion and turn detection ----------------------------------

    async def send_audio(self, pcm16: bytes) -> None:
        if self._closed or not pcm16:
            return
        rms = _rms(pcm16)
        speaking_now = rms >= SPEECH_RMS

        if speaking_now:
            # Barge-in: the user talking over the assistant cancels the
            # answer. That single cancellation is the whole feature.
            if self._respond_task is not None and not self._respond_task.done():
                self._respond_task.cancel()
                await self._queue.put(SessionEvent(kind="interrupted"))
            self._in_speech = True
            self._silence_samples = 0
            self._speech_samples += len(pcm16) // 2
            self._buffer.extend(pcm16)
            return

        if not self._in_speech:
            # Leading silence carries no information; buffering it would only
            # lengthen the clip Whisper has to chew through.
            return

        self._buffer.extend(pcm16)
        self._silence_samples += len(pcm16) // 2
        if self._silence_samples >= int(END_OF_TURN_S * INPUT_RATE):
            utterance = bytes(self._buffer)
            had_speech = self._speech_samples >= int(MIN_SPEECH_S * INPUT_RATE)
            self._buffer.clear()
            self._speech_samples = 0
            self._silence_samples = 0
            self._in_speech = False
            if had_speech:
                self._respond_task = asyncio.get_running_loop().create_task(
                    self._respond(utterance)
                )

    async def send_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self._closed:
            return
        if self._respond_task is not None and not self._respond_task.done():
            self._respond_task.cancel()
        self._respond_task = asyncio.get_running_loop().create_task(
            self._respond_to_text(text)
        )

    async def interrupt(self) -> None:
        if self._respond_task is not None and not self._respond_task.done():
            self._respond_task.cancel()
            await self._queue.put(SessionEvent(kind="interrupted"))

    # -- the response pipeline ----------------------------------------------

    async def _respond(self, utterance: bytes) -> None:
        try:
            await self._wait_warm()
            assert self._stt is not None
            text = await asyncio.to_thread(self._stt, utterance)
            if not text:
                return
            await self._queue.put(
                SessionEvent(kind="transcript", role="user", text=text, final=True)
            )
            await self._respond_to_text(text, already_queued=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the UI must hear about it
            logger.exception("local voice turn failed")
            await self._queue.put(SessionEvent(kind="error", detail=str(exc)))

    async def _respond_to_text(
        self, text: str, *, already_queued: bool = False
    ) -> None:
        try:
            await self._wait_warm()
            assert self._llm is not None and self._tts is not None
            if not already_queued:
                await self._queue.put(
                    SessionEvent(
                        kind="transcript", role="user", text=text, final=True
                    )
                )
            self._history.append({"role": "user", "content": text})
            # A cap on history keeps a long session from slowly pushing the
            # first-token latency past conversational.
            del self._history[:-16]

            tokens = self._llm(list(self._history))
            spoken: List[str] = []
            pending = ""
            while True:
                token = await tokens.get()
                if token is None:
                    break
                if token.startswith("\x00ERROR\x00"):
                    raise RuntimeError(token.split("\x00", 2)[2])
                pending += token
                pending = await self._speak_complete_sentences(pending, spoken)

            if pending.strip():
                await self._speak_sentence(pending.strip(), spoken)

            answer = " ".join(spoken).strip()
            if answer:
                self._history.append({"role": "assistant", "content": answer})
                # Cap again here: trimming only before the user turn leaves
                # the list one entry over after this append, and it drifts.
                del self._history[:-16]
                await self._queue.put(
                    SessionEvent(
                        kind="transcript",
                        role="assistant",
                        text=answer,
                        final=True,
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("local voice response failed")
            await self._queue.put(SessionEvent(kind="error", detail=str(exc)))

    async def _speak_complete_sentences(
        self, pending: str, spoken: List[str]
    ) -> str:
        while True:
            match = _SENTENCE_END.search(pending)
            if match is None:
                return pending
            sentence = pending[: match.end()].strip()
            pending = pending[match.end() :]
            if sentence:
                await self._speak_sentence(sentence, spoken)

    async def _speak_sentence(self, sentence: str, spoken: List[str]) -> None:
        assert self._tts is not None
        pcm = await asyncio.to_thread(self._tts, sentence)
        spoken.append(sentence)
        if pcm:
            await self._queue.put(
                SessionEvent(
                    kind="audio",
                    audio_b64=base64.b64encode(pcm).decode("ascii"),
                    sample_rate=OUTPUT_RATE,
                )
            )

    async def _wait_warm(self) -> None:
        # Await the warm-up TASK, not the lock: between connect() returning
        # and the task first running, the lock is free — a caller racing
        # through it would find the stages still None. Awaiting a finished
        # task is a no-op, so this costs nothing once warm.
        if self._warm_task is not None:
            await asyncio.shield(self._warm_task)

    # -- plumbing ------------------------------------------------------------

    async def events(self) -> AsyncIterator[SessionEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._respond_task is not None and not self._respond_task.done():
            self._respond_task.cancel()
        await self._queue.put(SessionEvent(kind="closed"))
        await self._queue.put(None)


def _rms(pcm16: bytes) -> float:
    import array
    import math

    samples = array.array("h")
    samples.frombytes(pcm16[: len(pcm16) - (len(pcm16) % 2)])
    if not samples:
        return 0.0
    total = 0.0
    for value in samples:
        total += (value / 32768.0) ** 2
    return math.sqrt(total / len(samples))


__all__ = ["LocalVoiceSession", "ollama_reachable"]
