"""Local-only mode is a contract — the single idiom for checking it.

Every outbound path must ask the same question, the same way, before it
touches an API key or produces the data it is about to send. When the
question is re-asked ad hoc at each call site, a path is always forgotten:

* ``speech/_discovery.py`` swallowed a local Whisper failure and quietly
  continued down the list to OpenAI and Deepgram.
* ``speech/llm_polish.py`` resolved an engine without ever asking whether it
  was local.
* ``tools/screen_vision_tools.py`` wrote the screenshot to a temp file first
  and only then decided whether it was allowed to send it.

So the rule stops being copied:

    from diapason.core.local_mode import local_only

    if local_only(config):
        # refuse, BEFORE reading a key or capturing anything

Order matters as much as the test. Nothing outbound may be prepared before
this branch: in local-only mode a path must touch no credential and create no
artifact. That is externally verifiable, which is what makes it a contract
rather than an intention.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from diapason.core.config import DiapasonConfig

logger = logging.getLogger(__name__)

__all__ = [
    "local_only",
    "engine_is_local",
    "host_is_local",
    "assert_may_leave",
    "LocalOnlyError",
    "REFUSAL_HINT",
]

# Strict loopback only. RFC1918 addresses are deliberately absent: an Ollama
# on 192.168.1.50 is another machine, therefore another promise. Reaching it
# is a separate decision the user has not made by ticking "local only".
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"})


class LocalOnlyError(RuntimeError):
    """Raised when a remote call is refused because local-only mode is on.

    Carries ``nothing_left_the_machine`` so callers can tell this apart from a
    generic outage and say so — the distinction is precisely what the user
    asked for by turning the mode on.
    """

    nothing_left_the_machine = True


REFUSAL_HINT = (
    "Local-only mode is on ([privacy] local_only = true), so nothing was sent. "
    "Set local_only = false to allow cloud engines."
)


def host_is_local(url_or_host: str) -> bool:
    """True when a URL or host designates this machine.

    Reaching loopback is not leaving, so ``http://localhost:11434`` (Ollama),
    the internal FastAPI server and the Apple Foundation Models shim stay
    available in local-only mode — they are the whole point of it.

    A private-network address is NOT local here. ``192.168.1.50`` is someone
    else's computer; sending a dictation there is still sending it away, and
    the user did not consent to that by asking for local-only.

    Anything unparseable is treated as remote: a host we cannot read is not a
    host we can vouch for.
    """
    raw = (url_or_host or "").strip()
    if not raw:
        return False
    if raw.startswith("/") or raw.startswith("unix:"):
        return True  # unix socket — cannot leave the machine
    try:
        from urllib.parse import urlparse

        parsed = urlparse(raw if "//" in raw else f"//{raw}")
        host = (parsed.hostname or "").strip().lower()
    except Exception:  # noqa: BLE001 - unparseable is not vouchable
        return False
    if not host:
        return False
    return host in _LOOPBACK_HOSTS or host.endswith(".localhost")


def assert_may_leave(
    what: str,
    *,
    destination: str = "",
    config: Optional["DiapasonConfig"] = None,
) -> None:
    """Raise :class:`LocalOnlyError` when ``what`` may not leave this machine.

    The single idiom every outbound path calls **before** reading a credential
    or producing the payload. Two things make it a contract rather than a
    style:

    * it raises rather than returning a boolean, so a caller cannot forget to
      branch on the answer;
    * ``destination`` short-circuits it for loopback, so guarding a path costs
      nothing when that path was never leaving in the first place.

    ``what`` is a short human description used in the message — "the dictated
    text", "the screenshot". It must never contain the data itself.
    """
    if destination and host_is_local(destination):
        return
    if not local_only(config):
        return
    where = f" to {destination}" if destination else ""
    logger.info(
        "local-mode: refused to send %s%s — nothing left the machine", what, where
    )
    raise LocalOnlyError(f"Refusing to send {what}{where}. {REFUSAL_HINT}")


def local_only(config: Optional["DiapasonConfig"] = None) -> bool:
    """Return True when nothing may leave this machine.

    ``config`` is optional so call sites deep in a path need not thread it
    through; when omitted the active configuration is loaded.

    Fail-closed on any error. Getting this wrong in one direction costs a
    feature until the configuration is readable again; getting it wrong in the
    other sends the user's voice, screen or text to a third party. The costs
    are not symmetric, so the default must not be either.
    """
    try:
        cfg: Any = config
        if cfg is None:
            from diapason.core.config import load_config

            cfg = load_config()
        privacy = getattr(cfg, "privacy", None)
        if privacy is None:
            # A config object predating [privacy] (or a stub in a test) is not
            # evidence that sending is allowed.
            logger.warning(
                "local-mode: config has no [privacy] section — assuming local-only"
            )
            return True
        return bool(getattr(privacy, "local_only", True))
    except Exception:  # noqa: BLE001 - deliberate: unreadable config must not authorise
        logger.warning(
            "local-mode: configuration unreadable — assuming local-only", exc_info=True
        )
        return True


def engine_is_local(engine: Any, *, local_ids: Optional[set[str]] = None) -> bool:
    """Best-effort verdict on whether an inference engine runs on this machine.

    Trusts the explicit ``is_cloud`` flag of the engine protocol first, then
    falls back to the engine id. An engine that answers neither is treated as
    remote: an unknown backend is not a local one.
    """
    if engine is None:
        return False
    is_cloud = getattr(engine, "is_cloud", None)
    if is_cloud is not None:
        return not bool(is_cloud)
    engine_id = str(getattr(engine, "engine_id", "") or "").strip().lower()
    if not engine_id:
        return False
    known_local = local_ids if local_ids is not None else {
        "ollama",
        "mlx",
        "vllm",
        "llama-cpp",
        "gemma-cpp",
        "apple-fm",
        "nexa",
    }
    return engine_id in known_local
