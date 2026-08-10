"""Dictation polish obeys local-only mode.

The whole dictation path is covered by the contract, not just the
transcription step. Before this guard, ``llm_polish_text`` took whichever
engine ``[engine] default`` named and sent the dictated sentence to it — so a
user transcribing locally still had every phrase polished in the cloud.

There is no cloud-free way to polish with a remote engine, so in local-only
mode the answer is "no polish", never "polish elsewhere": the function returns
None and the caller keeps the raw text.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from openjarvis.speech.llm_polish import llm_polish_text

_SENTENCE = "euh donc on se voit demain matin je crois"


@dataclass
class _Privacy:
    local_only: bool


class _Cfg:
    def __init__(self, local: bool):
        self.privacy = _Privacy(local_only=local)
        self.intelligence = MagicMock(default_model="gemma3:4b")
        self.engine = MagicMock(default="ollama")


def _engine(engine_id: str, is_cloud: bool) -> MagicMock:
    eng = MagicMock()
    eng.engine_id = engine_id
    eng.is_cloud = is_cloud
    return eng


def test_local_only_refuses_a_remote_engine_without_calling_it():
    """The sentence must not reach the engine at all — not merely be discarded."""
    remote = _engine("openai", True)

    with patch("openjarvis.core.config.load_config", return_value=_Cfg(True)):
        result = llm_polish_text(_SENTENCE, engine=remote)

    assert result is None
    remote.generate.assert_not_called()


def test_local_only_allows_a_local_engine():
    """Counter-proof: the guard refuses the cloud, not the feature."""
    local = _engine("ollama", False)
    local.generate.return_value = {"content": "On se voit demain matin."}

    with patch("openjarvis.core.config.load_config", return_value=_Cfg(True)):
        result = llm_polish_text(_SENTENCE, engine=local)

    local.generate.assert_called_once()
    assert result == "On se voit demain matin."


def test_a_remote_engine_is_still_used_when_local_only_is_off():
    """Counter-proof: default behaviour is unchanged for cloud users."""
    remote = _engine("openai", True)
    remote.generate.return_value = {"content": "On se voit demain matin."}

    with patch("openjarvis.core.config.load_config", return_value=_Cfg(False)):
        result = llm_polish_text(_SENTENCE, engine=remote)

    remote.generate.assert_called_once()
    assert result == "On se voit demain matin."


def test_an_engine_that_declares_nothing_is_treated_as_remote():
    """Silence is not consent: an engine with no locality signal is refused."""
    opaque = MagicMock(spec=[])  # neither engine_id nor is_cloud

    with patch("openjarvis.core.config.load_config", return_value=_Cfg(True)):
        assert llm_polish_text(_SENTENCE, engine=opaque) is None
