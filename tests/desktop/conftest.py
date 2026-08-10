"""Keep desktop tests away from the user's real data.

``DictationService`` records to the real dictation history by default — which
is correct for the product and wrong for a test suite: running the tests once
polluted the user's own history with fixture sentences ("bonjour le monde").
This autouse fixture redirects the history to a temp file for every test in
this package, so a test can only ever write to its own sandbox.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_dictation_history(tmp_path, monkeypatch):
    from openjarvis.desktop import dictation_history

    monkeypatch.setattr(
        dictation_history,
        "default_history_path",
        lambda: tmp_path / "dictation_history.jsonl",
    )
    yield
