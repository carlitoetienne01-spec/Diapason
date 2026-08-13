"""Model integrity + the local-only download policy (lot 6)."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from diapason.speech.model_integrity import (
    ImplicitDownloadBlocked,
    guard_implicit_download,
    sha256_file,
    should_allow_download,
    verify_file_sha256,
)

# ── sha256 verification ──────────────────────────────────────────────────────


def test_sha256_matches_and_mismatches(tmp_path):
    f = tmp_path / "model.bin"
    f.write_bytes(b"weights")
    digest = hashlib.sha256(b"weights").hexdigest()

    assert sha256_file(f) == digest
    assert verify_file_sha256(f, digest) is True
    assert verify_file_sha256(f, digest.upper()) is True  # case-insensitive
    assert verify_file_sha256(f, "deadbeef") is False


def test_verify_is_false_for_missing_file_not_an_exception(tmp_path):
    assert verify_file_sha256(tmp_path / "nope.bin", "abc") is False


def test_no_pin_means_unverified_not_verified(tmp_path):
    f = tmp_path / "m.bin"
    f.write_bytes(b"x")
    # An empty expected digest is "we don't know", which must not read as "ok".
    assert verify_file_sha256(f, "") is False


# ── download policy ──────────────────────────────────────────────────────────


def test_cached_model_is_always_allowed():
    assert should_allow_download(local_only=True, explicit=False, already_cached=True)


def test_implicit_download_refused_under_local_only():
    assert not should_allow_download(
        local_only=True, explicit=False, already_cached=False
    )


def test_explicit_pull_allowed_even_under_local_only():
    assert should_allow_download(local_only=True, explicit=True, already_cached=False)


def test_anything_allowed_when_local_only_is_off():
    assert should_allow_download(local_only=False, explicit=False, already_cached=False)


def test_guard_raises_only_on_the_refused_case():
    with pytest.raises(ImplicitDownloadBlocked):
        guard_implicit_download("base", local_only=True, already_cached=False)

    # These three do not raise.
    guard_implicit_download("base", local_only=True, already_cached=True)
    guard_implicit_download(
        "base", local_only=True, already_cached=False, explicit=True
    )
    guard_implicit_download("base", local_only=False, already_cached=False)


def test_guard_message_points_to_the_explicit_command():
    with pytest.raises(ImplicitDownloadBlocked, match="diapason model pull base"):
        guard_implicit_download("base", local_only=True, already_cached=False)


# ── faster-whisper wiring ────────────────────────────────────────────────────


def test_faster_whisper_refuses_silent_download_under_local_only():
    """First-use transcription must not quietly fetch a model in local-only."""
    from diapason.speech.faster_whisper import FasterWhisperBackend

    backend = FasterWhisperBackend(model_size="base")

    with patch("diapason.core.local_mode.local_only", return_value=True):
        with patch(
            "diapason.speech.model_integrity.faster_whisper_cached",
            return_value=False,
        ):
            with pytest.raises(ImplicitDownloadBlocked):
                backend._ensure_model()
