"""Engine discovery — probe running engines and aggregate available models."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from diapason.core.config import DiapasonConfig
from diapason.core.registry import EngineRegistry
from diapason.engine._base import InferenceEngine

logger = logging.getLogger(__name__)

# Map registry keys to config host attribute (None = no host arg)
_HOST_MAP: Dict[str, str | None] = {
    "ollama": "ollama_host",
    "vllm": "vllm_host",
    "llamacpp": "llamacpp_host",
    "sglang": "sglang_host",
    "mlx": "mlx_host",
    "lmstudio": "lmstudio_host",
    "exo": "exo_host",
    "nexa": "nexa_host",
    "uzu": "uzu_host",
    "apple_fm": "apple_fm_host",
    "lemonade": "lemonade_host",
    "cloud": None,
    "litellm": None,
    "gemma_cpp": None,
}


# Engines whose transport is a remote provider, whatever the config says.
# Keyed rather than probed because the verdict must be available BEFORE the
# class is instantiated — CloudEngine.__init__ reads eight API-key environment
# variables in its constructor (engine/cloud.py), so asking the instance
# afterwards is already too late.
_REMOTE_ENGINE_KEYS = frozenset({"cloud", "litellm"})


def _engine_key_is_remote(key: str, config: DiapasonConfig) -> bool:
    """True when constructing ``key`` would mean talking to another machine.

    Host-based engines are judged on their configured host, not on their name:
    an Ollama pointed at ``http://localhost:11434`` is local, the same Ollama
    pointed at a LAN box is not.
    """
    from diapason.core.local_mode import host_is_local

    if key in _REMOTE_ENGINE_KEYS:
        return True
    host_attr = _HOST_MAP.get(key)
    if host_attr is None:
        return False  # in-process (gemma_cpp) — nothing leaves
    host = getattr(config.engine, host_attr, None)
    if not host:
        return False  # class default, which is loopback for every host engine
    return not host_is_local(str(host))


def _make_engine(key: str, config: DiapasonConfig) -> InferenceEngine:
    """Instantiate a registered engine with the appropriate config host."""
    # Refuse BEFORE construction. This is the widest single guard in the
    # codebase: every path that reaches a cloud model — chat, ask, agents,
    # research, polish, vision, the server — resolves its engine here. Placing
    # the check at the call sites instead would have meant guarding ten of
    # them and forgetting the eleventh, and would still have let
    # CloudEngine.__init__ read every API key on the machine first.
    from diapason.core.local_mode import REFUSAL_HINT, LocalOnlyError, local_only

    if local_only(config) and _engine_key_is_remote(key, config):
        logger.info(
            "local-mode: refusing to construct remote engine %r "
            "— no credential was read",
            key,
        )
        raise LocalOnlyError(f"Engine {key!r} is remote. {REFUSAL_HINT}")

    cls = EngineRegistry.get(key)

    # gemma_cpp: pass config fields instead of host
    if key == "gemma_cpp":
        cfg = config.engine.gemma_cpp
        return cls(
            model_path=cfg.model_path or None,
            tokenizer_path=cfg.tokenizer_path or None,
            model_type=cfg.model_type or None,
            num_threads=cfg.num_threads,
        )

    host_attr = _HOST_MAP.get(key)
    if host_attr is not None:
        host = getattr(config.engine, host_attr, None)
        if host:
            return cls(host=host)
    return cls()


def _maybe_register_mining_sidecar_engine() -> None:
    """If a mining sidecar exists with a ``vllm_endpoint``, register a derived
    vLLM engine class pointing at it.  Idempotent.  Quiet on error.

    The trigger is the *shape* of the sidecar (presence of ``vllm_endpoint``),
    not the value of its ``provider`` field — this leaves room for future
    non-engine-replacing providers (e.g., a hypothetical cpu-pearl) whose
    sidecars don't include ``vllm_endpoint``.
    """
    try:
        from diapason.mining import Sidecar
        from diapason.mining._constants import SIDECAR_PATH
    except ImportError:
        return

    if EngineRegistry.contains("vllm-pearl-mining"):
        return  # idempotent

    payload = Sidecar.read(SIDECAR_PATH)
    if payload is None:
        return

    endpoint = payload.get("vllm_endpoint")
    model = payload.get("model")
    if not endpoint or not model:
        return  # data-driven gate: no vllm_endpoint → don't register

    from diapason.engine._openai_compat import _OpenAICompatibleEngine

    # Strip a trailing "/v1" path segment so _default_host is the bare
    # base URL and _api_prefix="/v1" combines correctly in request paths.
    api_prefix = "/v1"
    base_url = endpoint.rstrip("/")
    if base_url.endswith(api_prefix):
        base_url = base_url[: -len(api_prefix)]

    _cls = type(
        "VllmPearlMiningEngine",
        (_OpenAICompatibleEngine,),
        {
            "engine_id": "vllm-pearl-mining",
            "_default_host": base_url,
            "_api_prefix": api_prefix,
        },
    )
    EngineRegistry.register_value("vllm-pearl-mining", _cls)


def discover_engines(config: DiapasonConfig) -> List[Tuple[str, InferenceEngine]]:
    """Probe registered engines and return ``[(key, instance)]`` for healthy ones.

    Results are sorted with the config default engine first.
    """
    _maybe_register_mining_sidecar_engine()

    # Probe engines concurrently: each health() does a blocking network
    # check with its own timeout, so a serial loop costs the SUM of all
    # probe timeouts (dead localhost ports especially). Running them in
    # threads collapses that to roughly the slowest single probe. The
    # healthy.sort() below normalizes order, so completion order is
    # irrelevant and the result is identical to the serial version (#263).
    keys = list(EngineRegistry.keys())

    def _probe(key: str) -> Tuple[str, InferenceEngine] | None:
        try:
            engine = _make_engine(key, config)
            if engine.health():
                return (key, engine)
        except Exception as exc:
            logger.debug("Engine %r failed during discovery: %s", key, exc)
        return None

    healthy: List[Tuple[str, InferenceEngine]] = []
    if keys:
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            for result in pool.map(_probe, keys):
                if result is not None:
                    healthy.append(result)

    default_key = config.engine.default

    def sort_key(item: Tuple[str, Any]) -> Tuple[int, str]:
        return (0 if item[0] == default_key else 1, item[0])

    healthy.sort(key=sort_key)
    return healthy


def discover_models(
    engines: List[Tuple[str, InferenceEngine]],
) -> Dict[str, List[str]]:
    """Call ``list_models()`` on each engine and return a dict."""
    result: Dict[str, List[str]] = {}
    for key, engine in engines:
        try:
            result[key] = engine.list_models()
        except Exception as exc:
            logger.debug("Failed to list models for engine %r: %s", key, exc)
            result[key] = []
    return result


def get_engine(
    config: DiapasonConfig,
    engine_key: str | None = None,
    model: str | None = None,
) -> Tuple[str, InferenceEngine] | None:
    """Get a specific engine by key, or the default with fallback.

    When *model* is given, an engine is selected only if it can actually
    serve that model (``engine.can_serve(model)``). This stops the cloud
    fallback from being chosen — when the local engine is down — for a model
    whose provider client is missing, which otherwise surfaces as a confusing
    "OpenAI client not available" instead of a helpful "start your local
    engine" message (see #532). When *model* is ``None`` selection stays
    model-agnostic (unchanged behaviour).

    Returns ``(key, engine_instance)`` or ``None`` if no engine is available.
    """

    def _usable(engine: InferenceEngine) -> bool:
        return engine.health() and (model is None or engine.can_serve(model))

    # Build an ordered list of keys to try, then fall back to full discovery.
    keys_to_try: list[str] = []
    if engine_key:
        keys_to_try.append(engine_key)

    default_key = config.engine.default
    if default_key and default_key not in keys_to_try:
        keys_to_try.append(default_key)

    for key in keys_to_try:
        if not EngineRegistry.contains(key):
            continue
        try:
            engine = _make_engine(key, config)
            if _usable(engine):
                return (key, engine)
        except Exception as exc:
            logger.debug("Engine %r health check failed: %s", key, exc)

    # Fallback to the first healthy engine that can serve the model.
    for key, engine in discover_engines(config):
        if model is None or engine.can_serve(model):
            return (key, engine)
    return None


__all__ = ["discover_engines", "discover_models", "get_engine"]
