"""Always-on wake-word listener (local mic → Talk).

Backends:
- ``phrase_gate`` — energy/VAD + tiny Whisper STT + regex phrases (default)
- ``openwakeword`` — ML scores on PCM (pre-trained ``hey_jarvis`` or custom ONNX)
- ``auto`` — openWakeWord if installed, else phrase_gate

Default action: emit ``talk_open`` on ``local_trigger`` (open Talk orb).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from diapason.speech.wake_phrases import (
    DEFAULT_WAKE_VARIANTS,
    build_wake_pattern,
    has_wake_word,
)

logger = logging.getLogger(__name__)


@dataclass
class WakeListenConfig:
    sample_rate: int = 16000
    block_ms: int = 30
    channels: int = 1
    # Energy gate (phrase_gate)
    min_rms: float = 0.012
    speech_hold_s: float = 0.35
    silence_end_s: float = 0.55
    max_utterance_s: float = 2.8
    cooldown_s: float = 2.5
    phrases: tuple[str, ...] = field(default_factory=lambda: DEFAULT_WAKE_VARIANTS)
    action: str = "talk"  # talk | dictation | emit_only
    backend: str = "phrase_gate"  # phrase_gate | openwakeword | auto
    sensitivity: float = 0.5
    model_path: str = ""  # custom ONNX/tflite; empty → hey_jarvis pretrained


TranscribeFn = Callable[[bytes, int], str]  # pcm_s16le bytes, sample_rate → text


def _float_to_s16le(block) -> bytes:
    import numpy as np

    arr = np.asarray(block)
    if arr.ndim > 1:
        arr = np.mean(arr.astype(np.float64), axis=1)
    else:
        arr = arr.astype(np.float64)
    clipped = np.clip(arr, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


def default_transcribe_pcm(pcm: bytes, sample_rate: int) -> str:
    """Best-effort local STT (faster-whisper tiny). Returns '' if unavailable."""
    if not pcm:
        return ""
    try:
        import io
        import wave

        from faster_whisper import WhisperModel

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        buf.seek(0)
        model = getattr(default_transcribe_pcm, "_model", None)
        if model is None:
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            setattr(default_transcribe_pcm, "_model", model)
        segments, _info = model.transcribe(buf, language=None, beam_size=1)
        return " ".join(s.text for s in segments).strip()
    except Exception:
        logger.debug("wake STT unavailable", exc_info=True)
        return ""


def openwakeword_available() -> bool:
    try:
        import openwakeword  # noqa: F401
        from openwakeword.model import Model  # noqa: F401

        return True
    except Exception:
        return False


def _load_openwakeword_model(cfg: WakeListenConfig):
    """Return an openWakeWord Model or raise."""
    import openwakeword
    from openwakeword.model import Model

    try:
        openwakeword.utils.download_models()
    except Exception:
        logger.debug("openWakeWord model download skipped/failed", exc_info=True)

    model_path = (cfg.model_path or "").strip()
    if model_path:
        return Model(wakeword_models=[model_path], vad_threshold=0.3)

    # Prefers built-in hey_jarvis when present; else all pretrained
    try:
        return Model(wakeword_models=["hey_jarvis"], vad_threshold=0.3)
    except Exception:
        logger.debug("hey_jarvis model load failed; trying defaults", exc_info=True)
        return Model(vad_threshold=0.3)


def resolve_backend(requested: str) -> str:
    req = (requested or "phrase_gate").strip().lower()
    if req == "auto":
        return "openwakeword" if openwakeword_available() else "phrase_gate"
    if req in ("openwakeword", "oww", "ml"):
        if not openwakeword_available():
            raise ImportError(
                "openWakeWord not installed. "
                "Run: uv sync --extra speech-wake "
                "# or pip install openwakeword onnxruntime"
            )
        return "openwakeword"
    return "phrase_gate"


def wake_config_from_toml(
    *,
    cooldown: float | None = None,
    min_rms: float | None = None,
    phrases: str | None = None,
    backend: str | None = None,
) -> WakeListenConfig:
    """Build WakeListenConfig merging CLI overrides with [speech.wakeword]."""
    cfg = WakeListenConfig()
    try:
        from diapason.core.config import load_config

        w = load_config().speech.wakeword
        cfg.cooldown_s = float(w.cooldown_s)
        cfg.phrases = phrases_from_config(w.phrases)
        cfg.action = (w.action or "talk").strip() or "talk"
        cfg.backend = (w.backend or "phrase_gate").strip() or "phrase_gate"
        cfg.sensitivity = float(w.sensitivity)
        cfg.model_path = (w.model_path or "").strip()
    except Exception:
        logger.debug("wake config from toml unavailable", exc_info=True)

    if cooldown is not None:
        cfg.cooldown_s = float(cooldown)
    if min_rms is not None:
        cfg.min_rms = float(min_rms)
    if phrases:
        cfg.phrases = phrases_from_config(phrases)
    if backend:
        cfg.backend = backend.strip()
    return cfg


class WakeWordListener:
    """Mic loop: openWakeWord ML scores and/or STT phrase gate → callback."""

    def __init__(
        self,
        on_wake: Callable[[str], None],
        *,
        cfg: WakeListenConfig | None = None,
        once: bool = False,
        device: int | None = None,
        debug: bool = False,
        transcribe: TranscribeFn | None = None,
    ) -> None:
        self._on_wake = on_wake
        self._cfg = cfg or WakeListenConfig()
        self._once = once
        self._device = device
        self._debug = debug
        self._transcribe = transcribe or default_transcribe_pcm
        self._pattern = build_wake_pattern(self._cfg.phrases)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fired = False
        self._last_fire = 0.0
        self._resolved_backend = "phrase_gate"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="wake-listener", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def check_text(self, text: str) -> bool:
        """Unit-test / manual path: return True and invoke callback if wake."""
        if not has_wake_word(text, pattern=self._pattern):
            return False
        return self._fire(text)

    def _fire(self, label: str) -> bool:
        now = time.monotonic()
        if (now - self._last_fire) < self._cfg.cooldown_s:
            return False
        if self._once and self._fired:
            return False
        self._fired = True
        self._last_fire = now
        logger.info("Wake word detected: %r", label)
        try:
            self._on_wake(label)
        except Exception:
            logger.exception("Wake callback failed")
        return True

    def _run(self) -> None:
        try:
            self._resolved_backend = resolve_backend(self._cfg.backend)
        except ImportError as exc:
            logger.error("%s", exc)
            return

        if self._resolved_backend == "openwakeword":
            self._run_openwakeword()
        else:
            self._run_phrase_gate()

    def _run_openwakeword(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice + numpy required: pip install sounddevice numpy")
            return

        try:
            model = _load_openwakeword_model(self._cfg)
        except Exception:
            logger.exception("Failed to load openWakeWord; falling back to phrase_gate")
            self._run_phrase_gate()
            return

        # 80 ms frames = 1280 samples @ 16 kHz
        frame_samples = 1280
        threshold = float(self._cfg.sensitivity)
        logger.info(
            "Wake listener (openWakeWord) started threshold=%.2f cooldown=%.1fs",
            threshold,
            self._cfg.cooldown_s,
        )

        try:
            with sd.InputStream(
                device=self._device,
                samplerate=self._cfg.sample_rate,
                channels=self._cfg.channels,
                dtype="float32",
                blocksize=frame_samples,
            ) as stream:
                while not self._stop.is_set():
                    data, _ = stream.read(frame_samples)
                    pcm = np.frombuffer(_float_to_s16le(data), dtype=np.int16)
                    try:
                        scores = model.predict(pcm)
                    except Exception:
                        logger.debug("openWakeWord predict failed", exc_info=True)
                        continue
                    if not scores:
                        continue
                    best_name = ""
                    best_score = 0.0
                    for name, score in scores.items():
                        try:
                            s = float(score)
                        except (TypeError, ValueError):
                            continue
                        if s > best_score:
                            best_score = s
                            best_name = str(name)
                    if self._debug and best_score >= threshold * 0.6:
                        logger.info(
                            "oww scores peak %s=%.3f (thr=%.2f)",
                            best_name,
                            best_score,
                            threshold,
                        )
                    if best_score >= threshold and best_name:
                        self._fire(f"openwakeword:{best_name}:{best_score:.2f}")
        except Exception:
            logger.exception("Wake listener (openWakeWord) audio error")

    def _run_phrase_gate(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            logger.error(
                "sounddevice required for wake listening: pip install sounddevice numpy"
            )
            return

        from diapason.speech.clap_listener import rms_mono

        cfg = self._cfg
        blocksize = max(1, int(cfg.sample_rate * cfg.block_ms / 1000))
        logger.info(
            "Wake listener (phrase_gate) started (min_rms=%.3f cooldown=%.1fs once=%s)",
            cfg.min_rms,
            cfg.cooldown_s,
            self._once,
        )

        capturing = False
        speech_started: float | None = None
        last_loud = 0.0
        chunks: list[bytes] = []
        last_peak_log = 0.0
        peak_window = 0.0

        try:
            with sd.InputStream(
                device=self._device,
                samplerate=cfg.sample_rate,
                channels=cfg.channels,
                dtype="float32",
                blocksize=blocksize,
            ) as stream:
                while not self._stop.is_set():
                    data, _ = stream.read(blocksize)
                    level = rms_mono(data)
                    now = time.monotonic()
                    peak_window = max(peak_window, level)
                    if self._debug and (now - last_peak_log) >= 1.0:
                        logger.info(
                            "wake mic peak=%.5f capturing=%s", peak_window, capturing
                        )
                        peak_window = 0.0
                        last_peak_log = now

                    loud = level >= cfg.min_rms
                    if loud:
                        last_loud = now
                        if not capturing:
                            capturing = True
                            speech_started = now
                            chunks = []
                        chunks.append(_float_to_s16le(data))
                    elif capturing:
                        chunks.append(_float_to_s16le(data))
                        started = speech_started or now
                        timed_out = (now - started) >= cfg.max_utterance_s
                        quiet_long = (now - last_loud) >= cfg.silence_end_s
                        held = (now - started) >= cfg.speech_hold_s
                        if (quiet_long and held) or timed_out:
                            pcm = b"".join(chunks)
                            capturing = False
                            chunks = []
                            speech_started = None
                            self._handle_utterance(pcm)
        except Exception:
            logger.exception("Wake listener audio error")

    def _handle_utterance(self, pcm: bytes) -> None:
        now = time.monotonic()
        if (now - self._last_fire) < self._cfg.cooldown_s:
            return
        if self._once and self._fired:
            return
        try:
            text = (self._transcribe(pcm, self._cfg.sample_rate) or "").strip()
        except Exception:
            logger.debug("wake transcribe failed", exc_info=True)
            return
        if not text:
            return
        if self._debug:
            logger.info("wake STT: %r", text)
        if not has_wake_word(text, pattern=self._pattern):
            return
        self._fire(text)


def phrases_from_config(raw: str | Sequence[str] | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_WAKE_VARIANTS
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return tuple(parts) if parts else DEFAULT_WAKE_VARIANTS
    parts = [str(p).strip() for p in raw if str(p).strip()]
    return tuple(parts) if parts else DEFAULT_WAKE_VARIANTS


__all__ = [
    "WakeListenConfig",
    "WakeWordListener",
    "default_transcribe_pcm",
    "openwakeword_available",
    "phrases_from_config",
    "resolve_backend",
    "wake_config_from_toml",
]
