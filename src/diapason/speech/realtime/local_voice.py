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

from diapason.core.tool_turn import NO_TOOL_TURN_RE, turn_needs_tools
from diapason.server.suite import rappel_pour_la_voix
from diapason.speech.realtime import actualite_vocale
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
# Fin de tour SÉMANTIQUE. 800 ms est le prix payé quand on ne sait rien du
# contenu : assez long pour ne pas couper une phrase en deux. Mais quand la
# transcription déjà en main se termine par « ? » ou « . », la phrase EST
# finie — attendre 800 ms de plus est du silence pur, et c'est le premier
# poste de latence de toute la boucle vocale, devant le modèle lui-même.
# Les humains tournent à ~200 ms précisément parce qu'ils jugent la
# complétude pendant que l'autre parle, au lieu d'attendre le silence.
SEMANTIC_END_S = 0.45
# L'autre direction, tout aussi importante : « et donc je voulais dire
# que… » n'est PAS fini, même après 800 ms — couper là, c'est répondre à une
# phrase que la personne est encore en train de construire. On attend plus.
HESITATION_END_S = 1.15
# Le verdict « complet » n'est cru que si la transcription couvre la parole
# jusqu'à ~ce près de sa fin. Un partiel en retard peut dire « Quelle heure
# est-il » — complet — alors que la personne a ajouté « à » et réfléchit à
# la suite. L'hésitation, elle, accepte une couverture lâche : se tromper
# dans ce sens ne coûte que de l'attente.
ENDPOINT_COVERAGE_S = 0.75

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


# Mots français sur lesquels une phrase ne se termine pas : conjonctions,
# prépositions, déterminants, auxiliaires. Un dernier mot dans cette liste
# signifie « la suite arrive ». Les pronoms d'inversion (« est-il ») ne s'y
# trouvent pas : Whisper les écrit avec le trait d'union, donc le dernier
# token n'est jamais le pronom nu.
_TRAILING_INCOMPLETE = frozenset(
    "et mais ou donc or ni car que qu qui dont de du des à au aux le la les "
    "un une avec pour sur dans par sans sous chez vers si comme quand alors "
    "puis euh eh ben est sont être va vais vas veux veut peux peut dois doit "
    "faut mon ma mes ton ta tes son sa ses ce cet cette ces très plus moins "
    "je tu il elle on nous vous ils elles "
    # Formes élidées : le découpage sur l'apostrophe laisse la lettre seule
    # (« parce que j' » → « j »).
    "j l d n c s t m".split()
)


def classify_endpoint(text: str) -> str:
    """« complete », « hesitation » ou « neutral » pour une fin de tour.

    Conservateur par construction : « complete » exige une ponctuation
    terminale — c'est le seul verdict qui RACCOURCIT l'attente, donc le seul
    qui puisse couper quelqu'un. « hesitation » ne fait qu'attendre plus,
    l'erreur y est bon marché. Tout le reste garde le délai normal.
    """
    t = (text or "").strip().rstrip("»\"' ")
    if not t:
        return "neutral"
    # « … » est l'orthographe même du trailing-off : Whisper l'émet quand la
    # voix retombe sans conclure. C'est le contraire d'une phrase finie.
    if t.endswith(("...", "…")):
        return "hesitation"
    if t[-1] in ".!?":
        return "complete"
    if t[-1] in ",;:":
        return "hesitation"
    dernier = re.split(r"[\s']+", t.lower())[-1]
    if dernier in _TRAILING_INCOMPLETE:
        return "hesitation"
    return "neutral"


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


_CITATION_ECRITE = re.compile(
    r"\s*\[\d+(?:\s*[,;]\s*\d+)*\]|\s*(?:Sources?\s*:\s*)?\(?https?://\S+\)?"
)


def speakable(text: str) -> str:
    """Strip what a voice cannot say; collapse the leftover whitespace.

    Returns "" when nothing pronounceable is left — an emoji-only chunk
    leaves its punctuation behind ("👍👍." → "."), and a vocoder handed a
    bare period says "point" out loud.
    """
    cleaned = _UNSPEAKABLE.sub("", text or "")
    # 21/09/2026 : « Mark Carney [2] » se prononçait « Mark Carney deux » ;
    # un numéro de source ou une adresse web ne se disent pas.
    cleaned = _CITATION_ECRITE.sub("", cleaned)
    cleaned = re.sub(r"^[\s\-•]+", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    if not re.search(r"[\w]", cleaned, re.UNICODE):
        return ""
    return cleaned


class _SpecTurn:
    """Une réponse en cours de spéculation : la file du modèle, dupliquée.

    Le draineur lit la file originale et garde TOUT ce qu'il voit, y compris
    le ``None`` final — la spéculation ne doit rien consommer que l'adoption
    ne puisse rejouer. Au passage, il repère la première phrase avec le même
    découpage que ``_speak_complete_sentences`` et la synthétise en avance.
    L'audio n'est qu'un ``bytes`` en attente : l'émettre reste le privilège
    exclusif de la boucle de drainage de ``_respond_to_text``.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.items: list = []
        self.grew = asyncio.Event()
        self.first_sentence: Optional[str] = None
        self.first_audio: Optional["asyncio.Task[bytes]"] = None
        self.drainer: Optional["asyncio.Task[None]"] = None
        # La file productrice d'origine : c'est elle qu'abort() doit tuer —
        # annuler le drainer seul laissait le flux Ollama courir en zombie.
        self.source: Optional[Any] = None
        self._rediffusions: set[asyncio.Task] = set()

    def abort(self) -> None:
        """Abandonner la spéculation ET son producteur — le créneau se libère."""
        if self.drainer is not None:
            self.drainer.cancel()
        if self.first_audio is not None:
            self.first_audio.cancel()
        for rediffusion in tuple(self._rediffusions):
            rediffusion.cancel()
        arret = getattr(self.source, "abort", None)
        if arret is not None:
            arret()

    def replay_queue(self) -> "asyncio.Queue[Any]":
        """Une file équivalente à l'originale, rejouée depuis le début.

        Le draineur peut être encore en train de lire : la rediffusion suit
        au fil de l'eau, réveillée à chaque arrivée, et se termine sur le
        ``None`` que le draineur aura relayé.
        """
        q = _AbortableQueue()

        async def pump() -> None:
            i = 0
            while True:
                if i < len(self.items):
                    item = self.items[i]
                    i += 1
                    await q.put(item)
                    if item is None:
                        return
                else:
                    # Effacer AVANT de revérifier : un ajout entre le test et
                    # l'attente serait sinon perdu jusqu'au suivant.
                    self.grew.clear()
                    if i < len(self.items):
                        continue
                    await self.grew.wait()

        q.producer = asyncio.get_running_loop().create_task(pump())
        self._rediffusions.add(q.producer)
        q.producer.add_done_callback(self._rediffusions.discard)
        return q


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


def french_today(now=None) -> str:
    """La date seule, sans l'heure — stable toute la journée.

    L'horloge à la minute près, recollée au prompt à chaque appel, invalidait
    le cache de préfixe d'Ollama dès que la minute changeait : les six mille
    jetons de prompt et de schémas d'outils étaient relus en entier, plusieurs
    secondes par tour. La voix dispose maintenant de ``current_time`` : quand
    l'heure compte, le modèle la LIT — c'est plus juste qu'une heure figée au
    début du tour, et le préfixe, lui, ne bouge plus qu'à minuit.
    """
    import datetime

    if now is None:
        now = datetime.datetime.now()
    day = _FRENCH_DAYS[now.weekday()]
    month = _FRENCH_MONTHS[now.month - 1]
    return f"{day} {now.day} {month} {now.year}"


def _prewarm_prefix(model: str, system: str, tools_schema: list) -> None:
    """Fait lire le préfixe (système + outils) au modèle, en tâche de fond."""
    import threading

    def _lire() -> None:
        try:
            from diapason.core.local_mode import assert_may_leave

            assert_may_leave("the voice prefix prewarm", destination=_ollama_base())
            dated = (
                f"{system}\n\nDate actuelle : {french_today()}. "
                "Pour l'heure exacte, appelle l'outil current_time."
            )
            payload: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "system", "content": dated}],
                "stream": False,
                "think": False,
                "keep_alive": "30m",
                "options": {"num_predict": 1},
            }
            if tools_schema:
                payload["tools"] = tools_schema
            request = urllib.request.Request(
                f"{_ollama_base()}/api/chat",
                json.dumps(payload).encode(),
                {"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=120):
                pass
            logger.debug("voice prefix prewarmed")
        except Exception:  # noqa: BLE001 - le confort ne casse rien
            logger.debug("voice prefix prewarm failed", exc_info=True)

    threading.Thread(target=_lire, daemon=True, name="voice-prewarm").start()


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
        from diapason.speech.dictate_polish import reparer_homophones_de_commande

        cleaned = reparer_homophones_de_commande(cleaned)
    except Exception:  # noqa: BLE001 - la réparation est un bonus, jamais une porte
        pass
    try:
        from diapason.speech.dictation_dictionary import apply_dictionary

        return apply_dictionary(cleaned, bump_usage=False)
    except Exception:  # noqa: BLE001 - the dictionary is a bonus, never a gate
        return cleaned


def _taille_stt(config: Any) -> str:
    """L'oreille de la conversation : [speech.realtime] stt_model, sinon
    celle de la dictée ([speech] model), sinon small.

    Séparées le 24 août 2026 : medium partout rendait la voix lente à
    répondre (+1,5 s par tour) — la conversation préfère la vitesse, la
    dictée préfère la lettre.
    """
    realtime = getattr(getattr(config, "speech", None), "realtime", None)
    voix = str(getattr(realtime, "stt_model", "") or "").strip()
    if voix:
        return voix
    return str(getattr(config.speech, "model", "") or "small")


def _default_stt() -> Callable[[bytes], str]:
    """Whisper, shared across sessions, French pinned via the user's config."""
    from diapason.core.config import load_config
    from diapason.speech.faster_whisper import FasterWhisperBackend

    backend = _SHARED.get("stt")
    if backend is None:
        config = load_config()
        backend = FasterWhisperBackend(
            model_size=_taille_stt(config),
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


# Le choix « envoyer la trousse ou non » a été extrait dans core/tool_turn.py
# le 22 août 2026, quand le chat en flux a reçu ses outils et a hérité du même
# arbitrage. Le raisonnement — liste de REFUS, jamais d'autorisation — y est
# consigné en entier. Ces alias gardent les noms d'origine : ils sont importés
# par tests/speech/test_local_voice.py.
_NO_TOOL_TURN_RE = NO_TOOL_TURN_RE
_turn_needs_tools = turn_needs_tools


# Voir le payload de _default_llm : mesuré, pas choisi.
VOICE_TOOL_TURN_TEMPERATURE = 0.1

# Le filet anti-promesse vit désormais dans core/promesse.py (partagé avec
# le chat, affiné le 24 août 2026 : les OFFRES — « veux-tu que je
# cherche ? » — ne somment plus).
from diapason.core import promesse as _promesse  # noqa: E402

# Ces trois noms RÉ-EXPORTENT — même motif que `_NO_TOOL_TURN_RE` plus haut.
# Des AFFECTATIONS, et non des alias d'import : `ruff --fix` a supprimé
# l'alias `_PROMESSE_SANS_ACTE_RE` le 25 août 2026 en le jugeant inutilisé —
# ce qu'il était, dans ce module — et deux tests sont tombés à l'import. Un
# ré-export qui ne ressemble pas à un usage est une bombe à retardement ;
# une affectation, aucun linter ne la prendra jamais pour un oubli.
PROMESSE_SANS_ACTE_RE = _promesse.PROMESSE_SANS_ACTE_RE
_PROMESSE_SANS_ACTE_RE = PROMESSE_SANS_ACTE_RE
_est_une_promesse_sans_acte = _promesse.est_une_promesse_sans_acte


class _AbortableQueue(asyncio.Queue):
    """File de jetons dont le producteur peut être ABANDONNÉ.

    Le zombie (Atlas, 24 août 2026) : l'ancien producteur était un thread
    urllib bloquant sans canal d'annulation — barge-in, phrase d'arrêt ou
    action rapide laissaient le flux Ollama courir jusqu'à ses 320 jetons,
    et avec -np 1 ce fantôme BLOQUAIT le créneau du tour suivant. La
    latence surprise juste après une interruption, c'était lui.

    ``abort()`` annule la tâche productrice : l'``async with`` du client
    httpx ferme la connexion, Ollama avorte la génération, le créneau se
    libère — puis le ``finally`` du producteur pousse le ``None`` terminal,
    donc tout consommateur en attente se termine proprement.
    """

    producer: Optional["asyncio.Task[None]"] = None

    def abort(self) -> None:
        if self.producer is not None and not self.producer.done():
            self.producer.cancel()


class _RefusOutils(RuntimeError):
    """Ollama a refusé le champ tools (« does not support tools »)."""


def _num_ctx() -> int:
    try:
        from diapason.engine.ollama import _default_num_ctx

        return int(_default_num_ctx())
    except Exception:  # noqa: BLE001 - le défaut d'Ollama plutôt qu'une panne
        return 16384


def _default_llm(
    model: str,
    system: str,
    tools_schema: Optional[List[dict]] = None,
    *,
    mesures: Optional[dict] = None,
) -> Callable[[List[dict]], "asyncio.Queue[Any]"]:
    """Streamed chat against Ollama; the queue carries tokens and tool calls.

    Queue items: ``str`` tokens, ``("tools", [...])`` when the model asks to
    act, the ``\x00ERROR\x00`` sentinel, and ``None`` at end of stream.

    ``think`` is disabled explicitly: qwen3.5 reasons silently first, and in
    a voice conversation that silence IS the latency — measured, it swallowed
    the entire token budget before a single audible word.

    ``mesures`` est un dict mutable où le producteur consigne les postes
    aveugles du tour (ttft_ms, prefill_ms, eval_ms, load_ms…) — le témoin
    prefill dit si le cache de préfixe tient (dizaines de jetons) ou brûle
    (~6 000).
    """

    def start(messages: List[dict]) -> "asyncio.Queue[Any]":
        queue: _AbortableQueue = _AbortableQueue()
        # La trousse s'attache MÊME aux tours « merci » (24 août 2026) :
        # chaque variante de préfixe est un préfixe différent, et Ollama
        # (-np 1) n'en cache qu'un — c'est l'ALTERNANCE qui coûtait les
        # ~2,4 s de relecture, pas la taille. Un préfixe stable reste chaud.
        needs_tools = bool(tools_schema)

        async def stream_once(with_tools: bool) -> None:
            import httpx

            from diapason.core.local_mode import assert_may_leave

            assert_may_leave(
                "the realtime voice transcript", destination=_ollama_base()
            )
            # La date est relue à chaque APPEL — une session vit des
            # heures et la date d'hier est pire que rien — mais l'HEURE
            # n'y est plus : elle changeait chaque minute et brûlait le
            # cache de préfixe (six mille jetons relus par tour). L'heure
            # exacte vient de l'outil current_time, qui dit le présent
            # au lieu d'un instantané pris au début du tour.
            dated = (
                f"{system}\n\nDate actuelle : {french_today()}. "
                "Pour l'heure exacte, appelle l'outil current_time."
            )
            payload: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "system", "content": dated}] + messages,
                "stream": True,
                "think": False,
                "options": {
                    "num_predict": 320,
                    # La même fenêtre que le chat (config, sinon le défaut) :
                    # sans elle, Ollama prenait la sienne, et deux fenêtres
                    # font deux modèles chargés (revue vocale du 21/09).
                    "num_ctx": _num_ctx(),
                    # Le tour qui PORTE des outils est refroidi. Décider
                    # d'appeler un outil n'est pas un acte créatif, et à
                    # la voix la règle « keep answers short and spoken »
                    # pousse activement contre l'action : le modèle
                    # préfère répondre vite que regarder. Mesuré sur
                    # qwen3.5:9b avec le prompt vocal COMPLET, six essais
                    # par palier, « retiens que… » et « mes tâches ? » :
                    #
                    #   défaut d'Ollama (0,8)   3/6
                    #   0,3                     4/6
                    #   0,1                   6/6 et 5/6
                    #
                    # Un tour SANS outils garde la chaleur par défaut :
                    # c'est là que la parole se joue, et une réponse
                    # parlée glacée s'entend.
                    **(
                        {"temperature": VOICE_TOOL_TURN_TEMPERATURE}
                        if (with_tools and tools_schema)
                        else {}
                    ),
                },
                # Without this Ollama unloads the model after five idle
                # minutes, and the next turn silently pays a 6–9 s reload
                # — the single worst "why is it slow now" in a session.
                "keep_alive": "30m",
            }
            if with_tools and tools_schema:
                payload["tools"] = tools_schema
            calls: List[dict] = []
            t0 = time.monotonic()
            premier_jeton: Optional[float] = None
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{_ollama_base()}/api/chat", json=payload
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "replace")
                        if (
                            response.status_code == 400
                            and "does not support tools" in detail
                        ):
                            raise _RefusOutils(detail)
                        raise RuntimeError(
                            f"Ollama HTTP {response.status_code}: {detail[:300]}"
                        )
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        message = data.get("message") or {}
                        token = message.get("content", "")
                        if token:
                            if premier_jeton is None:
                                premier_jeton = time.monotonic()
                                ttft_ms = (premier_jeton - t0) * 1000
                                if mesures is not None:
                                    mesures["ttft_ms"] = round(ttft_ms)
                                logger.info(
                                    "local voice timing: stage=llm ttft_ms=%.0f",
                                    ttft_ms,
                                )
                            queue.put_nowait(token)
                        calls.extend(message.get("tool_calls") or [])
                        if data.get("done"):
                            # Les métriques du chunk final (nanosecondes) :
                            # prefill est LE témoin du cache de préfixe.
                            prefill_ms = (data.get("prompt_eval_duration") or 0) / 1e6
                            eval_ms = (data.get("eval_duration") or 0) / 1e6
                            load_ms = (data.get("load_duration") or 0) / 1e6
                            jetons = data.get("prompt_eval_count") or 0
                            if mesures is not None:
                                mesures.update(
                                    prefill_ms=round(prefill_ms),
                                    eval_ms=round(eval_ms),
                                    load_ms=round(load_ms),
                                    prompt_tokens=jetons,
                                    rounds=(mesures.get("rounds") or 0) + 1,
                                )
                            logger.info(
                                "local voice timing: stage=llm prefill_ms=%.0f "
                                "eval_ms=%.0f load_ms=%.0f prompt_tokens=%d",
                                prefill_ms,
                                eval_ms,
                                load_ms,
                                jetons,
                            )
                            break
            if calls:
                queue.put_nowait(("tools", calls))

        async def produire() -> None:
            try:
                try:
                    await stream_once(with_tools=needs_tools)
                except _RefusOutils:
                    # Some models (gemma3 among them) refuse the tools field
                    # outright — Ollama 400s the whole request. A voice that
                    # cannot act is degraded; one that errors on every single
                    # turn is broken. Retry once without tools and say so.
                    logger.warning(
                        "%s does not support tools; local voice continues without them",
                        model,
                    )
                    await stream_once(with_tools=False)
            except asyncio.CancelledError:
                # L'abandon n'est pas une panne : le finally clôt la file.
                raise
            except Exception as exc:  # noqa: BLE001 - surfaced as an event
                logger.debug("local LLM stream failed", exc_info=True)
                queue.put_nowait(f"\x00ERROR\x00{exc}")
            finally:
                queue.put_nowait(None)

        queue.producer = asyncio.get_running_loop().create_task(produire())
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


# ── Suis-je celui à qui l'on parle ? ─────────────────────────────────────
#
# Demandé le 23 août 2026 : « même si Diapason écoute, il doit savoir quand on
# s'adresse à lui — si je parle à quelqu'un d'autre, s'il y a du bruit, si je
# regarde un film. » La règle est celle d'une personne réelle dans la pièce :
#
# - on lui répond quand on vient de l'appeler par son NOM ;
# - une conversation ENGAGÉE se poursuit sans redire le nom à chaque phrase ;
# - passé un silence prolongé, elle attend d'être rappelée par son nom, et le
#   dialogue d'un film ou la voix d'un tiers ne la fait plus réagir.
#
# Le premier tour d'une session est toujours engagé : qui vient de cliquer
# « Démarrer » s'adresse évidemment à l'assistant.

ADDRESS_WINDOW_S = 90.0

# La transcription déforme le nom : « diapasant », « diapazon », « d'apaison »…
_NOM_RE = re.compile(r"[a-zà-ÿ]+")


def mentions_assistant_name(text: str) -> bool:
    """Vrai si un mot — ou DEUX mots adjacents recollés — ressemble au nom.

    La transcription coupe le nom en deux : « Dia pasons, quelle heure… »,
    constaté en session réelle. Un seul mot ne suffit donc pas ; les paires
    adjacentes se recollent avant la comparaison.
    """
    import difflib

    mots = _NOM_RE.findall(str(text or "").casefold())
    candidats = [m for m in mots if len(m) >= 6]
    candidats += [a + b for a, b in zip(mots, mots[1:]) if len(a + b) >= 6]
    return any(
        difflib.SequenceMatcher(None, c, "diapason").ratio() >= 0.75 for c in candidats
    )


def strip_assistant_name(text: str) -> str:
    """Retire l'appel initial — « Diapason, ouvre… » → « ouvre… »."""
    return (
        re.sub(
            # « Diapason, », « diapasant » — et « Dia pasons, », le nom coupé en
            # deux par la transcription.
            r"^\W*(?:[a-zà-ÿ]{2,4}\s+)?[a-zà-ÿ]*(?:diapa|pason|pazon)\w*[\s,.:!?]*",
            "",
            str(text or ""),
            flags=re.IGNORECASE,
        ).strip()
        or str(text or "").strip()
    )


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
        sur_echange: Optional[Callable[[str, str], None]] = None,
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
        # L'historique des échanges vocaux (traces.db, agent='voice') — la
        # mémoire nocturne ne relit que ce qui est écrit quelque part. Résolu
        # paresseusement ; ici et pas dans connect() : les bancs d'essai des
        # tests contournent connect() (leçon du 23 août 2026).
        self._magasin_traces_obj: Any = None
        self._magasin_traces_resolu = False
        # Le raccord vers la mémoire vivante (24 août 2026) : appelé à
        # chaque échange abouti, en plus de la trace. Sans lui, un fait
        # confié à l'oral attendait la consolidation du lendemain 3h30.
        self._sur_echange = sur_echange
        # Engagé dès la construction : le premier tour d'une session vient de
        # quelqu'un qui a cliqué « Démarrer » — il s'adresse à nous.
        self._engagee_jusqua = time.monotonic() + ADDRESS_WINDOW_S
        self._voice_lock: Optional[bool] = None
        # (buffered byte count, transcription task) — valid only while the
        # buffer has not grown past the snapshot it was taken from.
        self._speculative: Optional[tuple[int, asyncio.Task[str]]] = None
        # Réponse spéculative : la GÉNÉRATION lancée pendant le silence de
        # fin de tour, dès que la transcription complète est connue. Sûre par
        # construction : les outils ne s'exécutent et la voix ne part que
        # dans la boucle de drainage de _respond_to_text — une file qu'on
        # remplit sans la drainer ne peut ni agir ni parler.
        self._spec_llm: Optional[_SpecTurn] = None
        # Première phrase déjà synthétisée par la spéculation : (texte après
        # speakable, tâche de synthèse). Consommé une seule fois, apparié sur
        # le texte exact — un raté d'appariement coûte une synthèse normale,
        # jamais un mauvais audio.
        self._spec_audio: Optional[tuple[str, "asyncio.Task[bytes]"]] = None
        # Les postes de latence du tour en cours, remplis par le producteur
        # LLM et les jalons du tour ; snapshotés dans traces.db à la fin.
        self._mesures: dict[str, Any] = {}
        self._response_started: Optional[float] = None
        self._first_audio_logged = True
        self._ack_suivant = 0
        # Transcription affichée PENDANT qu'on parle. Distincte du
        # spéculatif, qui sert à répondre plus tôt et ne s'exécute que dans
        # le silence : celle-ci tourne au milieu de la phrase, et son seul
        # rôle est que l'écran suive la voix.
        self._partial: Optional[asyncio.Task[str]] = None
        self._partial_mark = 0
        self._partial_text = ""
        # Longueur du tampon à la dernière trame PARLÉE : la couverture d'un
        # partiel se juge contre la fin de la parole, pas celle du tampon,
        # qui continue de grossir avec le silence.
        self._speech_end_mark = 0
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
        self._derniere_app_ouverte = ""
        # Ré-engager à l'ouverture : qui clique « Démarrer » s'adresse à nous.
        self._engagee_jusqua = time.monotonic() + ADDRESS_WINDOW_S
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
                    if not _SHARED.get("acks"):
                        # Les accusés OPTIMISTES, payés une fois au chauffage :
                        # sur « monte le son », la voix répond en ~1 s au lieu
                        # de 3-5 — la 2e passe LLM se déroule pendant que
                        # l'accusé joue. Un échec = pas d'accusés, jamais une
                        # session en panne.
                        accuses: dict[str, bytes] = {}
                        for phrase in ("Ça marche.", "Je regarde."):
                            try:
                                pcm = await asyncio.to_thread(self._tts, phrase)
                                if pcm:
                                    accuses[phrase] = pcm
                            except Exception:  # noqa: BLE001
                                logger.debug("ack prerender failed", exc_info=True)
                        _SHARED["acks"] = accuses
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
                        self._model,
                        self._system_prompt(),
                        schema,
                        mesures=self._mesures,
                    )
                    # Préchauffer le PRÉFIXE, pas seulement le modèle : le
                    # premier tour d'une session payait ~2,4 s à relire prompt
                    # système et schémas d'outils (~6 000 jetons). On les fait
                    # lire MAINTENANT, pendant que Whisper et Kokoro chargent
                    # et que l'interface affiche déjà « préparation ». En fil
                    # détaché : un préchauffage raté ne doit jamais retarder
                    # ni faire échouer la session.
                    _prewarm_prefix(self._model, self._system_prompt(), schema)
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
            f"{base}\n\nAnswer in {language}. Brevity governs what you SAY, "
            "never whether you ACT: call the tool first, then report what it "
            "returned in one to three spoken sentences. Claiming an action "
            "you did not take is the one unacceptable answer. Keep answers "
            "short and spoken: "
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

    async def _harvest_partial(self) -> None:
        """Récolter une transcription partielle terminée, sans en lancer.

        Appelée aussi pendant le SILENCE : un partiel lancé juste avant la
        fin de la parole se termine après elle, et son texte sert alors de
        verdict à la fin de tour sémantique — le jeter aurait coûté
        précisément le cas le plus utile.
        """
        if self._partial is None or not self._partial.done():
            return
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

        await self._harvest_partial()

        # En relancer une si assez de parole neuve s'est accumulée.
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
        self._speech_end_mark = 0

    async def _drain_speculative(
        self, spec: _SpecTurn, src: "asyncio.Queue[Any]"
    ) -> None:
        """Dupliquer la file du modèle et préparer la première phrase.

        Le découpage est copié de ``_speak_complete_sentences`` — fin de
        phrase, ou première virgule au-delà du seuil pour le tout premier
        morceau — parce que l'audio préparé n'est utile que si son texte est
        EXACTEMENT celui que la boucle de parole découpera. Un désaccord ne
        casse rien : l'appariement rate, la phrase est synthétisée
        normalement, le gain est perdu et c'est tout.
        """
        pending = ""
        try:
            while True:
                item = await src.get()
                spec.items.append(item)
                spec.grew.set()
                if item is None:
                    return
                if (
                    spec.first_audio is None
                    and isinstance(item, str)
                    and not item.startswith("\x00ERROR\x00")
                    and self._tts is not None
                ):
                    pending += item
                    match = _SENTENCE_END.search(pending)
                    if match is None:
                        candidate = _FIRST_CHUNK.search(pending)
                        if (
                            candidate is not None
                            and candidate.end() >= _FIRST_CHUNK_MIN_CHARS
                        ):
                            match = candidate
                    if match is not None:
                        phrase = speakable(pending[: match.end()].strip())
                        if phrase:
                            spec.first_sentence = phrase
                            spec.first_audio = asyncio.get_running_loop().create_task(
                                asyncio.to_thread(self._tts, phrase)
                            )
        finally:
            # Réveiller une rediffusion en attente même sur annulation, pour
            # qu'elle ne dorme pas sur un événement que plus personne ne met.
            spec.grew.set()

    def _turn_messages(self, text: str) -> List[dict]:
        """L'assemblage du tour — LE MÊME pour la spéculation et l'adoption.

        Extrait pour qu'il soit impossible aux deux chemins de diverger : une
        spéculation bâtie sur d'autres messages répondrait à un autre
        contexte que celui que l'adoption croit servir.
        """
        hist = list(self._history)[-15:]
        note = self._anti_loop_note(hist)
        extra = [note] if note else []
        # Le CLICHÉ DU BUREAU (23 août 2026) : l'app au premier plan et les
        # apps en marche, pour que « ouvre X » sur une app déjà ouverte se
        # dise au lieu de se rejouer. Lecture du cache seulement — jamais
        # une milliseconde d'attente ici — et EN FIN de contexte : dans le
        # préambule, cet état volatil brûlerait le cache de préfixe à
        # chaque tour.
        try:
            from diapason.desktop.etat_bureau import decrire, dernier_etat_connu

            cliche = dernier_etat_connu()
            if cliche is not None:
                extra.append({"role": "system", "content": decrire(cliche)})
        except Exception:  # noqa: BLE001 - la perception est un bonus
            pass
        # CE QUE L'UTILISATEUR REGARDE DANS DIAPASON (handoff, 25 août
        # 2026) : sans ce cliché, « continue ce projet sur mon téléphone »
        # n'a aucun référent pour « ce projet ». Même discipline que le
        # cliché du bureau : lecture d'un cache volatile, en fin de
        # contexte, et silence total quand rien n'est frais.
        try:
            from diapason.desktop.contexte_app import (
                decrire as decrire_app,
            )
            from diapason.desktop.contexte_app import (
                dernier_contexte,
            )

            vue = dernier_contexte()
            if vue is not None:
                extra.append({"role": "system", "content": decrire_app(vue)})
        except Exception:  # noqa: BLE001 - la perception est un bonus
            pass
        # PERCEPTION CONTINUE sans inférence ajoutée (Atlas, 24 août 2026) :
        # pendant un partage d'écran, la boucle a DÉJÀ payé la description —
        # le tour la lit du cache au lieu d'obliger le modèle à appeler
        # screen_share_status pour voir ce que la session sait déjà. En fin
        # de contexte, comme le cliché : volatil, donc jamais en préambule.
        try:
            from diapason.desktop.screen_share import get_screen_share

            partage = get_screen_share()
            if partage.is_active():
                resume = (partage.latest_summary() or "").strip()
                if resume:
                    extra.append(
                        {
                            "role": "system",
                            "content": f"Sur l'écran partagé : {resume}",
                        }
                    )
        except Exception:  # noqa: BLE001 - la perception est un bonus
            pass
        # CE QUE LA MAIN TIENT, en dernier — donc au plus près du message de
        # l'utilisateur, parce que c'est le fait le plus actionnable du lot.
        # Sans lui, « envoie ça sur mon téléphone » n'avait aucun référent :
        # le presse-papiers spatial n'était connu que du module des gestes,
        # et la voix répondait sur ce que l'ÉCRAN affichait à cet instant.
        #
        # Main vide : on n'ajoute RIEN. Pas de « ta main est vide » — ce
        # serait la phrase creuse du §5, présente à chaque tour de chaque
        # session où les gestes ne sont jamais armés, et une invitation à
        # commenter un état dont personne n'a parlé. L'OUTIL, lui, le dit
        # franchement quand on l'appelle : parce qu'on l'a appelé.
        try:
            from diapason.desktop.presse_papiers_spatial import decrire, tenu

            objet = tenu()
            if objet is not None:
                extra.append({"role": "system", "content": decrire(objet)})
        except Exception:  # noqa: BLE001 - la perception est un bonus
            pass
        messages = hist + extra + [{"role": "user", "content": text}]
        # 21/09/2026, 23 h : « Raconte-moi l'histoire de ce pays » après
        # Haïti recevait « de quel pays tu parles ? » au chat ; la voix
        # reçoit le même rappel du sujet (server/suite.py).
        rappel = rappel_pour_la_voix(hist, text)
        if rappel is not None:
            messages.append(rappel)
        # 21/09/2026 : la consigne d'actualité est DANS l'assemblage, donc
        # dans la spéculation aussi — posée seulement à l'adoption, la
        # réponse préparée pendant le silence aurait été bâtie sans elle, et
        # adoptée telle quelle : « Justin Trudeau » de mémoire, à la voix.
        tour = self._tour_actualite(text)
        if tour is not None:
            messages.append(actualite_vocale.consigne(tour))
        return messages

    def _tour_actualite(self, text: str) -> Optional["actualite_vocale.TourVocal"]:
        """Le tour d'actualité de cet énoncé, ou None — recalculé à
        l'identique par la spéculation et par l'adoption. Sans web_search
        (outils coupés, liste du client), aucune consigne qu'on ne pourrait
        honorer (revue du 21/09)."""
        if not self._enable_tools or not self._web_search_permis():
            return None
        return actualite_vocale.preparer_tour(text, self._history, self._ville())

    def _ville(self) -> str:
        """La ville de la config ([tools] ville), lue une fois par session."""
        if not hasattr(self, "_ville_config"):
            try:
                from diapason.core.config import load_config

                self._ville_config = str(
                    getattr(load_config().tools, "ville", "") or ""
                )
            except Exception:  # noqa: BLE001 - sans config, aucune ville devinée
                self._ville_config = ""
        return self._ville_config

    def _web_search_permis(self) -> bool:
        try:
            from diapason.speech.realtime.tools import list_voice_tool_ids

            return "web_search" in set(list_voice_tool_ids(self._allowed_tools))
        except Exception:  # noqa: BLE001 - sans liste, on suppose la trousse par défaut
            return True

    @staticmethod
    def _anti_loop_note(hist: List[dict]) -> Optional[dict]:
        """Casse les boucles de répétition, structurellement.

        Vécu en session réelle : coincé par une question méta qu'il ne
        savait pas traiter, le modèle a répondu « Je t'écoute. » — une
        béquille que le prompt lui suggérait alors — puis l'a REDIT à chaque
        tour : sa propre répétition dans l'historique devenait le motif le
        plus probable à continuer. Un prompt corrigé réduit le risque ; ce
        garde le constate et le nomme, ce qui est plus fort qu'interdire.
        """
        replies = [
            (m.get("content") or "").strip()
            for m in hist
            if m.get("role") == "assistant"
        ]
        if len(replies) < 2 or not replies[-1]:
            return None
        if replies[-1].casefold() != replies[-2].casefold():
            return None
        return {
            "role": "system",
            "content": (
                "Tes deux dernières réponses sont identiques : "
                f"« {replies[-1][:80]} ». "
                "Ne redis pas cette phrase. Réponds au fond de la question ; "
                "si tu ne sais pas, dis précisément ce qui te manque."
            ),
        }

    def _speculation_pointless(self, text: str) -> bool:
        """Les énoncés qui ne passeront jamais par le modèle.

        Une phrase d'arrêt ne reçoit aucune réponse, et une commande vocale
        explicite prend le chemin direct sans LLM. Spéculer dessus ne serait
        pas dangereux — la file ne serait jamais drainée — seulement du
        calcul chauffé pour rien.
        """
        if is_stop_phrase(text):
            return True
        if not self._enable_tools:
            return False
        try:
            from diapason.desktop.voice_commands import is_explicit_voice_command

            return bool(is_explicit_voice_command(text))
        except Exception:  # noqa: BLE001 - l'aide est un bonus, jamais un mur
            return False

    def _endpoint_hint(self) -> tuple[Optional[str], bool]:
        """Le meilleur texte disponible pour juger la fin de tour, et si sa
        couverture de la parole est assez serrée pour un verdict « complet ».

        La transcription spéculative couvre TOUT le tampon : autoritaire.
        Le partiel, lui, peut être en retard d'un cycle — dire « Quelle
        heure est-il », complet, quand la personne a ajouté « à » et
        réfléchit. D'où la marge de couverture, exigée seulement pour
        raccourcir.
        """
        spec = self._speculative
        if spec is not None and spec[1].done():
            try:
                texte = (spec[1].result() or "").strip()
            except BaseException:  # noqa: BLE001 - annulation comprise
                texte = ""
            if texte:
                return texte, True
        if self._partial_text:
            marge = int(ENDPOINT_COVERAGE_S * INPUT_RATE) * 2
            couvre = self._partial_mark >= self._speech_end_mark - marge
            return self._partial_text, couvre
        return None, False

    def _end_of_turn_s(self) -> float:
        """Le silence exigé pour clore CE tour-ci — sémantique quand on sait.

        800 ms est le prix de l'ignorance : sans indice sur le contenu, il
        faut ce délai pour ne pas couper une phrase en deux. Quand la
        transcription en main finit par « ? », attendre encore 400 ms est du
        silence pur — le premier poste de latence de la boucle, devant le
        modèle. Et quand elle finit par « donc… », 800 ms ne suffisent PAS :
        couper là, c'est répondre à une phrase encore en construction.
        """
        texte, couvre = self._endpoint_hint()
        if not texte:
            return END_OF_TURN_S
        verdict = classify_endpoint(texte)
        if verdict == "hesitation":
            return HESITATION_END_S
        if verdict == "complete" and couvre:
            return SEMANTIC_END_S
        return END_OF_TURN_S

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
            if self._spec_llm is not None:
                # La génération en vol répond à une phrase qui n'était pas
                # finie. On l'abandonne — même coût qu'un barge-in : le flux
                # court jusqu'à son plafond de jetons, personne ne le lit.
                logger.info("local voice timing: stage=spec_llm outcome=discarded")
                self._spec_llm.abort()
                self._spec_llm = None
            if not self._in_speech and self._preroll:
                # The turn's first loud frame: everything quieter that came
                # just before it is the word's real beginning.
                self._buffer.extend(self._preroll)
                self._preroll.clear()
            self._in_speech = True
            self._silence_samples = 0
            self._speech_samples += len(pcm16) // 2
            self._buffer.extend(pcm16)
            self._speech_end_mark = len(self._buffer)
            await self._pump_partial()
            return

        if not self._in_speech:
            # Leading silence is not buffered wholesale — but its tail end is
            # where the next word's onset lives, so it feeds the ring.
            self._feed_preroll(pcm16)
            return

        self._buffer.extend(pcm16)
        self._silence_samples += len(pcm16) // 2

        # Un partiel encore en vol à la fin de la parole atterrit ici ; son
        # verdict décide du seuil de fin de tour quelques trames plus bas.
        await self._harvest_partial()

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

        # Dès que la transcription spéculative atterrit, lancer la
        # génération sur le silence restant. Le gain est l'écart entre
        # « transcription connue » et « tour clos » — jusqu'à ~0,3 s sur un
        # tour normal, ~0,6 s après une hésitation. Si la parole reprend, la
        # branche parlée jette la file plus haut ; toute file qui survit
        # jusqu'à la fin du tour décrit donc l'énoncé entier.
        if (
            self._spec_llm is None
            and self._llm is not None
            and self._speculative is not None
            and self._speculative[1].done()
        ):
            try:
                spec_text = (self._speculative[1].result() or "").strip()
            except BaseException:  # noqa: BLE001 - annulation comprise
                spec_text = ""
            # La spéculation subit la MÊME toilette que le tour réel — le nom
            # de l'assistant retiré. Sans ça, « Diapason, ouvre X » spéculait
            # sur le texte avec nom, le tour réel arrivait sans, et la
            # comparaison jetait la réponse préparée : le premier jeton se
            # payait deux fois précisément sur le mode d'adresse principal
            # (Atlas, 24 août 2026).
            if spec_text and mentions_assistant_name(spec_text):
                spec_text = strip_assistant_name(spec_text) or spec_text
            if spec_text and not self._speculation_pointless(spec_text):
                spec = _SpecTurn(spec_text)
                spec.source = self._llm(self._turn_messages(spec_text))
                spec.drainer = asyncio.get_running_loop().create_task(
                    self._drain_speculative(spec, spec.source)
                )
                self._spec_llm = spec
                logger.info("local voice timing: stage=spec_llm outcome=started")

        if self._silence_samples >= int(self._end_of_turn_s() * INPUT_RATE):
            utterance = bytes(self._buffer)
            had_speech = self._speech_samples >= int(MIN_SPEECH_S * INPUT_RATE)
            # Hand over the speculative result only if it covers everything
            # heard: trailing silence grows the buffer, so equality is on the
            # snapshot boundary having remained the end of speech.
            speculative = self._speculative
            self._speculative = None
            spec_llm = self._spec_llm
            self._spec_llm = None
            self._buffer.clear()
            self._speech_samples = 0
            self._silence_samples = 0
            self._in_speech = False
            self._drop_partial()
            if had_speech:
                early = speculative[1] if speculative is not None else None
                self._respond_task = asyncio.get_running_loop().create_task(
                    self._respond(utterance, early_stt=early, spec_llm=spec_llm)
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
        spec_llm: Optional[_SpecTurn] = None,
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
            await self._dispatch_text(
                text,
                turn_started=turn_started,
                spec_llm=spec_llm,
                utterance=bytes(utterance),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the UI must hear about it
            logger.exception("local voice turn failed")
            await self._queue.put(SessionEvent(kind="error", detail=str(exc)))
        finally:
            # 12 septembre 2026 : un tour vide, ignoré ou interrompu AVANT
            # le modèle échappait au finally de _respond_to_text. Son calcul
            # spéculatif continuait alors à occuper l'unique créneau Ollama.
            if spec_llm is not None:
                spec_llm.abort()

    def _voice_lock_actif(self) -> bool:
        if self._voice_lock is None:
            try:
                from diapason.core.config import load_config

                rt = load_config().speech.realtime
                self._voice_lock = bool(getattr(rt, "voice_lock", True))
            except Exception:  # noqa: BLE001 - sans config, verrou par défaut
                self._voice_lock = True
        return self._voice_lock

    def _magasin_traces(self) -> Any:
        """Le magasin d'historique, résolu une fois. None = traces coupées."""
        if self._magasin_traces_resolu:
            return self._magasin_traces_obj
        self._magasin_traces_resolu = True
        try:
            from diapason.core.config import load_config
            from diapason.traces.store import TraceStore

            config = load_config()
            if getattr(config.traces, "enabled", False):
                self._magasin_traces_obj = TraceStore(config.traces.db_path)
        except Exception:  # noqa: BLE001 - l'historique est un bonus, la voix prime
            logger.debug("voice: traces indisponibles", exc_info=True)
            self._magasin_traces_obj = None
        return self._magasin_traces_obj

    def _journaliser_echange(
        self, question: str, reponse: str, *, duree_s: float = 0.0
    ) -> None:
        """L'échange vocal abouti rejoint traces.db, étiqueté agent='voice'.

        Demandé le 23 août 2026 : la voix ne laissait AUCUNE persistance
        serveur, donc la consolidation nocturne ne relisait que le chat —
        une mémoire qui rate le mode principal d'usage. record_response_trace
        est best-effort : jamais une exception dans le chemin de la parole.
        """
        if question.strip() and reponse.strip() and self._sur_echange is not None:
            try:
                self._sur_echange(question.strip(), reponse.strip())
            except Exception:  # noqa: BLE001 - la mémoire est un bonus, la voix prime
                logger.warning(
                    "voice: échange non transmis à la mémoire", exc_info=True
                )
        magasin = self._magasin_traces()
        if magasin is None or not question.strip() or not reponse.strip():
            return
        from diapason.traces.collector import record_response_trace

        fin = time.time()
        record_response_trace(
            magasin,
            query=question.strip(),
            result=reponse.strip(),
            model=str(self._model or ""),
            engine="ollama",
            agent="voice",
            started_at=fin - max(0.0, float(duree_s)),
            ended_at=fin,
            # Les postes du tour (ttft, prefill, tts, premier audio…) : la
            # consolidation nocturne et un simple sqlite peuvent enfin voir
            # OÙ la voix perd ses secondes, au lieu de régresser à l'oreille.
            metadata={"latence": dict(self._mesures)} if self._mesures else None,
        )

    async def _dispatch_text(
        self,
        text: str,
        *,
        turn_started: float,
        spec_llm: Optional[_SpecTurn] = None,
        utterance: Optional[bytes] = None,
    ) -> None:
        nomme = mentions_assistant_name(text)
        engagee = time.monotonic() < self._engagee_jusqua
        if not nomme and not engagee:
            # Personne ne nous parle : un tiers, la télévision, le bruit.
            # Ni réponse, ni affichage — remplir le fil avec le dialogue d'un
            # film serait aussi impoli que d'y répondre. Une trace sobre au
            # journal, pour pouvoir diagnostiquer sans écouter personne.
            logger.info("voice turn ignored (not addressed): %d chars", len(text))
            return
        # L'EMPREINTE VOCALE tranche après le nom : la garde par le nom
        # filtre le film et le bruit, elle ne filtre pas un tiers qui DIT
        # « Diapason ». Demandé le 23 août 2026 : ne répondre qu'à la voix du
        # propriétaire. Tant que le profil n'est pas nourri (cinq tours
        # adressés), chaque tour adressé l'enrôle en silence ; ensuite le
        # verrou s'arme. Le doute profite au propriétaire — un faux rejet
        # rendrait l'assistant sourd à son maître.
        if utterance is not None and self._voice_lock_actif():
            from diapason.speech.speaker_id import get_verifier

            verifier = get_verifier()
            if verifier.arme:
                score, proprietaire = await asyncio.to_thread(
                    verifier.verify, utterance
                )
                if not proprietaire:
                    logger.info(
                        "voice turn ignored (unknown voice, score=%.2f): %d chars",
                        score,
                        len(text),
                    )
                    return
            else:
                await asyncio.to_thread(verifier.enroll, utterance)
                logger.info(
                    "voice enrollment: %d/%d samples",
                    verifier.echantillons,
                    5,
                )
        # Chaque tour adressé prolonge la conversation ; dire le nom rouvre
        # une conversation éteinte.
        self._engagee_jusqua = time.monotonic() + ADDRESS_WINDOW_S
        # Le cliché du bureau se rafraîchit EN PARALLÈLE du tour (~100 ms
        # d'osascript) : le tour ne lit que le cache, jamais l'osascript.
        # La référence est gardée, sinon la tâche part au ramasse-miettes.
        try:
            from diapason.desktop.etat_bureau import etat_du_bureau

            self._tache_etat_bureau = asyncio.create_task(
                asyncio.to_thread(etat_du_bureau)
            )
        except Exception:  # noqa: BLE001 - la perception est un bonus
            pass
        if nomme:
            text = strip_assistant_name(text)
            if not text:
                # « Diapason ? » tout seul : on signale qu'on écoute.
                text = "Oui ?"
        await self._queue.put(
            SessionEvent(kind="transcript", role="user", text=text, final=True)
        )
        if is_stop_phrase(text):
            # They asked for quiet. The barge-in already silenced playback;
            # answering would be one more sentence of exactly what they asked
            # to stop. La spéculation en vol est tuée, pas seulement ignorée.
            if spec_llm is not None:
                spec_llm.abort()
            return
        if await self._try_fast_voice_action(text, turn_started=turn_started):
            # Une action directe n'a pas besoin de la génération spéculative.
            # Avant, « la file abandonnée court[ait] jusqu'à son plafond » —
            # c'était le zombie qui bloquait le créneau -np 1 du tour suivant.
            if spec_llm is not None:
                spec_llm.abort()
            return
        await self._respond_to_text(text, already_queued=True, spec_llm=spec_llm)

    async def _try_fast_voice_action(self, text: str, *, turn_started: float) -> bool:
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
        # L'ENCHAÎNEMENT, mains libres : « ouvre l'App Store » puis
        # « recherche-moi des jeux » — sans redire où. Une recherche nue qui
        # suit une ouverture s'applique à ce qui vient d'être ouvert, pas à
        # Google. C'est le scénario dicté mot pour mot le 23 août 2026.
        if action.kind == "search" and self._derniere_app_ouverte:
            from diapason.tools.app_actions import _normaliser_app

            if _normaliser_app(self._derniere_app_ouverte) is not None:
                from diapason.desktop.voice_commands import VoiceAction

                action = VoiceAction(
                    kind="app_search",
                    target=action.target,
                    raw=action.raw,
                    extra={"app": self._derniere_app_ouverte},
                )
        # ``open_anything`` is intentionally left to the regular tool path:
        # its target may be an app, file, folder or web page and a failed
        # deterministic guess must not swallow the model's richer resolver.
        if action.kind not in {"focus_app", "open_uri", "search", "app_search"}:
            return False

        action_started = time.monotonic()
        result = await asyncio.to_thread(execute_voice_action, action)
        # Symétrique du journal des outils LLM : sans cette ligne, un échec
        # du chemin rapide ne laissait AUCUNE trace côté serveur, et chaque
        # diagnostic commençait à l'aveugle.
        logger.warning(
            "voice fast action %s target=%s ok=%s",
            action.kind,
            action.target,
            bool(result.get("success")),
        )
        if not result.get("handled"):
            return False
        success = bool(result.get("success"))
        if success and action.kind == "focus_app":
            self._derniere_app_ouverte = str(action.target or "")
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
        if action.kind == "app_search":
            verb = "Je cherche"
            target = f"{action.target} dans {str(extra.get('app') or 'l’application')}"
        else:
            verb = "Je lance" if extra.get("play") else "J’ouvre"
        response = (
            f"{verb} {target}." if success else f"Je n’ai pas pu ouvrir {target}."
        )
        # Quand l'outil a constaté l'état (« déjà devant toi », « remise
        # devant », « lancée »), sa phrase dit la vérité — elle prime sur
        # le verbe générique (demandé le 23 août 2026 : la parole suit la
        # réalité, jamais l'inverse).
        if success and result.get("etat") and result.get("detail"):
            response = str(result["detail"])
        await self._speak_sentence(response, spoken)
        self._history.append({"role": "assistant", "content": response})
        del self._history[:-16]
        self._journaliser_echange(
            text, response, duree_s=time.monotonic() - action_started
        )
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
        self,
        text: str,
        *,
        already_queued: bool = False,
        spec_llm: Optional[_SpecTurn] = None,
    ) -> None:
        response_started = time.monotonic()
        self._response_started = response_started
        self._first_audio_logged = False
        tokens: Optional["asyncio.Queue[Any]"] = None
        try:
            if spec_llm is not None and spec_llm.text != text:
                # 12 septembre 2026 : une transcription révisée lançait la
                # bonne réponse sans arrêter la mauvaise avant la FIN du
                # tour. Avec un seul créneau, la bonne attendait la mauvaise.
                spec_llm.abort()
                spec_llm = None
                logger.info("local voice timing: stage=spec_llm outcome=mismatch")
            await self._wait_warm()
            assert self._llm is not None and self._tts is not None
            if not already_queued:
                await self._queue.put(
                    SessionEvent(kind="transcript", role="user", text=text, final=True)
                )
            # The per-turn transcript: history plus whatever tool exchanges
            # this turn produces. Tool messages stay HERE and never enter the
            # long-term history — a session that opened three apps would
            # otherwise drag those payloads through every later turn.
            # Assemblé AVANT la mutation de l'historique, par le même chemin
            # que la spéculation.
            # 21/09/2026 : les gardes d'actualité du chat, à la voix. Une
            # question d'actualité (ou « vérifie ça ») reçoit sa consigne au
            # tour courant (dans _turn_messages, spéculation comprise) ; la
            # fraîcheur, la page du poste et la note avant rédaction suivent ;
            # et si rien n'a été vérifié, la voix le DIT en fin de tour au
            # lieu de laisser passer « Justin Trudeau ».
            tour_actualite = self._tour_actualite(text)
            messages = self._turn_messages(text)
            index_note: Optional[int] = None
            self._history.append({"role": "user", "content": text})
            # A cap on history keeps a long session from slowly pushing the
            # first-token latency past conversational.
            del self._history[:-16]
            spoken: List[str] = []
            debut_passe = 0
            tool_notes: List[str] = []
            relance_promesse = False
            self._budget.reset()
            # Bounded by the budget plus the final text-only round, so a model
            # that asks for tools forever cannot loop us forever.
            for _round in range(self._budget.max_steps + 1):
                if _round == 0 and spec_llm is not None and spec_llm.text == text:
                    # La génération a démarré pendant le silence de fin de
                    # tour ; ses premiers jetons sont déjà dans la file. Le
                    # texte doit correspondre exactement : la transcription
                    # peut être révisée avant la confirmation du tour.
                    tokens = spec_llm.replay_queue()
                    if spec_llm.first_sentence and spec_llm.first_audio:
                        self._spec_audio = (
                            spec_llm.first_sentence,
                            spec_llm.first_audio,
                        )
                    logger.info("local voice timing: stage=spec_llm outcome=adopted")
                else:
                    tokens = self._llm(list(messages))
                pending = ""
                tool_calls: List[dict] = []
                debut_passe = len(spoken)
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
                if (
                    tour_actualite is not None
                    and not tool_calls
                    and not tour_actualite.recherche_tentee
                    and not tour_actualite.relance_faite
                    and not relance_promesse
                ):
                    # Le premier passage a parlé sans chercher (« je vais
                    # vérifier… », ou la réponse de mémoire). La parole est
                    # sortie ; la livraison suit, UNE fois — revue du 21/09 :
                    # « Je vais vérifier ça en ligne. Je le dis de mémoire,
                    # sans avoir pu vérifier en ligne. »
                    messages.extend(
                        actualite_vocale.relance(tour_actualite, " ".join(spoken))
                    )
                    logger.warning("voice actuality answer without search, retrying")
                    continue
                if (
                    tour_actualite is not None
                    and not tool_calls
                    and actualite_vocale.relance_possible(
                        tour_actualite, " ".join(spoken[debut_passe:])
                    )
                ):
                    # « Je n'ai pas trouvé le vainqueur » après une recherche :
                    # le code lit la source la plus prometteuse et le modèle
                    # reprend d'après elle, une fois (banc du 21/09). Jugé sur
                    # cette passe seule : un aveu dit AVANT la recherche ne
                    # fait pas relire une page après la bonne réponse.
                    passe = " ".join(spoken[debut_passe:])
                    lire, lectures = self._lecteur_budgete()
                    # L'accusé se décide AVANT de parler : une source à lire
                    # et de quoi la payer. « Je lis la source. » puis rien
                    # (revue du 21/09, 22 h) disait une lecture qui n'avait
                    # pas lieu.
                    annonce = (
                        actualite_vocale.lecture_possible(tour_actualite)
                        and self._budget.allow()
                    )
                    if annonce:
                        await self._speak_sentence(
                            actualite_vocale.ACCUSE_LECTURE, spoken
                        )
                    reprise = await asyncio.to_thread(
                        actualite_vocale.relance_apres_non_reponse,
                        tour_actualite,
                        passe,
                        lire if annonce else None,
                        self._budget.allow,
                    )
                    await self._annoncer_lectures(lectures)
                    if reprise:
                        messages.extend(reprise)
                        logger.warning(
                            "voice actuality non-answer, reading then retrying"
                        )
                        continue
                    if annonce:
                        await self._speak_sentence(
                            actualite_vocale.ACCUSE_LECTURE_RATEE, spoken
                        )
                if not tool_calls or not self._enable_tools:
                    # La PROMESSE SANS L'ACTE (23 août 2026) : « d'accord, je
                    # cherche du R&B sur YouTube pour toi » — dit, rien fait.
                    # Un tour qui annonce une action au présent sans avoir
                    # appelé d'outil est repris UNE fois, avec sommation. La
                    # promesse est déjà sortie des haut-parleurs ; l'acte la
                    # suit, et l'usager entend promesse puis livraison.
                    if (
                        self._enable_tools
                        and not relance_promesse
                        and not tool_notes
                        and _est_une_promesse_sans_acte(" ".join(spoken))
                    ):
                        relance_promesse = True
                        messages.append(
                            {
                                "role": "assistant",
                                "content": " ".join(spoken).strip(),
                            }
                        )
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "Tu viens d'ANNONCER une action sans "
                                    "appeler d'outil — c'est une promesse en "
                                    "l'air. Appelle MAINTENANT l'outil qui "
                                    "convient (open_anything pour jouer ou "
                                    "ouvrir quelque chose), puis confirme en "
                                    "une phrase courte, sans répéter ton "
                                    "annonce."
                                ),
                            }
                        )
                        logger.warning(
                            "voice promise without action, retrying with a summons"
                        )
                        continue
                    break
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": tool_calls,
                    }
                )
                if _round == 0 and not spoken:
                    # L'accusé OPTIMISTE (Atlas, 24 août 2026) : sur un geste
                    # local sûr, un accusé pré-synthétisé part TOUT DE SUITE
                    # — la deuxième passe LLM (1-2,5 s, le plus gros silence
                    # du tour) se déroule pendant qu'il joue.
                    await self._emit_optimistic_ack(tool_calls, spoken)
                if tour_actualite is not None and not spoken:
                    noms_appeles = {
                        (c.get("function") or {}).get("name", "") for c in tool_calls
                    }
                    if "web_search" in noms_appeles:
                        # Une recherche et une lecture font une à trois
                        # secondes de silence que rien ne signalait (21/09).
                        await self._speak_sentence(
                            actualite_vocale.ACCUSE_RECHERCHE, spoken
                        )
                for call in tool_calls:
                    debut_outil = time.monotonic()
                    reply = await self._run_tool(call, tour=tour_actualite)
                    logger.info(
                        "local voice timing: stage=tool_exec tool=%s ms=%.0f",
                        (call.get("function") or {}).get("name", ""),
                        (time.monotonic() - debut_outil) * 1000,
                    )
                    messages.append(reply)
                    tool_notes.append(_tool_note(call, reply))
                if tour_actualite is not None:
                    # Ce que le code sait des sources, dit avant la rédaction
                    # — et une note nouvelle REMPLACE la précédente.
                    note = actualite_vocale.note(tour_actualite)
                    if index_note is not None:
                        del messages[index_note]
                        index_note = None
                    if note is not None:
                        messages.append(note)
                        index_note = len(messages) - 1

            if tour_actualite is not None:
                # §100, prononcé : de mémoire, ou en désaccord avec les sources.
                dit = " ".join(spoken).strip()
                derniere_passe = " ".join(spoken[debut_passe:]).strip()
                epilogue = actualite_vocale.epilogue(
                    tour_actualite, dit, derniere_passe
                )
                # Le même niveau que le chat, en pastille (22/09/2026). Jugé
                # sur ce que le MODÈLE a dit, pris avant l'épilogue :
                # `_speak_sentence` ajoute celui-ci à `spoken`, et juger
                # « Attention : les sources désignent Mark Carney… » reviendrait
                # à juger le verdict au lieu de la réponse.
                niveau = actualite_vocale.niveau_vocal(
                    tour_actualite, dit, derniere_passe
                )
                if epilogue:
                    await self._speak_sentence(epilogue, spoken)
                await self._queue.put(
                    SessionEvent(kind="verification", verification=niveau)
                )
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
                self._journaliser_echange(
                    text, answer, duree_s=time.monotonic() - response_started
                )
            self._mesures.clear()
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
        finally:
            # Quoi qu'il arrive — fin normale, barge-in, fermeture — aucun
            # producteur ne survit au tour : un flux qui a fini ignore
            # l'abort, un flux en vol libère le créneau -np 1. getattr :
            # les fakes des tests sont des files nues.
            arret = getattr(tokens, "abort", None)
            if arret is not None:
                arret()
            if spec_llm is not None:
                arret_spec = getattr(spec_llm, "abort", None)
                if arret_spec is not None:
                    arret_spec()

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

    async def _run_tool(
        self, call: dict, tour: Optional["actualite_vocale.TourVocal"] = None
    ) -> dict:
        """Execute one tool call and shape the result for the transcript.

        The result goes two ways at once: a "tool" event so the panel shows
        what just happened, and a role="tool" message so the model can build
        its answer on what the tool actually returned.

        Sur un tour d'actualité (``tour``), les arguments de web_search sont
        complétés par le code (fraîcheur), et la page du poste est lue et
        jointe au résultat — la lecture est annoncée au panneau comme un
        outil, rien ne se fait en cachette (§5).
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
        if tour is not None:
            args = actualite_vocale.preparer_appel(tour, name, args)
            deja = actualite_vocale.deja_lue(tour, name, args)
            if deja is not None:
                return {
                    "role": "tool",
                    "tool_name": name,
                    "content": json.dumps(deja, ensure_ascii=False),
                }
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

        from diapason.server.details_outils import details_du_fil

        await self._queue.put(
            SessionEvent(
                kind="tool",
                tool_name=name,
                tool_ok=bool(result.get("ok")),
                detail=str(result.get("error") or "")[:200],
                # Le même calcul qu'au chat, jamais une seconde copie : `0`
                # doit passer, et un booléen n'est pas un compte.
                tool_details=details_du_fil(result) or None,
            )
        )
        if tour is not None and self._tool_executor is not None:
            lire, lectures = self._lecteur_budgete()
            try:
                result = await asyncio.to_thread(
                    actualite_vocale.absorber_resultat, tour, name, args, result, lire
                )
            except Exception as exc:  # noqa: BLE001 - la recherche payée ne se perd pas
                logger.warning(
                    "voice actuality: reading failed: %s", exc, exc_info=True
                )
                lectures.append({"ok": False, "error": str(exc)})
            await self._annoncer_lectures(lectures)
        return {
            "role": "tool",
            "tool_name": name,
            "content": json.dumps(result, ensure_ascii=False, default=str),
        }

    def _lecteur_budgete(self):
        """Un lecteur de page pour le code, qui compte dans le budget du tour
        comme un appel du modèle (revue du 21/09 : la lecture automatique
        passait à côté) et garde chaque page lue pour l'annoncer au panneau."""
        lectures: list[dict] = []
        executeur = self._tool_executor
        budget = self._budget

        def lire(nom: str, arguments: dict) -> dict:
            if executeur is None:
                page = {"ok": False, "error": "tools unavailable"}
            elif not budget.allow():
                page = {"ok": False, "error": "Voice tool budget exceeded"}
            else:
                budget.consume()
                page = executeur(nom, arguments)
            lectures.append(page)
            return page

        return lire, lectures

    async def _annoncer_lectures(self, lectures: list) -> None:
        for page in lectures:
            await self._queue.put(
                SessionEvent(
                    kind="tool",
                    tool_name="web_read",
                    tool_ok=bool(page.get("ok")),
                    detail=str(page.get("error") or page.get("content") or "")[:200],
                )
            )

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

    async def _emit_optimistic_ack(
        self, tool_calls: List[dict], spoken: List[str]
    ) -> None:
        """Un accusé pré-rendu part pendant que le geste s'exécute.

        Seulement pour les gestes locaux SÛRS (FAST_ACK_TOOL_IDS) : tous
        sans confirmation, exécution sous la seconde. Un envoi de message ou
        une suppression n'a pas d'accusé optimiste — la cloche et le constat
        gardent le dernier mot.
        """
        try:
            from diapason.speech.realtime.tools import FAST_ACK_TOOL_IDS
        except Exception:  # noqa: BLE001 - l'accusé est un bonus
            return
        noms = [(c.get("function") or {}).get("name", "") for c in tool_calls]
        if not noms or not all(n in FAST_ACK_TOOL_IDS for n in noms):
            return
        accuses = _SHARED.get("acks") or {}
        if not accuses:
            return
        phrases = list(accuses)
        phrase = phrases[self._ack_suivant % len(phrases)]
        self._ack_suivant += 1
        pcm = accuses[phrase]
        spoken.append(phrase)
        duration = len(pcm) / 2 / OUTPUT_RATE
        now = time.monotonic()
        self._speaking_until = max(now, self._speaking_until) + duration
        await self._queue.put(
            SessionEvent(
                kind="audio",
                audio_b64=base64.b64encode(pcm).decode("ascii"),
                sample_rate=OUTPUT_RATE,
            )
        )
        self._marquer_premier_audio(now)
        logger.info("local voice timing: stage=ack phrase=%r", phrase)

    def _marquer_premier_audio(self, quand: float) -> None:
        if self._first_audio_logged or self._response_started is None:
            return
        self._first_audio_logged = True
        ms = (quand - self._response_started) * 1000
        self._mesures["first_audio_ms"] = round(ms)
        logger.info("local voice timing: stage=first_audio ms=%.0f", ms)

    async def _speak_sentence(self, sentence: str, spoken: List[str]) -> None:
        assert self._tts is not None
        sentence = speakable(sentence)
        if not sentence:
            # A chunk that was all emoji: nothing to say, nothing to record.
            return
        pcm: Optional[bytes] = None
        spec_audio, self._spec_audio = self._spec_audio, None
        if spec_audio is not None and spec_audio[0] == sentence:
            # La spéculation a déjà synthétisé exactement cette phrase
            # pendant le silence de fin de tour ; la tâche est peut-être
            # même déjà finie. Un échec quelconque retombe sur la synthèse
            # normale — le cache est un raccourci, jamais un point de panne.
            try:
                pcm = await spec_audio[1]
            except BaseException:  # noqa: BLE001 - annulation comprise
                pcm = None
        spec_hit = pcm is not None
        if pcm is None:
            debut_tts = time.monotonic()
            pcm = await asyncio.to_thread(self._tts, sentence)
            logger.info(
                "local voice timing: stage=tts ms=%.0f spec_hit=0",
                (time.monotonic() - debut_tts) * 1000,
            )
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
            self._marquer_premier_audio(now)
            if spec_hit:
                logger.info("local voice timing: stage=tts ms=0 spec_hit=1")

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
        if self._spec_llm is not None:
            self._spec_llm.abort()
            self._spec_llm = None
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
