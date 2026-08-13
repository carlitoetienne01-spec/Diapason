"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, List, Optional

from diapason.core.registry import SpeechRegistry
from diapason.speech._stubs import Segment, SpeechBackend, TranscriptionResult

# Keep CLI/server startup free of the heavy AV/numpy/CTranslate2 chain. These
# names remain module globals so tests and embedders can inject implementations.
_UNLOADED = object()
WhisperModel: Any = _UNLOADED
ctranslate2: Any = _UNLOADED

logger = logging.getLogger(__name__)

# What Whisper's front end expects. A bare sample array carries no rate, so
# handing it audio at any other rate would silently transpose the speech.
WHISPER_RATE = 16_000

# How sure Whisper must be before a detected language is reused for the rest
# of the session, and how much audio that verdict must be based on. Language
# detection reads only the first window, so a two-second "oui, voilà" is
# exactly the case it gets wrong.
LANGUAGE_LATCH_CONFIDENCE = 0.85
LANGUAGE_LATCH_SECONDS = 2.0


def _decode_pcm_wav(audio: bytes):
    """Decode 16 kHz mono 16-bit PCM WAV to a float32 array, or None.

    Deliberately narrow: it accepts exactly the shape the dictation path
    already produces and refuses everything else, so the caller falls back to
    the demuxer rather than this function guessing at a conversion. Returning
    None is the safe answer — it costs a temp file, never a wrong result.
    """
    try:
        import io
        import wave

        import numpy as np

        with wave.open(io.BytesIO(audio)) as wav:
            if (
                wav.getcomptype() != "NONE"
                or wav.getsampwidth() != 2
                or wav.getnchannels() != 1
                or wav.getframerate() != WHISPER_RATE
            ):
                return None
            frames = wav.readframes(wav.getnframes())
    except Exception:  # noqa: BLE001 - not a WAV we understand; use the demuxer
        return None
    if not frames:
        return None
    import numpy as np

    return np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "float16",
        use_dictionary_hints: bool = True,
        language: str = "",
        realtime: bool = False,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Optional[Any] = None
        self._last_error: Optional[str] = None
        # Configured language, or "auto" / "" to detect.
        self._language = (language or "").strip()
        # Whisper runs a separate detection pass whenever no language is
        # given, and on this machine that pass costs roughly as much as the
        # decode itself — measured 1.90 s -> 1.13 s per 4-second French clip
        # once the language is known. Detection is also least reliable
        # exactly where dictation lives: a two-second utterance.
        #
        # So detect ONCE, then reuse. The first utterance of a session pays
        # for it, every later one is fast, and nobody has to guess a locale
        # or edit a config file to get the speedup.
        self._detected: Optional[str] = None
        # (value,) so a cached "no hotwords" is distinguishable from "unread".
        self._hotwords_cache: Optional[tuple] = None
        self._hotwords_stamp: int = -1
        # Bias recognition toward the user's own vocabulary. The dictionary
        # already fixed mistakes AFTER the fact (apply_dictionary in
        # dictate_polish); ``transcription_hints`` was written to fix them
        # BEFORE, and had no caller at all. Feeding it to faster-whisper's
        # ``hotwords`` is what stops a name like "Carlito" coming back as
        # "Karli 2-1" in the first place — a post-hoc replacement cannot
        # recover a name the recogniser never proposed.
        self._use_dictionary_hints = use_dictionary_hints
        # Realtime turns are short and already segmented by the microphone
        # gate. Greedy decoding is much faster here, while Silero VAD rejects
        # the low-level noise that Whisper otherwise turns into stock phrases
        # or hotwords (the observed silent turn became "Google Chrome").
        self._realtime = bool(realtime)

    # Brand names the intent layer keys on. "youtube" absent from the
    # transcript means no YouTube intent ever fires — a garble like
    # "yutihub" silently downgrades « joue X sur YouTube » to a Google
    # search. Small and fixed on purpose: hotwords bias decoding, and a
    # long list would bend ordinary dictation toward it.
    _BASE_HOTWORDS = (
        "YouTube Spotify Netflix Amazon Gmail WhatsApp Google Chrome Safari "
        "App Store Diapason"
    )

    def _hotwords(self) -> Optional[str]:
        """Brand vocabulary plus the personal dictionary, or None.

        Cached against the dictionary file's mtime: this used to re-read and
        JSON-parse the file inside every transcription, on the one code path
        where the user is sitting there waiting. Keying on mtime keeps an
        edit picked up on the next utterance without paying for the read on
        every one.
        """
        if not self._use_dictionary_hints:
            return None
        try:
            from diapason.speech.dictation_dictionary import (
                default_dictionary_path,
                transcription_hints,
            )

            try:
                stamp = default_dictionary_path().stat().st_mtime_ns
            except OSError:
                stamp = 0  # no dictionary yet; still worth caching the miss
            if self._hotwords_cache is not None and self._hotwords_stamp == stamp:
                return self._hotwords_cache[0]

            words = transcription_hints()
            value = " ".join([self._BASE_HOTWORDS, *words])
            self._hotwords_cache = (value,)
            self._hotwords_stamp = stamp
            return value
        except Exception:  # noqa: BLE001 - hints are an optimisation, never required
            logger.debug("could not build transcription hints", exc_info=True)
            # A broken dictionary must not take the brand vocabulary down
            # with it — intent detection depends on it.
            return self._BASE_HOTWORDS

    def preload(self) -> bool:
        """Build the model now rather than on the user's first keypress.

        Under the LaunchAgent the service starts at login and then sits idle,
        so without this the first dictation of the day pays several seconds
        of model construction while the user is already talking.
        """
        try:
            self._ensure_model()
            return True
        except Exception:  # noqa: BLE001 - stay usable; the first call retries
            logger.debug("model preload failed", exc_info=True)
            return False

    def _effective_language(self, requested: Optional[str]) -> Optional[str]:
        """Which language to decode as, or None to let Whisper detect.

        Precedence: the per-call argument, then the configured language, then
        whatever was detected earlier in this session. ``"auto"`` is an
        explicit request to detect every time — the escape hatch for someone
        who genuinely switches language mid-session and would rather pay for
        it than be pinned to the first thing they said.
        """
        for candidate in (requested, self._language):
            value = (candidate or "").strip()
            if value.lower() == "auto":
                return None
            if value:
                return value
        return self._detected

    def _resolve_compute_type(self) -> str:
        """Pick a CTranslate2 compute type supported by the configured device."""
        global ctranslate2

        if ctranslate2 is _UNLOADED:
            try:
                import ctranslate2 as _ctranslate2

                ctranslate2 = _ctranslate2
            except ImportError:
                ctranslate2 = None
        if ctranslate2 is None:
            return self._compute_type

        try:
            supported = set(ctranslate2.get_supported_compute_types(self._device))
        except Exception as exc:
            logger.debug(
                "Could not inspect CTranslate2 compute types for %s: %s",
                self._device,
                exc,
            )
            return self._compute_type

        if self._compute_type in supported:
            return self._compute_type

        preferences = (
            ("int8", "float32", "int8_float32", "int16")
            if self._compute_type == "float16"
            else ("float32", "int8", "int8_float32", "int16")
        )
        fallback = next((value for value in preferences if value in supported), None)
        if fallback is None:
            return self._compute_type

        # INFO, not WARNING: on Apple Silicon this fallback fires on every
        # single run (CTranslate2 has no float16 CPU path), so it is expected
        # behaviour, not an anomaly. As a WARNING it printed into the middle
        # of every dictation session and read like something was broken.
        logger.info(
            "CTranslate2 compute_type=%r is not supported on device=%r; "
            "using %r instead",
            self._compute_type,
            self._device,
            fallback,
        )
        return fallback

    def _ensure_model(self) -> Any:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            global WhisperModel

            # Local-only refuses a SILENT first-use download. Constructing
            # WhisperModel fetches the weights over the network if they are not
            # cached; under [privacy] local_only that background fetch is the
            # very thing the mode forbids. An already-cached model is fine
            # (nothing leaves), and `diapason model pull` is the explicit path.
            from diapason.core.local_mode import local_only
            from diapason.speech.model_integrity import (
                faster_whisper_cached,
                guard_implicit_download,
            )

            guard_implicit_download(
                self._model_size,
                local_only=local_only(),
                already_cached=faster_whisper_cached(self._model_size),
            )

            if WhisperModel is _UNLOADED:
                try:
                    from faster_whisper import WhisperModel as _WhisperModel

                    WhisperModel = _WhisperModel
                except ImportError:
                    WhisperModel = None
            if WhisperModel is None:
                self._last_error = (
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra desktop"
                )
                raise ImportError(self._last_error)

            compute_type = self._resolve_compute_type()
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=compute_type,
            )
        self._last_error = None
        return self._model

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        try:
            model = self._ensure_model()

            kwargs = {}
            effective = self._effective_language(language)
            if effective:
                kwargs["language"] = effective
            hotwords = self._hotwords()
            if hotwords:
                kwargs["hotwords"] = hotwords
            if self._realtime:
                kwargs.update(
                    {
                        "beam_size": 1,
                        "best_of": 1,
                        "condition_on_previous_text": False,
                        "vad_filter": True,
                        "vad_parameters": {
                            "threshold": 0.5,
                            "min_speech_duration_ms": 250,
                            "min_silence_duration_ms": 160,
                            "speech_pad_ms": 80,
                        },
                    }
                )

            samples = _decode_pcm_wav(audio) if format.lstrip(".") == "wav" else None
            if samples is not None:
                # Straight from memory. The dictation path already holds a
                # float32 array; encoding it to WAV, writing it to disk and
                # having PyAV decode it back was a round trip to nowhere that
                # measured ~27% of the total transcription time.
                segments_iter, info = model.transcribe(samples, **kwargs)
                segments_list = list(segments_iter)
            else:
                # Anything else (mp3, m4a…) still needs a demuxer, and
                # faster-whisper takes a path for that. delete=False + manual
                # unlink: on Windows an open NamedTemporaryFile holds an
                # exclusive handle, so PyAV's reopen fails with EACCES.
                suffix = f".{format}" if not format.startswith(".") else format
                tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                try:
                    with tmp:
                        tmp.write(audio)
                    segments_iter, info = model.transcribe(tmp.name, **kwargs)
                    segments_list = list(segments_iter)
                finally:
                    try:
                        os.unlink(tmp.name)
                    except OSError as unlink_exc:
                        logger.debug(
                            "Could not remove temp audio file %s: %s",
                            tmp.name,
                            unlink_exc,
                        )
        except Exception as exc:
            self._last_error = str(exc)
            raise

        # Remember a detected language so the next utterance can skip the
        # detection pass — but only on evidence strong enough to bet a whole
        # session on.
        #
        # The two guards below exist because of a real failure: one uncertain
        # detection on a first short clip latched the session to English, and
        # every French sentence afterwards came back translated. Forcing the
        # wrong language is not a small error — Whisper does not refuse, it
        # renders the speech *as* that language. Re-detecting merely costs a
        # few hundred milliseconds, so the asymmetry decides the design.
        if not self._language and self._detected is None:
            probability = getattr(info, "language_probability", 0.0) or 0.0
            seconds = getattr(info, "duration", 0.0) or 0.0
            confident = probability >= LANGUAGE_LATCH_CONFIDENCE
            if confident and seconds >= LANGUAGE_LATCH_SECONDS:
                self._detected = getattr(info, "language", None)

        # Build result
        text = "".join(seg.text for seg in segments_list).strip()
        segments = [
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=None,
            )
            for seg in segments_list
        ]

        self._last_error = None
        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        try:
            self._ensure_model()
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug("Faster-Whisper health check failed: %s", exc)
            return False

    def last_error(self) -> Optional[str]:
        """Return the last model load or transcription error, if any."""
        return self._last_error

    def supported_formats(self) -> List[str]:
        """Supported audio formats (same as ffmpeg/Whisper)."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
