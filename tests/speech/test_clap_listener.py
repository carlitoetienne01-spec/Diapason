"""Unit tests for clap detector (no microphone)."""

from __future__ import annotations

from diapason.speech.clap_listener import ClapConfig, ClapDetector, rms_mono


def _cfg(**kwargs) -> ClapConfig:
    base = dict(
        spike_ratio=5.0,
        cooldown_s=0.2,
        min_double_gap_s=0.05,
        max_double_gap_s=0.35,
        retrigger_ratio=0.55,
        noise_floor_alpha=0.99,
        min_rms=0.01,
        quiet_gate_mult=2.2,
    )
    base.update(kwargs)
    return ClapConfig(**base)


def _feed_quiet(det: ClapDetector, t0: float, n: int = 30) -> float:
    t = t0
    for i in range(n):
        t = t0 + i * 0.04
        det.process(0.002, t)
    return t


def _clap_pulse(det: ClapDetector, t: float, peak: float = 0.2) -> bool:
    hit = det.process(peak, t)
    det.process(0.001, t + 0.02)
    return hit


def test_rms_silence():
    import numpy as np

    assert rms_mono(np.zeros(64, dtype="float32")) == 0.0


def test_double_clap_within_window():
    det = ClapDetector(cfg=_cfg(), noise_floor=0.002)
    t = _feed_quiet(det, 0.0)
    assert _clap_pulse(det, t + 0.1) is False
    assert _clap_pulse(det, t + 0.1 + 0.15) is True


def test_gap_too_large_starts_new_pair():
    det = ClapDetector(cfg=_cfg(), noise_floor=0.002)
    t = _feed_quiet(det, 0.0)
    assert _clap_pulse(det, t + 0.1) is False
    assert _clap_pulse(det, t + 0.1 + 0.50) is False
    assert _clap_pulse(det, t + 0.1 + 0.50 + 0.12) is True


def test_local_trigger_emit(tmp_path):
    from diapason.channels.local_trigger import LocalTriggerChannel

    path = tmp_path / "t.jsonl"
    ch = LocalTriggerChannel(path=path)
    received = []

    def handler(msg):
        received.append(msg.content)
        return None

    ch.on_message(handler)
    ch.connect()
    ch.emit("hello", event="welcome_home")
    import time

    time.sleep(0.8)
    ch.disconnect()
    assert any("hello" in c for c in received)
