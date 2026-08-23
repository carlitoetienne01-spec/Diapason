"""Model download integrity and the local-only download policy.

Two gaps this closes:

* Diapason pulls models with ``huggingface-cli download`` / ``ollama pull``
  and never checks what arrived. Diapason's ``fetch-model.js`` pins a sha256
  and deletes the file on mismatch. ``verify_file_sha256`` brings that here.

* faster-whisper downloads its model on first transcription — silently, over
  the network. Under ``[privacy] local_only`` a *silent* fetch is exactly what
  the user asked not to happen. ``should_allow_download`` encodes the policy:
  an implicit download is refused, an explicit ``diapason model pull`` is
  allowed, and an already-cached model is always fine (nothing leaves).

Both are pure functions so the policy is unit-tested, not left to a live pull.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CHUNK = 1 << 20  # 1 MiB


def sha256_file(path: str | Path) -> str:
    """Return the hex sha256 of a file, read in chunks (models are large)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(_CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify_file_sha256(path: str | Path, expected: str) -> bool:
    """True when the file's digest matches ``expected`` (case-insensitive).

    A missing or unreadable file is a failure, not an exception: the caller's
    job is to react (re-download, delete), not to crash.
    """
    want = (expected or "").strip().lower()
    if not want:
        # No pin to check against — treat as unverifiable, i.e. not verified.
        return False
    try:
        return sha256_file(path).lower() == want
    except OSError:
        return False


def should_allow_download(
    *, local_only: bool, explicit: bool, already_cached: bool
) -> bool:
    """Decide whether a model download may proceed.

    * Already cached → always allowed: using a model that is already on disk
      sends nothing.
    * Explicit (the user ran ``diapason model pull``) → allowed even in
      local-only: a foreground request is consent.
    * Implicit under local-only → refused: a background fetch triggered by the
      first dictation is the silent network access local-only forbids.
    """
    if already_cached:
        return True
    if not local_only:
        return True
    return explicit


class ImplicitDownloadBlocked(RuntimeError):
    """Raised when local-only refuses a silent model download."""


def guard_implicit_download(
    model_name: str,
    *,
    local_only: bool,
    already_cached: bool,
    explicit: bool = False,
) -> None:
    """Raise :class:`ImplicitDownloadBlocked` when a download must not happen."""
    if should_allow_download(
        local_only=local_only, explicit=explicit, already_cached=already_cached
    ):
        return
    raise ImplicitDownloadBlocked(
        f"Model {model_name!r} is not downloaded and local-only mode is on, so "
        f"it was not fetched automatically. Run `diapason model pull {model_name}` "
        "to download it explicitly, or set [privacy] local_only = false."
    )


def faster_whisper_cached(model_size: str) -> bool:
    """Best-effort check: is this faster-whisper model already in the HF cache?

    Uses huggingface_hub's cache probe when available; on any uncertainty it
    returns False, which fails safe — the caller then refuses an implicit
    download rather than risking a silent one.
    """
    # La table d'alias de faster-whisper fait foi : large-v3-turbo vit chez
    # mobiuslabsgmbh/, pas chez Systran/ — le gabarit codé en dur déclarait
    # « absent » un modèle pourtant téléchargé, et la garde le bloquait
    # (constaté le 23 août 2026). Le gabarit reste le repli pour une taille
    # que la table ne connaîtrait pas.
    if "/" in model_size:
        repo = model_size
    else:
        try:
            from faster_whisper.utils import _MODELS

            repo = _MODELS.get(model_size, f"Systran/faster-whisper-{model_size}")
        except Exception:  # noqa: BLE001 - la table est un bonus, pas une porte
            repo = f"Systran/faster-whisper-{model_size}"
    try:
        from huggingface_hub import try_to_load_from_cache  # type: ignore

        # model.bin is the weight file every faster-whisper repo ships.
        hit = try_to_load_from_cache(repo, "model.bin")
        return isinstance(hit, str) and Path(hit).exists()
    except Exception:  # noqa: BLE001 - unknown cache state fails safe
        return False
