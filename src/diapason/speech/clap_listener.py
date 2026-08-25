"""Double-clap detector and optional microphone listener (welcome trigger)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ClapConfig:
    sample_rate: int = 44100
    block_ms: int = 40
    channels: int = 1
    spike_ratio: float = 2.5
    cooldown_s: float = 0.35
    min_double_gap_s: float = 0.04
    max_double_gap_s: float = 0.80
    retrigger_ratio: float = 0.80
    noise_floor_alpha: float = 0.992
    min_rms: float = 0.003
    quiet_gate_mult: float = 2.2


@dataclass
class ClapDetector:
    """Stateful detector: feed RMS samples, receive double-clap events."""

    cfg: ClapConfig
    noise_floor: float = 1e-4
    last_logged_double: float = 0.0
    first_clap_time: float | None = None
    spike_armed: bool = True
    last_miss_reason: str | None = None
    # Ce que le micro ENTEND, même quand aucun double ne se forme.
    # Sans ce compte, quelqu'un qui clape peut le faire une heure sans
    # savoir si le micro l'entend, si le seuil est trop haut, ou si c'est
    # l'écart entre les deux claps qui ne convient pas (25 août 2026).
    claps_entendus: int = 0
    dernier_clap_a: float = 0.0

    def process(self, level: float, now: float) -> bool:
        self.last_miss_reason = None
        cfg = self.cfg
        quiet_gate = self.noise_floor * cfg.quiet_gate_mult
        if level < quiet_gate:
            self.noise_floor = (
                cfg.noise_floor_alpha * self.noise_floor
                + (1.0 - cfg.noise_floor_alpha) * level
            )
            self.noise_floor = max(self.noise_floor, 1e-7)

        threshold = max(self.noise_floor * cfg.spike_ratio, cfg.min_rms)
        retrigger_level = threshold * cfg.retrigger_ratio

        if level < retrigger_level:
            self.spike_armed = True

        if not (
            self.spike_armed
            and level >= threshold
            and (now - self.last_logged_double) >= cfg.cooldown_s
        ):
            return False

        self.spike_armed = False
        self.claps_entendus += 1
        self.dernier_clap_a = now
        if self.first_clap_time is None:
            self.first_clap_time = now
            return False

        gap = now - self.first_clap_time
        if gap < cfg.min_double_gap_s:
            self.last_miss_reason = f"gap_too_small={gap:.3f}s"
            return False
        if gap <= cfg.max_double_gap_s:
            self.first_clap_time = None
            self.last_logged_double = now
            return True

        self.last_miss_reason = f"gap_too_large={gap:.3f}s_new_first"
        self.first_clap_time = now
        return False

    @property
    def threshold(self) -> float:
        return max(self.noise_floor * self.cfg.spike_ratio, self.cfg.min_rms)


def rms_mono(block) -> float:
    import numpy as np

    arr = np.asarray(block)
    if arr.ndim > 1:
        arr = np.mean(arr.astype(np.float64), axis=1)
    else:
        arr = arr.astype(np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr**2)))


def _input_devices():
    import sounddevice as sd

    return [
        (i, dev)
        for i, dev in enumerate(sd.query_devices())
        if dev["max_input_channels"] >= 1
    ]


def resolve_input_device_index(spec: str) -> int:
    import sounddevice as sd

    spec = spec.strip()
    if spec.isdigit():
        idx = int(spec)
        sd.query_devices(idx)
        return idx
    needle = spec.lower()
    for idx, dev in _input_devices():
        if needle in str(dev["name"]).lower():
            return idx
    raise ValueError(f"No input device matches {spec!r}")


def probe_input_max_rms(
    device: int,
    blocksize: int,
    *,
    sample_rate: int,
    channels: int,
    probe_s: float,
) -> float | None:
    import sounddevice as sd

    try:
        with sd.InputStream(
            device=device,
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            blocksize=blocksize,
        ) as stream:
            peak = 0.0
            deadline = time.monotonic() + probe_s
            while time.monotonic() < deadline:
                data, _ = stream.read(blocksize)
                peak = max(peak, rms_mono(data))
            return peak
    except Exception:
        return None


def choose_input_device(
    cfg: ClapConfig,
    blocksize: int,
    *,
    override: str | None = None,
    silent_rms: float = 0.0005,
    probe_s: float = 0.5,
) -> int | None:
    """Pick a working mic: override → default if loud → loudest input → default."""
    import sounddevice as sd

    logger.info("Audio devices:\n%s", sd.query_devices())

    if override and override.strip():
        idx = resolve_input_device_index(override)
        peak = probe_input_max_rms(
            idx,
            blocksize,
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            probe_s=probe_s,
        )
        logger.info(
            "Using configured mic [%d] (probe rms=%s)",
            idx,
            f"{peak:.5f}" if peak is not None else "unopenable",
        )
        return idx

    default = sd.default.device[0]
    if default is not None and default >= 0:
        peak = probe_input_max_rms(
            default,
            blocksize,
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            probe_s=probe_s,
        )
        if peak is not None and peak >= silent_rms:
            logger.info("Using default mic [%d] (probe rms=%.5f)", default, peak)
            return int(default)
        logger.warning(
            "Default mic [%d] silent/unusable (rms=%s); scanning…",
            default,
            f"{peak:.5f}" if peak is not None else "n/a",
        )

    best_idx: int | None = None
    best_peak = -1.0
    for idx, _dev in _input_devices():
        if default is not None and idx == default:
            continue
        peak = probe_input_max_rms(
            idx,
            blocksize,
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            probe_s=probe_s,
        )
        if peak is not None and peak > best_peak:
            best_peak = peak
            best_idx = idx

    if best_idx is not None and best_peak >= silent_rms:
        logger.info("Auto-selected mic [%d] (probe rms=%.5f)", best_idx, best_peak)
        return best_idx

    if default is not None and default >= 0:
        logger.warning("Falling back to default mic [%d]", default)
        return int(default)
    inputs = _input_devices()
    if inputs:
        logger.warning("Falling back to first input [%d]", inputs[0][0])
        return inputs[0][0]
    return None


class ClapListener:
    """Background mic loop that invokes a callback on double clap."""

    def __init__(
        self,
        on_double_clap: Callable[[], None],
        *,
        cfg: ClapConfig | None = None,
        once: bool = True,
        device: int | None = None,
        debug: bool = False,
    ) -> None:
        self._on_double = on_double_clap
        self._cfg = cfg or ClapConfig()
        self._once = once
        self._device = device
        self._debug = debug
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fired = False
        # Le fil d'écoute meurt en silence quand sounddevice manque ou que
        # le micro refuse de s'ouvrir : start() rend la main sans rien dire,
        # et l'appelant croit écouter (constaté le 25 août 2026 — le mode
        # annonçait « écoute active » alors que le fil était mort à la
        # première ligne). Ces deux signaux rendent le démarrage
        # CONSTATABLE au lieu d'être supposé.
        self._pret = threading.Event()
        self._panne: Optional[str] = None
        self._detecteur: Optional[ClapDetector] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._pret.clear()
        self._panne = None
        self._thread = threading.Thread(
            target=self._run, name="clap-listener", daemon=True
        )
        self._thread.start()
        # Attendre le verdict plutôt que de rendre la main sur une
        # espérance : deux secondes suffisent à ouvrir un micro, et
        # au-delà c'est que quelque chose ne va pas.
        self._pret.wait(2.0)

    @property
    def ecoute(self) -> bool:
        """Le micro est-il RÉELLEMENT ouvert ? Constaté, jamais supposé."""
        return (
            self._pret.is_set()
            and self._panne is None
            and self._thread is not None
            and self._thread.is_alive()
        )

    @property
    def claps_entendus(self) -> int:
        """Combien de pics le micro a relevés — doubles ou non."""
        return self._detecteur.claps_entendus if self._detecteur else 0

    @property
    def dernier_echec(self) -> Optional[str]:
        """Pourquoi le dernier pic n'a pas formé un double, s'il y a lieu."""
        return self._detecteur.last_miss_reason if self._detecteur else None

    @property
    def panne(self) -> Optional[str]:
        """Pourquoi l'écoute n'a pas démarré, s'il y a une raison."""
        return self._panne

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            self._panne = (
                "sounddevice manque : uv sync --extra speech-wake"
            )
            logger.error(self._panne)
            self._pret.set()
            return

        blocksize = max(
            1,
            int(self._cfg.sample_rate * self._cfg.block_ms / 1000),
        )
        detector = ClapDetector(cfg=self._cfg)
        self._detecteur = detector
        logger.info(
            "Clap listener started "
            "(spike_ratio=%.1f, gap=%.2f–%.2fs, once=%s, debug=%s)",
            self._cfg.spike_ratio,
            self._cfg.min_double_gap_s,
            self._cfg.max_double_gap_s,
            self._once,
            self._debug,
        )
        last_peak_log = 0.0
        peak_window = 0.0
        first_seen = False
        try:
            with sd.InputStream(
                device=self._device,
                samplerate=self._cfg.sample_rate,
                channels=self._cfg.channels,
                dtype="float32",
                blocksize=blocksize,
            ) as stream:
                # Le micro est ouvert POUR DE VRAI : c'est seulement ici
                # qu'on peut le dire.
                self._pret.set()
                while not self._stop.is_set():
                    data, _overflowed = stream.read(blocksize)
                    level = rms_mono(data)
                    now = time.monotonic()
                    peak_window = max(peak_window, level)

                    if self._debug and (now - last_peak_log) >= 1.0:
                        logger.info(
                            "mic peak=%.5f floor=%.5f thr=%.5f",
                            peak_window,
                            detector.noise_floor,
                            detector.threshold,
                        )
                        peak_window = 0.0
                        last_peak_log = now

                    before = detector.first_clap_time
                    hit = detector.process(level, now)
                    if (
                        before is None
                        and detector.first_clap_time is not None
                        and not hit
                        and not first_seen
                    ):
                        first_seen = True
                        logger.info(
                            "First clap (rms=%.5f thr=%.5f) — clap again within %.2fs",
                            level,
                            detector.threshold,
                            self._cfg.max_double_gap_s,
                        )
                    if (
                        detector.last_miss_reason
                        and detector.last_miss_reason.startswith("gap_too_large")
                    ):
                        logger.info(
                            "Second clap too late (%s)", detector.last_miss_reason
                        )
                        first_seen = True

                    if not hit:
                        continue
                    if self._once and self._fired:
                        logger.info("Double clap ignored (already fired this session)")
                        continue
                    self._fired = True
                    logger.info("Double clap detected — firing callback")
                    try:
                        self._on_double()
                    except Exception:
                        logger.exception("Clap callback failed")
                    if self._once:
                        break
        except Exception:
            logger.exception("Clap listener audio error")
