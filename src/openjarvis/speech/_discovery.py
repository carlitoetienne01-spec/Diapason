"""Auto-discover available speech-to-text backends."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from openjarvis.core.config import JarvisConfig
    from openjarvis.speech._stubs import SpeechBackend

logger = logging.getLogger(__name__)

# Priority order: local first, then cloud
DISCOVERY_ORDER = [
    "faster-whisper",
    "openai",
    "deepgram",
]

# Backends that run entirely on this machine. Auto-discovery is restricted to
# these when local-only mode is on. A backend absent from this set is treated
# as remote: an unrecognised backend is not a local one.
LOCAL_BACKENDS = frozenset({"faster-whisper", "whisper", "mlx-whisper", "sherpa-onnx"})


def _create_backend(
    key: str,
    config: "JarvisConfig",
) -> Optional["SpeechBackend"]:
    """Try to instantiate a speech backend by registry key."""
    from openjarvis.core.registry import SpeechRegistry

    if not SpeechRegistry.contains(key):
        return None

    try:
        backend_cls = SpeechRegistry.get(key)

        if key == "faster-whisper":
            return backend_cls(
                model_size=config.speech.model,
                device=config.speech.device,
                compute_type=config.speech.compute_type,
            )
        elif key == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return None
            return backend_cls(api_key=api_key)
        elif key == "deepgram":
            api_key = os.environ.get("DEEPGRAM_API_KEY", "")
            if not api_key:
                return None
            return backend_cls(api_key=api_key)
        else:
            return backend_cls()
    except Exception:
        # Was a bare `return None`, which made a broken local backend
        # indistinguishable from an absent one: auto-discovery then walked on
        # to OpenAI and Deepgram, and the user's voice left the machine
        # because faster-whisper failed to load. The fallback still happens
        # when it is allowed, but it is no longer silent.
        logger.warning("speech backend %r failed to initialise", key, exc_info=True)
        return None


def get_speech_backend(config: "JarvisConfig") -> Optional["SpeechBackend"]:
    """Resolve the speech backend from config.

    If ``config.speech.backend`` is ``"auto"``, tries backends in
    priority order and returns the first healthy one.

    Local-only mode ([privacy] local_only) restricts both branches to
    ``LOCAL_BACKENDS``: an explicitly configured cloud backend is refused
    rather than honoured, and auto-discovery never walks past the local
    entries. A local failure then yields ``None`` — never a cloud backend.
    """
    # Trigger registration of built-in backends
    import openjarvis.speech  # noqa: F401
    from openjarvis.core.local_mode import local_only

    restrict_to_local = local_only(config)
    backend_key = config.speech.backend

    if backend_key != "auto":
        if restrict_to_local and backend_key not in LOCAL_BACKENDS:
            logger.error(
                "speech backend %r is remote and local-only mode is on — refusing; "
                "no audio was sent",
                backend_key,
            )
            return None
        return _create_backend(backend_key, config)

    # Auto-discovery: try each in priority order.
    order = [k for k in DISCOVERY_ORDER if not restrict_to_local or k in LOCAL_BACKENDS]
    for key in order:
        backend = _create_backend(key, config)
        if backend is not None:
            return backend

    if restrict_to_local:
        logger.error(
            "no local speech backend available and local-only mode is on — "
            "refusing to fall back to a cloud backend; no audio was sent"
        )
    return None
