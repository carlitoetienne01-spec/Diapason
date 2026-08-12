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
END_OF_TURN_S = 0.6
# After this much silence the utterance is PROBABLY over, so transcription
# starts speculatively while the remaining silence confirms it. If the user
# resumes speaking the result is discarded — wasted work, never a wrong turn.
# This overlaps most of Whisper's latency with a wait that existed anyway.
SPECULATE_AFTER_S = 0.25
# Ignore blips shorter than this — a cough is not a turn.
MIN_SPEECH_S = 0.35
# While the assistant's audio is still playing on the client, the microphone
# hears the speakers. Interrupting on the ordinary speech threshold would let
# the assistant cut ITSELF off; requiring a markedly stronger signal means
# only a real voice over the top does it.
BARGE_RMS = SPEECH_RMS * 3

# Utterances that mean "stop talking" and deserve silence, not a reply.
# With barge-in the playback already stopped the moment the user spoke;
# answering "ok, j'arrête" would be exactly the noise they asked to end.
_STOP_PHRASES = re.compile(
    r"^(?:diapason[,\s]*)?"
    r"(?:arr[êe]te(?:[- ]toi)?(?:\s+de\s+parler)?|stop|tais[- ]toi|chut+"
    r"|silence|[çc]a suffit|c'?est bon)"
    r"(?:[,\s]+(?:s'?il\s+te\s+pla[îi]t|merci))?[\s.!…]*$",
    re.IGNORECASE,
)


def is_stop_phrase(text: str) -> bool:
    return bool(_STOP_PHRASES.match((text or "").strip()))

# Sentence boundary for incremental speech: synthesise as soon as a sentence
# is complete instead of waiting for the whole answer — this is what turns
# "LLM total time" into "LLM time to first sentence" in perceived latency.
_SENTENCE_END = re.compile(r"([.!?…:;]+[\s»”)]*\s+|\n+)")

# For the very first audible chunk only, a comma is also a boundary: "Oui,"
# reaching the speakers half a second before the rest of the sentence is what
# makes the exchange feel answered rather than processed.
_FIRST_CHUNK = re.compile(r"([,;]\s+)")
_FIRST_CHUNK_MIN_CHARS = 16

# Everything a voice cannot say. Emojis fed to the vocoder get read out loud
# ("visage souriant…"), which is exactly as useless as it sounds; markdown
# marks become audible asterisks. The transcript shown on screen is built
# from the SANITISED text too, so what you read is what was said.
_UNSPEAKABLE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # emoji blocks, symbols, pictographs
    "\U00002600-\U000027BF"  # misc symbols, dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicator flags
    "\u2b00-\u2bff"          # arrows/stars block used by some emoji
    "\ufe0e\ufe0f\u200d"    # variation selectors, ZWJ
    "*_`#~|<>"                 # markdown furniture
    "]+"
)


def speakable(text: str) -> str:
    """Strip what a voice cannot say; collapse the leftover whitespace.

    Returns "" when nothing pronounceable is left — an emoji-only chunk
    leaves its punctuation behind ("👍👍." → "."), and a vocoder handed a
    bare period says "point" out loud.
    """
    cleaned = _UNSPEAKABLE.sub("", text or "")
    cleaned = re.sub(r"^[\s\-•]+", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    if not re.search(r"[\w]", cleaned, re.UNICODE):
        return ""
    return cleaned

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
    model: str, system: str, tools_schema: Optional[List[dict]] = None
) -> Callable[[List[dict]], "asyncio.Queue[Any]"]:
    """Streamed chat against Ollama; the queue carries tokens and tool calls.

    Queue items: ``str`` tokens, ``("tools", [...])`` when the model asks to
    act, the ``\x00ERROR\x00`` sentinel, and ``None`` at end of stream.

    ``think`` is disabled explicitly: qwen3.5 reasons silently first, and in
    a voice conversation that silence IS the latency — measured, it swallowed
    the entire token budget before a single audible word.
    """

    def start(messages: List[dict]) -> "asyncio.Queue[Any]":
        queue: asyncio.Queue[Any] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker() -> None:
            try:
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": [{"role": "system", "content": system}]
                    + messages,
                    "stream": True,
                    "think": False,
                    "options": {"num_predict": 320},
                    # Without this Ollama unloads the model after five idle
                    # minutes, and the next turn silently pays a 6–9 s reload
                    # — the single worst "why is it slow now" in a session.
                    "keep_alive": "30m",
                }
                if tools_schema:
                    payload["tools"] = tools_schema
                request = urllib.request.Request(
                    f"{_ollama_base()}/api/chat",
                    json.dumps(payload).encode(),
                    {"Content-Type": "application/json"},
                )
                calls: List[dict] = []
                with urllib.request.urlopen(request, timeout=120) as response:
                    for line in response:
                        data = json.loads(line)
                        message = data.get("message") or {}
                        token = message.get("content", "")
                        if token:
                            loop.call_soon_threadsafe(queue.put_nowait, token)
                        calls.extend(message.get("tool_calls") or [])
                        if data.get("done"):
                            break
                if calls:
                    loop.call_soon_threadsafe(
                        queue.put_nowait, ("tools", calls)
                    )
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
        enable_tools: bool = True,  # same allow-listed tools as Gemini
        max_tool_steps: int = 12,
        allowed_tools: Optional[Sequence[str]] = None,
        stt: Optional[Callable[[bytes], str]] = None,
        llm: Optional[Callable[[List[dict]], Any]] = None,
        tts: Optional[Callable[[str], bytes]] = None,
        tool_executor: Optional[Callable[[str, dict], dict]] = None,
    ) -> None:
        self._model = model or DEFAULT_MODEL
        self._voice = voice or DEFAULT_VOICE
        self._instructions = instructions
        self._language = language
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._enable_tools = bool(enable_tools)
        self._allowed_tools = list(allowed_tools) if allowed_tools else None
        from diapason.speech.realtime.tools import VoiceToolBudget

        self._budget = VoiceToolBudget(max_tool_steps)
        self._tool_executor = tool_executor
        self._queue: asyncio.Queue[Optional[SessionEvent]] = asyncio.Queue()
        self._buffer = bytearray()
        self._speech_samples = 0
        self._silence_samples = 0
        self._in_speech = False
        self._respond_task: Optional[asyncio.Task[None]] = None
        self._warm_task: Optional[asyncio.Task[None]] = None
        # (buffered byte count, transcription task) — valid only while the
        # buffer has not grown past the snapshot it was taken from.
        self._speculative: Optional[tuple[int, asyncio.Task[str]]] = None
        # When, on OUR clock, the audio already shipped to the client will
        # finish playing. Synthesis outruns playback, so the respond task is
        # usually long done while the user is still hearing the answer — this
        # clock is what lets speech interrupt a playback with no task left to
        # cancel. That gap was exactly the reported "il ne s'arrête pas".
        self._speaking_until = 0.0
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
                    schema: List[dict] = []
                    if self._enable_tools:
                        from diapason.speech.realtime.tools import (
                            openai_tools_schema,
                        )

                        # Ollama speaks the OpenAI function format, so the
                        # schema built for OpenAI Realtime serves unchanged.
                        schema = await asyncio.to_thread(
                            openai_tools_schema, self._allowed_tools
                        )
                    self._llm = _default_llm(
                        self._model, self._system_prompt(), schema
                    )
                if self._tool_executor is None and self._enable_tools:
                    from diapason.speech.realtime.tools import (
                        execute_voice_tool,
                    )

                    self._tool_executor = (
                        lambda name, args: execute_voice_tool(
                            name, args, self._allowed_tools
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
                logger.exception("local voice warm-up failed")
                await self._queue.put(
                    SessionEvent(kind="error", detail=f"local setup: {exc}")
                )

    def _system_prompt(self) -> str:
        if self._instructions:
            return self._instructions
        try:
            from diapason.speech.realtime.oral_prompt import (
                build_live_agent_template,
            )

            base = build_live_agent_template(enable_tools=self._enable_tools)
        except Exception:  # noqa: BLE001 - a persona is not worth failing over
            base = "You are Diapason, a helpful voice assistant."
        language = self._language or "the language the user speaks"
        return (
            f"{base}\n\nAnswer in {language}. Keep answers short and spoken: "
            "one to three sentences unless asked for more. Your words are "
            "READ ALOUD by a voice synthesizer: never use emojis, emoticons, "
            "markdown, bullet points or any visual formatting — they come "
            "out as spoken garbage. Plain sentences only. Everything runs "
            "locally on the user's machine."
        )

    # -- audio ingestion and turn detection ----------------------------------

    async def send_audio(self, pcm16: bytes) -> None:
        if self._closed or not pcm16:
            return
        import time as _time

        rms = _rms(pcm16)
        playback_live = _time.monotonic() < self._speaking_until
        # Over live playback the microphone hears the speakers, so only a
        # markedly stronger signal counts as the user. Below that, the frame
        # is neither speech nor silence: it is the assistant's own echo, and
        # buffering it would transcribe the assistant back at itself.
        threshold = BARGE_RMS if playback_live else SPEECH_RMS
        speaking_now = rms >= threshold
        if playback_live and not speaking_now:
            return

        if speaking_now:
            # Barge-in, both halves. Cancelling the respond task stops what
            # is still being generated; the "interrupted" event makes the
            # client flush what was ALREADY delivered to its playback queue.
            # Synthesis outruns playback, so most of the time only the second
            # half has anything left to stop.
            interrupted = False
            if self._respond_task is not None and not self._respond_task.done():
                self._respond_task.cancel()
                interrupted = True
            if playback_live:
                self._speaking_until = 0.0
                interrupted = True
            if interrupted:
                await self._queue.put(SessionEvent(kind="interrupted"))
            # Any speculative transcription was of an utterance that turned
            # out not to be finished; it no longer describes the buffer.
            self._speculative = None
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

        long_enough = self._speech_samples >= int(MIN_SPEECH_S * INPUT_RATE)
        if (
            self._speculative is None
            and long_enough
            and self._stt is not None
            and self._silence_samples >= int(SPECULATE_AFTER_S * INPUT_RATE)
        ):
            snapshot = bytes(self._buffer)
            self._speculative = (
                len(self._buffer),
                asyncio.get_running_loop().create_task(
                    asyncio.to_thread(self._stt, snapshot)
                ),
            )

        if self._silence_samples >= int(END_OF_TURN_S * INPUT_RATE):
            utterance = bytes(self._buffer)
            had_speech = self._speech_samples >= int(MIN_SPEECH_S * INPUT_RATE)
            # Hand over the speculative result only if it covers everything
            # heard: trailing silence grows the buffer, so equality is on the
            # snapshot boundary having remained the end of speech.
            speculative = self._speculative
            self._speculative = None
            self._buffer.clear()
            self._speech_samples = 0
            self._silence_samples = 0
            self._in_speech = False
            if had_speech:
                early = speculative[1] if speculative is not None else None
                self._respond_task = asyncio.get_running_loop().create_task(
                    self._respond(utterance, early_stt=early)
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

    async def _respond(
        self,
        utterance: bytes,
        early_stt: Optional["asyncio.Task[str]"] = None,
    ) -> None:
        try:
            await self._wait_warm()
            assert self._stt is not None
            if early_stt is not None:
                # Transcription began during the end-of-turn silence; by now
                # it is usually already done, and the wait it overlapped was
                # dead time either way.
                text = await early_stt
            else:
                text = await asyncio.to_thread(self._stt, utterance)
            if not text:
                return
            await self._queue.put(
                SessionEvent(kind="transcript", role="user", text=text, final=True)
            )
            if is_stop_phrase(text):
                # They asked for quiet. The barge-in already silenced the
                # playback the moment they spoke; generating "d'accord,
                # j'arrête" would be one more sentence of exactly the noise
                # they asked to end.
                return
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

            # The per-turn transcript: history plus whatever tool exchanges
            # this turn produces. Tool messages stay HERE and never enter the
            # long-term history — a session that opened three apps would
            # otherwise drag those payloads through every later turn.
            messages = list(self._history)
            spoken: List[str] = []
            # Bounded by the budget plus the final text-only round, so a model
            # that asks for tools forever cannot loop us forever.
            for _round in range(self._budget.max_steps + 1):
                tokens = self._llm(list(messages))
                pending = ""
                tool_calls: List[dict] = []
                while True:
                    item = await tokens.get()
                    if item is None:
                        break
                    if isinstance(item, tuple) and item[0] == "tools":
                        tool_calls.extend(item[1])
                        continue
                    if item.startswith("\x00ERROR\x00"):
                        raise RuntimeError(item.split("\x00", 2)[2])
                    pending += item
                    pending = await self._speak_complete_sentences(
                        pending, spoken
                    )
                if pending.strip():
                    await self._speak_sentence(pending.strip(), spoken)
                if not tool_calls or not self._enable_tools:
                    break
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": tool_calls,
                    }
                )
                for call in tool_calls:
                    messages.append(await self._run_tool(call))

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

    async def _run_tool(self, call: dict) -> dict:
        """Execute one tool call and shape the result for the transcript.

        The result goes two ways at once: a "tool" event so the panel shows
        what just happened, and a role="tool" message so the model can build
        its answer on what the tool actually returned.
        """
        function = call.get("function") or {}
        name = str(function.get("name") or "")
        raw_args = function.get("arguments") or {}
        args = raw_args if isinstance(raw_args, dict) else {}
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except ValueError:
                args = {}

        if not self._budget.allow():
            result = {
                "ok": False,
                "error": f"Voice tool budget exceeded ({self._budget.max_steps})",
            }
        elif self._tool_executor is None:
            result = {"ok": False, "error": "tools unavailable"}
        else:
            self._budget.consume()
            result = await asyncio.to_thread(self._tool_executor, name, args)

        await self._queue.put(
            SessionEvent(
                kind="tool",
                tool_name=name,
                tool_ok=bool(result.get("ok")),
                detail=str(result.get("error") or "")[:200],
            )
        )
        return {
            "role": "tool",
            "tool_name": name,
            "content": json.dumps(result, ensure_ascii=False, default=str),
        }

    async def _speak_complete_sentences(
        self, pending: str, spoken: List[str]
    ) -> str:
        while True:
            match = _SENTENCE_END.search(pending)
            if match is None and not spoken:
                # Nothing audible yet: a comma will do. The half-second this
                # buys on the opening syllables is worth more than anywhere
                # else in the pipeline, because it is the half-second the
                # user experiences as "it heard me".
                candidate = _FIRST_CHUNK.search(pending)
                if candidate is not None and candidate.end() >= _FIRST_CHUNK_MIN_CHARS:
                    match = candidate
            if match is None:
                return pending
            sentence = pending[: match.end()].strip()
            pending = pending[match.end() :]
            if sentence:
                await self._speak_sentence(sentence, spoken)

    async def _speak_sentence(self, sentence: str, spoken: List[str]) -> None:
        assert self._tts is not None
        sentence = speakable(sentence)
        if not sentence:
            # A chunk that was all emoji: nothing to say, nothing to record.
            return
        pcm = await asyncio.to_thread(self._tts, sentence)
        spoken.append(sentence)
        if pcm:
            import time as _time

            duration = len(pcm) / 2 / OUTPUT_RATE
            now = _time.monotonic()
            # Chunks queue up on the client, so each one starts when the
            # previous ends — never before now.
            self._speaking_until = max(now, self._speaking_until) + duration
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
