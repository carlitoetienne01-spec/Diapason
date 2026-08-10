"""Guards against the dictionary runaway that actually happened.

Auto-learning had no upper bound, so each pass could learn the previous entry
plus a little more. On this machine it produced a 2 MB dictionary whose
largest entry was 1,048,583 characters of "pasting......" — which was then
handed to the recogniser as a hotwords prompt longer than the audio itself.
"""

from __future__ import annotations

from diapason.speech.dictation_dictionary import (
    DictionaryEntry,
    _learnable_phrase,
    transcription_hints,
)


def test_a_short_name_is_learnable():
    assert _learnable_phrase("Carlito") is True
    assert _learnable_phrase("Carlito Etienne") is True


def test_a_paragraph_is_not_a_dictionary_word():
    """The missing cap: a 1 MB string used to pass this check."""
    assert _learnable_phrase("x" * 5_000) is False
    assert _learnable_phrase("pasting" + "." * 1_000_000) is False


def test_a_long_sentence_is_not_learnable():
    """A dictionary entry is a word or a short phrase, not a sentence."""
    assert _learnable_phrase("un deux trois quatre cinq six sept huit") is False


def test_hints_never_emit_an_oversized_entry():
    """Defence in depth: an already-poisoned file must not reach the model.

    The caps stop new poisoning; this stops an existing bad entry from being
    sent by a build that predates them.
    """
    entries = [
        DictionaryEntry(word="Carlito", usage_count=5),
        DictionaryEntry(word="pasting" + "." * 100_000, usage_count=99),
    ]
    hints = transcription_hints(entries)
    assert hints == ["Carlito"]


def test_hints_respect_the_limit():
    entries = [DictionaryEntry(word=f"mot{i}", usage_count=i) for i in range(100)]
    assert len(transcription_hints(entries, limit=10)) == 10
