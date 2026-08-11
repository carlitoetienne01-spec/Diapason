"""Turn a block of microphone audio into a handful of band energies.

The dictation indicator used to receive one number — the RMS level — which is
enough to make a field breathe but not enough to make it behave like an
equaliser: a single number cannot say *where* in the spectrum the energy is,
so every part of the display can only ever move together.

This computes that missing information. It is deliberately small and pure: no
audio device, no state, no callbacks, so the band layout can be tested without
a microphone.
"""

from __future__ import annotations

import math
from typing import List, Sequence

# Speech lives here. Below ~80 Hz is room rumble and handling noise; above
# ~8 kHz there is little voiced energy and a lot of hiss, and both would show
# up as bands that twitch when nobody is speaking.
MIN_HZ = 80.0
MAX_HZ = 8000.0

DEFAULT_BANDS = 12

# Attack is fast so a syllable registers; release is slow so the display
# coasts through the gap between two words instead of collapsing and jumping.
ATTACK = 0.55
RELEASE = 0.12


def band_edges(bands: int = DEFAULT_BANDS) -> List[float]:
    """Band boundaries in Hz, spaced logarithmically.

    Linear spacing would give almost every band to the top octaves, where
    speech has least to say — the display would look busy at the right and
    dead at the left. Log spacing matches how pitch is actually heard.
    """
    if bands < 1:
        return [MIN_HZ, MAX_HZ]
    ratio = MAX_HZ / MIN_HZ
    return [MIN_HZ * (ratio ** (i / bands)) for i in range(bands + 1)]


def band_energies(
    samples: Sequence[float],
    sample_rate: int,
    *,
    bands: int = DEFAULT_BANDS,
) -> List[float]:
    """Energy per band, 0–1, from a mono block.

    Returns all zeros for anything unusable — a block too short to resolve the
    lowest band tells us nothing, and inventing values would make the display
    move for no reason.
    """
    import numpy as np

    data = np.asarray(samples, dtype="float32").reshape(-1)
    if data.size < 64 or sample_rate <= 0:
        return [0.0] * bands

    # A window is not optional: without one, every block boundary is a step
    # change that smears energy across the whole spectrum, and the top bands
    # light up on silence.
    windowed = data * np.hanning(data.size).astype("float32")
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(data.size, d=1.0 / sample_rate)

    edges = band_edges(bands)
    out: List[float] = []
    for i in range(bands):
        lo, hi = edges[i], edges[i + 1]
        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any():
            # The block is too short to resolve this band; carry the
            # neighbour rather than punching a permanent hole in the display.
            out.append(out[-1] if out else 0.0)
            continue
        out.append(float(spectrum[mask].mean()))

    # Normalise against the loudest band of this block, then apply a gentle
    # compression: raw magnitudes span orders of magnitude, and a linear map
    # leaves everything but the peak flat on the floor.
    peak = max(out) if out else 0.0
    if peak <= 1e-9:
        return [0.0] * bands
    return [min(1.0, (value / peak) ** 0.6) for value in out]


class BandSmoother:
    """Holds the previous frame so the bands rise fast and fall slowly.

    Raw per-block energies flicker at the block rate, which reads as noise
    rather than as a voice. Kept separate from the analysis so the maths above
    stays pure.
    """

    def __init__(self, bands: int = DEFAULT_BANDS) -> None:
        self.values: List[float] = [0.0] * bands

    def push(self, energies: Sequence[float]) -> List[float]:
        if len(energies) != len(self.values):
            self.values = [0.0] * len(energies)
        for i, target in enumerate(energies):
            rate = ATTACK if target > self.values[i] else RELEASE
            self.values[i] += (target - self.values[i]) * rate
        return list(self.values)


def scaled_by_level(bands: Sequence[float], level: float) -> List[float]:
    """Scale per-block bands by overall loudness.

    Band energies are normalised within their own block, so silence and a
    shout produce the same shape. Multiplying by the level is what makes the
    display fall quiet when the room is quiet — the shape says *what* is being
    said, the level says *how loudly*.
    """
    # Same curve the indicator already used for the RMS meter, so a given
    # loudness moves the display by the same amount it always did.
    norm = min(1.0, math.sqrt(max(0.0, level) / 4.0))
    return [value * norm for value in bands]
