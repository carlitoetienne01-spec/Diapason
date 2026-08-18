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
import importlib.util
import json
import logging
import re
import shutil
import time
import urllib.error
import urllib.request
from typing import Any, AsyncIterator, Callable, List, Optional, Sequence

from diapason.speech.realtime.base import RealtimeVoiceSession, SessionEvent

logger = logging.getLogger(__name__)

INPUT_RATE = 16_000
OUTPUT_RATE = 24_000

# End-of-turn detection on raw RMS of int16/32768 samples. Ordinary speech
# sits near 0.01–0.05 on this scale; an untouched microphone well below.
SPEECH_RMS = 0.008

# Word onsets (soft vowels, fricatives) sit BELOW the speech threshold: a
# gate that only starts buffering once RMS crosses it amputates the first
# syllable of every utterance — "App Store" reached Whisper as "…Store".
# Keep a rolling window of the most recent sub-threshold audio and prepend
# it when speech starts, exactly like hardware VADs do.
PRE_ROLL_S = 0.4
# How long a pause ends the turn. Shorter clips sentences mid-breath; longer
# makes every exchange feel laggy. 700 ms is where read-aloud French pauses
# land between sentences but not between words.
END_OF_TURN_S = 0.8
# After this much silence the utterance is PROBABLY over, so transcription
# starts speculatively while the remaining silence confirms it. If the user
# resumes speaking the result is discarded — wasted work, never a wrong turn.
# This overlaps most of Whisper's latency with a wait that existed anyway.
SPECULATE_AFTER_S = 0.25
# Nouvelle parole accumulée avant de retenter une transcription partielle.
# Assez court pour que les mots apparaissent pendant qu'on parle, assez long
# pour que faster-whisper ait le temps de finir la précédente : chaque passe
# relit tout le tampon depuis le début, donc les lancer plus souvent ne rend
# pas l'affichage plus vif, seulement la machine plus chaude.
PARTIAL_EVERY_S = 0.7
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
    "\U0001f000-\U0001faff"  # emoji blocks, symbols, pictographs
    "\U00002600-\U000027bf"  # misc symbols, dingbats
    "\U0001f1e6-\U0001f1ff"  # regional indicator flags
    "\u2b00-\u2bff"  # arrows/stars block used by some emoji
    "\ufe0e\ufe0f\u200d"  # variation selectors, ZWJ
    "*_`#~|<>"  # markdown furniture
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


_FRENCH_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_FRENCH_MONTHS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def french_now(now=None) -> str:
    """The machine's local date and time, spelled out in French.

    Hand-rolled rather than strftime with a locale: setlocale is process-wide
    state and this runs inside a server thread pool. Injected into the system
    prompt at every turn — a model has no clock, and "quelle heure est-il"
    answered with "je ne peux pas lire l'heure" was a reported failure, on a
    machine that obviously knows.
    """
    import datetime

    if now is None:
        now = datetime.datetime.now()
    day = _FRENCH_DAYS[now.weekday()]
    month = _FRENCH_MONTHS[now.month - 1]
    return f"{day} {now.day} {month} {now.year}, {now.hour} h {now.minute:02d}"


def _ollama_base() -> str:
    from diapason.core.env import get as env_get

    return (env_get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")


def ollama_reachable(timeout_s: float = 1.5) -> bool:
    """True when the local model server answers. Never raises."""
    try:
        from diapason.core.local_mode import assert_may_leave

        assert_may_leave("the Ollama health request", destination=_ollama_base())
        with urllib.request.urlopen(
            f"{_ollama_base()}/api/tags", timeout=timeout_s
        ) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - unreachable is a normal state
        return False


def local_voice_readiness(timeout_s: float = 1.5) -> tuple[bool, str]:
    """Return whether every local voice runtime component is available.

    Keep this check cheap: model construction belongs to ``connect()``, but a
    missing optional extra or system phonemizer must disable Start instead of
    letting the WebSocket claim readiness and fail a few seconds later.
    """
    required_modules = ("faster_whisper", "kokoro", "soundfile")
    if any(importlib.util.find_spec(name) is None for name in required_modules):
        return False, "missing-dependencies"
    # The voice-local extra installs espeakng-loader, which supplies a bundled
    # phonemizer even when launchd's minimal PATH cannot see Homebrew's binary.
    has_phonemizer = (
        shutil.which("espeak-ng") is not None
        or shutil.which("espeak") is not None
        or importlib.util.find_spec("espeakng_loader") is not None
    )
    if not has_phonemizer:
        return False, "missing-phonemizer"
    if not ollama_reachable(timeout_s=timeout_s):
        return False, "ollama-unavailable"
    return True, "ready"


def polish_transcript(text: str) -> str:
    """Apply the user's dictation dictionary to a voice transcript.

    The dictation path earns its accuracy partly AFTER Whisper: the personal
    dictionary fixes the words the recognizer keeps getting wrong ("App
    Store", proper nouns). Voice transcripts deserve the same corrections —
    same user, same vocabulary, same mistakes. bump_usage=False: voice hits
    must not skew the dictation dictionary's learning statistics.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    try:
        from diapason.speech.dictation_dictionary import apply_dictionary

        return apply_dictionary(cleaned, bump_usage=False)
    except Exception:  # noqa: BLE001 - the dictionary is a bonus, never a gate
        return cleaned


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
            # Realtime audio must not inherit the dictation hotword list:
            # on pure background noise it reproducibly hallucinated the first
            # brand in that list, "Google Chrome". Silero VAD plus a greedy,
            # independent decode is both safer and substantially faster.
            use_dictionary_hints=False,
            realtime=True,
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
        return polish_transcript(getattr(result, "text", "") or "")

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


# Turns that plainly need no tool: acknowledgements, greetings, thanks. Every
# entry must be impossible to read as a command — « arrête » and « stop » stay
# out, they end screen sharing.
#
# This used to be the opposite: an allowlist of trigger words (agenda, spotify,
# ouvre, joue…), and a turn without one got no tools at all. The system prompt
# meanwhile advertises twenty tools, so « quelles sont mes tâches aujourd'hui »,
# « combien j'ai dépensé ce mois-ci » and « note que je dois appeler le
# dentiste » were all answered from the model's imagination — the prompt
# promised, the filter removed, and the reply sounded exactly as confident
# either way. An allowlist has to enumerate every phrasing of every capability
# to be correct; a denylist only has to recognise "yeah, thanks" to be useful,
# and anything it fails to recognise gets the tools.
# ``'`` and ``’`` both, because which one arrives depends on the speech-to-text
# engine, not on the speaker. Matching only the ASCII form let « d’accord »
# through as a tool-bearing turn.
_APOS = r"['’]"
_NO_TOOL_TURN_RE = re.compile(
    r"^\W*(?:"
    r"oui|ouais|non|nan|ok|okay|d" + _APOS + r"accord|dac|entendu|"
    r"merci(?:\s+beaucoup)?|de\s+rien|"
    r"salut|bonjour|bonsoir|coucou|hello|hi|hey|"
    r"au\s+revoir|bye|à\s+plus|à\s+bientôt|bonne\s+nuit|"
    r"parfait|super|génial|cool|nickel|très\s+bien|"
    r"exactement|voilà|c" + _APOS + r"est\s+ça|je\s+vois|"
    r"ah|oh|hmm|euh|mm+"
    r")\W*$",
    re.IGNORECASE,
)


def _turn_needs_tools(messages: Sequence[dict]) -> bool:
    """Whether to send the tool schema with this turn.

    Sending it costs prefill on a local model, which in a spoken conversation
    is audible. But withholding it costs the user a capability they were told
    they had, silently — so the default is to send, and only an utterance
    recognisably free of any request is exempt.
    """
    for message in reversed(messages):
        if message.get("role") == "user":
            content = str(message.get("content") or "").strip()
            if not content:
                return False
            return not _NO_TOOL_TURN_RE.match(content)
    return False


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
        needs_tools = bool(tools_schema) and _turn_needs_tools(messages)

        def worker() -> None:
            def stream_once(with_tools: bool) -> None:
                from diapason.core.local_mode import assert_may_leave

                assert_may_leave(
                    "the realtime voice transcript", destination=_ollama_base()
                )
                # The clock is appended per CALL, not baked at warm-up: a
                # session lives for hours, and yesterday's timestamp is worse
                # than none.
                dated = f"{system}\n\nDate et heure actuelles : {french_now()}."
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": [{"role": "system", "content": dated}] + messages,
                    "stream": True,
                    "think": False,
                    "options": {"num_predict": 320},
                    # Without this Ollama unloads the model after five idle
                    # minutes, and the next turn silently pays a 6–9 s reload
                    # — the single worst "why is it slow now" in a session.
                    "keep_alive": "30m",
                }
                if with_tools and tools_schema:
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
                    loop.call_soon_threadsafe(queue.put_nowait, ("tools", calls))

            try:
                try:
                    # The full schema is ~9 KB / ~2,600 prompt tokens. On the
                    # measured 14B local model, a cold ordinary turn spent
                    # almost eight seconds parsing tools it could not need.
                    stream_once(with_tools=needs_tools)
                except urllib.error.HTTPError as exc:
                    detail = ""
                    try:
                        detail = exc.read().decode("utf-8", "replace")
                    except Exception:  # noqa: BLE001
                        pass
                    if "does not support tools" not in detail:
                        raise
                    # Some models (gemma3 among them) refuse the tools field
                    # outright — Ollama 400s the whole request. A voice that
                    # cannot act is degraded; one that errors on every single
                    # turn is broken. Retry once without tools and say so.
                    logger.warning(
                        "%s does not support tools; local voice continues without them",
                        model,
                    )
                    stream_once(with_tools=False)
            except Exception as exc:  # noqa: BLE001 - surfaced as an event
                logger.debug("local LLM stream failed", exc_info=True)
                loop.call_soon_threadsafe(queue.put_nowait, f"\x00ERROR\x00{exc}")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, worker)
        return queue

    return start


def _tool_note(call: dict, reply: dict) -> str:
    """One line of what a tool did, for the cross-turn history trace.

    Deliberately lossy: the point is that « joue-la » next turn can find
    "open_anything(joue papaoutai sur youtube) -> ok: Playing top YouTube
    result…", not to replay the full JSON payload through every prompt.
    """
    function = call.get("function") or {}
    name = str(function.get("name") or "?")
    raw_args = function.get("arguments") or {}
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except ValueError:
            raw_args = {}
    args = raw_args if isinstance(raw_args, dict) else {}
    arg = str(args.get("target") or args.get("query") or args.get("uri") or "")
    outcome = ""
    try:
        payload = json.loads(reply.get("content") or "{}")
        # json.loads happily returns a str or list; .get on those is an
        # AttributeError, which — raised here — would abort the whole
        # spoken turn over a logging nicety.
        if not isinstance(payload, dict):
            payload = {}
        ok = "ok" if payload.get("ok") else "failed"
        outcome = str(payload.get("content") or payload.get("error") or "")
    except (ValueError, TypeError):
        ok = "?"
    detail = f"({arg[:80]})" if arg else ""
    tail = f": {outcome[:160]}" if outcome else ""
    return f"{name}{detail} -> {ok}{tail}"


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
        self._preroll = bytearray()
        self._speech_samples = 0
        self._silence_samples = 0
        self._in_speech = False
        self._respond_task: Optional[asyncio.Task[None]] = None
        self._warm_task: Optional[asyncio.Task[None]] = None
        # (buffered byte count, transcription task) — valid only while the
        # buffer has not grown past the snapshot it was taken from.
        self._speculative: Optional[tuple[int, asyncio.Task[str]]] = None
        # Transcription affichée PENDANT qu'on parle. Distincte du
        # spéculatif, qui sert à répondre plus tôt et ne s'exécute que dans
        # le silence : celle-ci tourne au milieu de la phrase, et son seul
        # rôle est que l'écran suive la voix.
        self._partial: Optional[asyncio.Task[str]] = None
        self._partial_mark = 0
        self._partial_text = ""
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
        # A ready frame is a contract: microphone audio can be processed. The
        # old lifecycle sent it before Kokoro/Whisper loaded, so a missing
        # optional dependency looked like a successful session and then died.
        # Warm under the shared lock first; later sessions reuse the models.
        self._warm_task = asyncio.get_running_loop().create_task(self._warm())
        if await self._warm_task:
            await self._queue.put(SessionEvent(kind="ready"))

    async def _warm(self) -> bool:
        async with _SHARED_LOCK:
            try:
                if self._stt is None:
                    self._stt = await asyncio.to_thread(_default_stt)
                if self._tts is None:
                    self._tts = await asyncio.to_thread(_default_tts, self._voice)
                    if not _SHARED.get("tts_warmed"):
                        # Kokoro loads the selected voice weights lazily on
                        # its first synthesis. Pay that one-off cost before
                        # the ready event, while the UI already says it is
                        # preparing, instead of after the user's first words.
                        await asyncio.to_thread(self._tts, "Prêt.")
                        _SHARED["tts_warmed"] = True
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
                    self._llm = _default_llm(self._model, self._system_prompt(), schema)
                if self._tool_executor is None and self._enable_tools:
                    from diapason.speech.realtime.tools import (
                        execute_voice_tool,
                    )

                    self._tool_executor = lambda name, args: execute_voice_tool(
                        name, args, self._allowed_tools
                    )
                return True
            except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
                logger.exception("local voice warm-up failed")
                await self._queue.put(
                    SessionEvent(kind="error", detail=f"local setup: {exc}")
                )
                return False

    def _system_prompt(self) -> str:
        # Memory-laden instructions from the server COMPOSE with the voice
        # rules instead of replacing them. The first cut returned the
        # instructions alone, and since memory injection is on by default,
        # the no-emoji rule and the language pin silently vanished in real
        # sessions — only the text sanitiser was left standing.
        if self._instructions:
            base = self._instructions
        else:
            try:
                from diapason.speech.realtime.oral_prompt import (
                    build_live_agent_template,
                )

                base = build_live_agent_template(enable_tools=self._enable_tools)
            except Exception:  # noqa: BLE001 - a persona is never fatal
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

    def _feed_preroll(self, pcm16: bytes) -> None:
        """Roll the pre-speech window forward, bounded to PRE_ROLL_S."""
        self._preroll.extend(pcm16)
        budget = int(PRE_ROLL_S * INPUT_RATE) * 2
        excess = len(self._preroll) - budget
        if excess > 0:
            del self._preroll[:excess]

    async def _pump_partial(self) -> None:
        """Faire suivre l'écran à la voix, pendant qu'elle parle.

        Tous les événements « transcript » partaient avec ``final=True`` :
        rien ne pouvait s'afficher avant la fin de la phrase, et l'écran
        restait vide pendant qu'on parlait. ``SessionEvent`` portait déjà un
        champ ``final`` que personne n'alimentait — le canal existait, il
        était muet.

        Une seule transcription à la fois, jamais attendue. La récolte se
        fait au passage de la trame suivante : ``send_audio`` est appelée à
        chaque paquet du micro et ne doit jamais bloquer, sinon c'est
        l'audio lui-même qui prend du retard.

        Le résultat est *remplacé*, pas ajouté : whisper relit tout le tampon
        et peut réviser ce qu'il avait compris. C'est ce qui fait qu'un mot
        se corrige tout seul à l'écran au lieu de se dupliquer.
        """
        if self._stt is None:
            return

        # 1. Récolter celle qui vient de finir.
        if self._partial is not None and self._partial.done():
            tache, self._partial = self._partial, None
            try:
                texte = (tache.result() or "").strip()
            except BaseException:  # noqa: BLE001 - annulation comprise
                texte = ""
            if texte and texte != self._partial_text:
                self._partial_text = texte
                await self._queue.put(
                    SessionEvent(
                        kind="transcript",
                        role="user",
                        text=texte,
                        final=False,
                        replace=True,
                    )
                )

        # 2. En relancer une si assez de parole neuve s'est accumulée.
        if self._partial is not None:
            return
        if self._speech_samples < int(MIN_SPEECH_S * INPUT_RATE):
            # Whisper invente des mots sur un souffle. Sous ce seuil, se taire
            # vaut mieux qu'afficher une phrase que personne n'a dite.
            return
        neuf = len(self._buffer) - self._partial_mark
        if neuf < int(PARTIAL_EVERY_S * INPUT_RATE) * 2:  # octets, pas samples
            return
        self._partial_mark = len(self._buffer)
        instantane = bytes(self._buffer)
        self._partial = asyncio.get_running_loop().create_task(
            asyncio.to_thread(self._stt, instantane)
        )

    def _drop_partial(self) -> None:
        """Oublier la transcription en cours et le texte affiché.

        Appelé quand le tour se termine ou qu'il est abandonné : ce qui est
        en vol décrit un tampon qui n'existe plus.
        """
        if self._partial is not None:
            self._partial.cancel()
            self._partial = None
        self._partial_mark = 0
        self._partial_text = ""

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
            # Echo of our own playback — but a user starting to talk over
            # the assistant ALSO lands here until they cross the barge
            # threshold. Feed the pre-roll ring so the onset of a barge-in
            # is recovered instead of lost.
            self._feed_preroll(pcm16)
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
            if not self._in_speech and self._preroll:
                # The turn's first loud frame: everything quieter that came
                # just before it is the word's real beginning.
                self._buffer.extend(self._preroll)
                self._preroll.clear()
            self._in_speech = True
            self._silence_samples = 0
            self._speech_samples += len(pcm16) // 2
            self._buffer.extend(pcm16)
            await self._pump_partial()
            return

        if not self._in_speech:
            # Leading silence is not buffered wholesale — but its tail end is
            # where the next word's onset lives, so it feeds the ring.
            self._feed_preroll(pcm16)
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
            self._drop_partial()
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
            self._dispatch_text(text, turn_started=time.monotonic())
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
        turn_started = time.monotonic()
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
            stt_ms = (time.monotonic() - turn_started) * 1000
            logger.info(
                "local voice timing: stage=stt ms=%.0f audio_ms=%.0f chars=%d",
                stt_ms,
                len(utterance) / 2 / INPUT_RATE * 1000,
                len(text),
            )
            if not text:
                logger.info("local voice rejected non-speech turn")
                return
            await self._dispatch_text(text, turn_started=turn_started)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the UI must hear about it
            logger.exception("local voice turn failed")
            await self._queue.put(SessionEvent(kind="error", detail=str(exc)))

    async def _dispatch_text(self, text: str, *, turn_started: float) -> None:
        await self._queue.put(
            SessionEvent(kind="transcript", role="user", text=text, final=True)
        )
        if is_stop_phrase(text):
            # They asked for quiet. The barge-in already silenced playback;
            # answering would be one more sentence of exactly what they asked
            # to stop.
            return
        if await self._try_fast_voice_action(text, turn_started=turn_started):
            return
        await self._respond_to_text(text, already_queued=True)

    async def _try_fast_voice_action(
        self, text: str, *, turn_started: float
    ) -> bool:
        """Execute an explicit open/search command without two LLM rounds.

        A bare app name is deliberately excluded: Whisper hallucinated
        "Google Chrome" from silence, and a false transcript must never turn
        into an OS action. Only a spoken imperative reaches this path.
        """
        if not self._enable_tools:
            return False
        from diapason.desktop.voice_commands import (
            execute_voice_action,
            is_explicit_voice_command,
            parse_voice_command,
        )

        if not is_explicit_voice_command(text):
            return False
        action = parse_voice_command(text)
        # ``open_anything`` is intentionally left to the regular tool path:
        # its target may be an app, file, folder or web page and a failed
        # deterministic guess must not swallow the model's richer resolver.
        if action.kind not in {"focus_app", "open_uri", "search"}:
            return False

        action_started = time.monotonic()
        result = await asyncio.to_thread(execute_voice_action, action)
        if not result.get("handled"):
            return False
        success = bool(result.get("success"))
        extra = action.extra or {}
        # A URL read aloud is noise; the human label travels in extra.
        target = str(
            extra.get("spoken")
            or result.get("target")
            or action.target
            or "l’application"
        )
        await self._queue.put(
            SessionEvent(
                kind="tool",
                tool_name="open_anything",
                tool_ok=success,
                detail="" if success else str(result.get("detail") or "")[:200],
            )
        )
        self._history.append({"role": "user", "content": text})
        spoken: List[str] = []
        verb = "Je lance" if extra.get("play") else "J’ouvre"
        response = (
            f"{verb} {target}."
            if success
            else f"Je n’ai pas pu ouvrir {target}."
        )
        await self._speak_sentence(response, spoken)
        self._history.append({"role": "assistant", "content": response})
        del self._history[:-16]
        await self._queue.put(
            SessionEvent(
                kind="transcript",
                role="assistant",
                text=response,
                final=True,
            )
        )
        logger.info(
            "local voice timing: stage=direct_action action=%s "
            "action_ms=%.0f total_ms=%.0f ok=%s",
            action.kind,
            (time.monotonic() - action_started) * 1000,
            (time.monotonic() - turn_started) * 1000,
            success,
        )
        return True

    async def _respond_to_text(
        self, text: str, *, already_queued: bool = False
    ) -> None:
        response_started = time.monotonic()
        try:
            await self._wait_warm()
            assert self._llm is not None and self._tts is not None
            if not already_queued:
                await self._queue.put(
                    SessionEvent(kind="transcript", role="user", text=text, final=True)
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
            tool_notes: List[str] = []
            self._budget.reset()
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
                    pending = await self._speak_complete_sentences(pending, spoken)
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
                    reply = await self._run_tool(call)
                    messages.append(reply)
                    tool_notes.append(_tool_note(call, reply))

            answer = " ".join(spoken).strip()
            if tool_notes:
                # The raw tool payloads stay per-turn (see above), but a
                # compact trace must survive: without it, « joue-la » at the
                # next turn has nothing to resolve against — the model only
                # ever saw "C'est ouvert." in its own history.
                self._history.append(
                    {
                        "role": "system",
                        "content": "Actions just performed: " + " ; ".join(tool_notes),
                    }
                )
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
            logger.info(
                "local voice timing: stage=response total_ms=%.0f "
                "chars=%d tool_steps=%d",
                (time.monotonic() - response_started) * 1000,
                len(answer),
                self._budget.used,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("local voice response failed")
            await self._queue.put(SessionEvent(kind="error", detail=str(exc)))

    def _restore_spoken_target(self, name: str, args: dict) -> dict:
        """The spoken phrase is the source of truth, not the model's URL.

        Despite explicit prompt examples, the model sometimes paraphrases a
        « joue X sur youtube » into a self-built results URL — which only
        shows a list, never plays. When the tool target is such a URL and
        the user's utterance carried a play verb aimed at YouTube, hand the
        tool the utterance itself: open_anything's intent parser knows how
        to turn it into actual playback.
        """
        if name != "open_anything":
            return args
        target = str(args.get("target") or "")
        if not re.match(r"^https?://(?:www\.)?youtube\.com/results", target):
            return args
        last_user = next(
            (
                m.get("content", "")
                for m in reversed(self._history)
                if m.get("role") == "user"
            ),
            "",
        )
        low = last_user.lower()
        if "youtube" in low and re.search(
            r"\b(?:joue|play|mets|lance|écoute|ecoute|regarde|watch)\b", low
        ):
            logger.info("voice tool: model built a results URL; restoring phrase")
            return {**args, "target": last_user}
        return args

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

        args = self._restore_spoken_target(name, args)
        # Successful voice tool calls used to leave zero trace server-side —
        # every misfire diagnosis started blind. One compact line fixes that.
        logger.warning(
            "voice tool %s args=%s", name, json.dumps(args, ensure_ascii=False)[:200]
        )

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

    async def _speak_complete_sentences(self, pending: str, spoken: List[str]) -> str:
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
