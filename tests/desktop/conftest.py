"""Keep desktop tests away from the user's real data.

Both of these fixtures exist because a test run actually damaged real user
data:

* ``DictationService`` records to the real dictation history by default, so
  the suite wrote fixture sentences ("bonjour le monde") into it.
* ``finalize_dictation`` auto-learns into the real dictionary. Repeated runs
  fed status text back into it, each pass learning the previous entry plus
  more — a 2 MB file whose largest entry was a million characters of
  "pasting......", which then went to the recogniser as a hotwords prompt.

The lesson is not "add caps" (those exist now too) but that a test must never
be able to reach the user's files at all.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_dictation_history(tmp_path, monkeypatch):
    from diapason.desktop import dictation_history

    monkeypatch.setattr(
        dictation_history,
        "default_history_path",
        lambda: tmp_path / "dictation_history.jsonl",
    )
    yield


@pytest.fixture(autouse=True)
def _isolate_dictation_dictionary(tmp_path, monkeypatch):
    from diapason.speech import dictation_dictionary

    monkeypatch.setattr(
        dictation_dictionary,
        "default_dictionary_path",
        lambda: tmp_path / "dictation_dictionary.json",
    )
    yield
