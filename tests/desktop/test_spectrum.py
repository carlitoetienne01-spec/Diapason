"""Band analysis: does a tone land where a listener would expect it?"""

from __future__ import annotations

import numpy as np
import pytest

from diapason.desktop.spectrum import (
    DEFAULT_BANDS,
    MAX_HZ,
    MIN_HZ,
    BandSmoother,
    band_edges,
    band_energies,
    scaled_by_level,
)

RATE = 48_000


def tone(hz: float, samples: int = 2048, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(samples) / RATE
    return (np.sin(2 * np.pi * hz * t) * amplitude).astype("float32")


class TestBandEdges:
    def test_spans_the_speech_range(self):
        edges = band_edges()
        assert edges[0] == pytest.approx(MIN_HZ)
        assert edges[-1] == pytest.approx(MAX_HZ)

    def test_is_logarithmic_not_linear(self):
        # Linear spacing would hand almost every band to the top octaves,
        # where speech has least to say: busy on the right, dead on the left.
        edges = band_edges()
        widths = [b - a for a, b in zip(edges, edges[1:])]
        assert widths[-1] > widths[0] * 10

    def test_edges_increase(self):
        edges = band_edges()
        assert edges == sorted(edges)

    def test_degenerate_band_count_does_not_crash(self):
        assert len(band_edges(0)) == 2


class TestBandEnergies:
    @pytest.mark.parametrize(
        "hz,expected_band",
        [(120, 0), (900, 6), (5000, 10)],
    )
    def test_a_tone_peaks_in_the_band_that_contains_it(self, hz, expected_band):
        energies = band_energies(tone(hz), RATE)
        assert int(np.argmax(energies)) == expected_band

    def test_silence_is_silent(self):
        # An indicator that twitches in a quiet room is worse than no
        # indicator: it says the microphone is hearing something it is not.
        assert (
            band_energies(np.zeros(2048, dtype="float32"), RATE)
            == [0.0] * DEFAULT_BANDS
        )

    def test_returns_one_value_per_band(self):
        assert len(band_energies(tone(500), RATE)) == DEFAULT_BANDS
        assert len(band_energies(tone(500), RATE, bands=5)) == 5

    def test_every_value_is_normalised(self):
        for value in band_energies(tone(700), RATE):
            assert 0.0 <= value <= 1.0

    def test_a_block_too_short_to_analyse_returns_nothing(self):
        # Rather than invent numbers from a block that cannot resolve the
        # lowest band.
        assert (
            band_energies(np.zeros(10, dtype="float32"), RATE) == [0.0] * DEFAULT_BANDS
        )

    def test_an_invalid_sample_rate_returns_nothing(self):
        assert band_energies(tone(500), 0) == [0.0] * DEFAULT_BANDS

    def test_shape_is_independent_of_loudness(self):
        # Bands are normalised within their block, so a whisper and a shout
        # give the same shape; the level is applied separately.
        quiet = band_energies(tone(900, amplitude=0.02), RATE)
        loud = band_energies(tone(900, amplitude=0.9), RATE)
        assert np.allclose(quiet, loud, atol=0.05)

    def test_windowing_keeps_a_pure_tone_off_the_far_bands(self):
        # Without a window every block boundary is a step change that smears
        # energy across the spectrum and lights the top bands on silence.
        energies = band_energies(tone(150), RATE)
        assert max(energies[6:]) < 0.15


class TestSmoother:
    def test_rises_faster_than_it_falls(self):
        # Fast attack so a syllable registers; slow release so the display
        # coasts through the gap between two words instead of collapsing.
        smoother = BandSmoother(4)
        smoother.push([1.0] * 4)
        risen = smoother.values[0]
        smoother.push([0.0] * 4)
        fallen = smoother.values[0]
        assert risen > 0.4
        assert fallen > risen * 0.5

    def test_converges_on_a_held_value(self):
        smoother = BandSmoother(3)
        for _ in range(60):
            smoother.push([0.8, 0.8, 0.8])
        assert all(abs(v - 0.8) < 0.01 for v in smoother.values)

    def test_adapts_when_the_band_count_changes(self):
        smoother = BandSmoother(4)
        assert len(smoother.push([0.5] * 9)) == 9

    def test_starts_from_silence(self):
        assert BandSmoother(5).values == [0.0] * 5


class TestScaledByLevel:
    def test_silence_flattens_everything(self):
        assert scaled_by_level([1.0, 1.0], 0.0) == [0.0, 0.0]

    def test_louder_input_scales_further_up(self):
        quiet = scaled_by_level([1.0], 0.2)[0]
        loud = scaled_by_level([1.0], 3.0)[0]
        assert loud > quiet

    def test_never_exceeds_the_band_value(self):
        assert scaled_by_level([1.0], 1e6)[0] <= 1.0

    def test_a_negative_level_is_treated_as_silence(self):
        assert scaled_by_level([1.0], -5.0) == [0.0]
