"""Screen vision tools — one-shot describe + start/stop screen share."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from diapason.core.registry import ToolRegistry
from diapason.core.types import Message, Role, ToolResult
from diapason.desktop.screen_capture import (
    LOCAL_VISION_ENGINES,
    capture_screen_b64,
)
from diapason.desktop.screen_share import get_screen_share
from diapason.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_last_capture_monotonic: float = 0.0


def _vision_config() -> Any:
    try:
        from diapason.core.config import load_config

        return load_config().desktop.vision
    except Exception:
        return None


def _vision_enabled(cfg: Any = None) -> bool:
    c = cfg if cfg is not None else _vision_config()
    return bool(getattr(c, "enabled", False)) if c is not None else False


def describe_screen(
    *,
    question: str = "",
    monitor: Optional[int] = None,
    skip_rate_limit: bool = False,
) -> ToolResult:
    """Capture once and describe. Shared by one-shot tool and share loop."""
    global _last_capture_monotonic

    cfg = _vision_config()
    if not _vision_enabled(cfg):
        return ToolResult(
            tool_name="screen_describe",
            content=(
                "Screen vision is disabled. Enable with "
                "[desktop.vision] enabled = true "
                "(and grant Screen Recording on macOS)."
            ),
            success=False,
        )

    rate_ms = int(getattr(cfg, "rate_limit_ms", 1500) or 1500)
    now = time.monotonic()
    if (
        not skip_rate_limit
        and rate_ms > 0
        and (now - _last_capture_monotonic) * 1000 < rate_ms
    ):
        # While sharing, prefer cached summary if available
        share = get_screen_share()
        cached = share.latest_summary() if share.is_active() else ""
        if cached:
            return ToolResult(
                tool_name="screen_describe",
                content=cached,
                success=True,
                metadata={"cached": True, "sharing": True},
            )
        return ToolResult(
            tool_name="screen_describe",
            content="Please wait a moment before capturing the screen again.",
            success=False,
            metadata={"rate_limited": True},
        )

    q = (question or "").strip() or (
        "Describe briefly what you see on the screen. "
        "Focus on the main window and any text the user might care about. "
        "2–5 short sentences."
    )
    if monitor is None:
        mon = int(getattr(cfg, "monitor", 1) or 1)
    else:
        mon = int(monitor)
    max_dim = int(getattr(cfg, "max_dimension", 1280) or 1280)
    keep_temp = bool(getattr(cfg, "keep_temp", False))
    allow_cloud = bool(getattr(cfg, "allow_cloud", False))
    model = str(getattr(cfg, "model", "") or "").strip()
    engine_key = str(getattr(cfg, "engine", "") or "").strip()

    # ── AUTHORISE FIRST, CAPTURE SECOND ──────────────────────────────────
    # The previous order captured the screen and only then decided whether it
    # was allowed to be sent. capture_screen_b64 goes through
    # capture_screen_to_temp, so a request that was about to be refused still
    # wrote a full-screen image to a temp file. Refusing after the fact
    # protects the network but not the disk.
    #
    # Everything that can refuse — no engine, remote engine, no model — now
    # runs before any image of the user's screen is allowed to exist.
    try:
        from diapason.core.config import load_config
        from diapason.core.local_mode import local_only
        from diapason.engine._discovery import get_engine

        config = load_config()
        key = engine_key or (config.engine.default or "").strip() or None
        engine = get_engine(config, key)
        if engine is None:
            return ToolResult(
                tool_name="screen_describe",
                content="No inference engine available for vision.",
                success=False,
            )

        engine_id = getattr(engine, "engine_id", "") or key or ""
        is_local = engine_id in LOCAL_VISION_ENGINES
        if engine_id and engine_id not in LOCAL_VISION_ENGINES:
            if getattr(engine, "is_cloud", False) or engine_id in {
                "openai",
                "anthropic",
                "gemini",
                "groq",
            }:
                is_local = False
            else:
                is_local = not bool(getattr(engine, "is_cloud", False))

        # [privacy] local_only outranks [desktop.vision] allow_cloud. A
        # per-domain switch may only ever be more restrictive than the global
        # one, never less — otherwise the global switch is a suggestion.
        if local_only(config):
            allow_cloud = False

        if not allow_cloud and not is_local:
            return ToolResult(
                tool_name="screen_describe",
                content=(
                    f"Refusing to send screenshot to non-local engine "
                    f"('{engine_id}'). Use ollama (e.g. gemma3:4b / llava) "
                    "or set [desktop.vision] allow_cloud = true."
                ),
                success=False,
                metadata={"engine": engine_id, "local": False, "captured": False},
            )

        resolved_model = model or (config.intelligence.default_model or "").strip()
        if not resolved_model:
            return ToolResult(
                tool_name="screen_describe",
                content=(
                    "No vision model configured. Set [desktop.vision] model "
                    "or [intelligence] default_model (e.g. gemma3:4b)."
                ),
                success=False,
            )
    except Exception as exc:
        logger.exception("screen_describe: engine resolution failed")
        return ToolResult(
            tool_name="screen_describe",
            content=f"Screen vision failed: {exc}",
            success=False,
        )

    # Authorised — only now may an image of the screen exist.
    try:
        b64, meta = capture_screen_b64(
            monitor=mon,
            max_dimension=max_dim,
            keep_temp=keep_temp,
        )
    except Exception as exc:
        return ToolResult(
            tool_name="screen_describe", content=str(exc), success=False
        )

    _last_capture_monotonic = time.monotonic()

    try:
        result = engine.generate(
            [Message(role=Role.USER, content=q, images=[b64])],
            model=resolved_model,
            temperature=0.2,
            max_tokens=400,
        )
        content = ""
        if isinstance(result, dict):
            content = str(result.get("content") or "").strip()
        if not content:
            content = "I could not read the screen clearly."

        return ToolResult(
            tool_name="screen_describe",
            content=content,
            success=True,
            metadata={
                "monitor": mon,
                "bytes": meta.get("bytes"),
                "engine": engine_id,
                "model": resolved_model,
                "local": is_local,
                "sharing": get_screen_share().is_active(),
            },
        )
    except Exception as exc:
        logger.exception("screen_describe failed")
        return ToolResult(
            tool_name="screen_describe",
            content=f"Screen vision failed: {exc}",
            success=False,
        )


def _share_describe_fn(*, question: str = "", monitor: int = 1) -> str:
    """Background loop callback — skip rate limit, return text only."""
    result = describe_screen(
        question=question, monitor=monitor, skip_rate_limit=True
    )
    if not result.success:
        raise RuntimeError(result.content)
    return result.content


@ToolRegistry.register("screen_describe")
class ScreenDescribeTool(BaseTool):
    """Capture the screen once and describe/answer with a vision model."""

    tool_id = "screen_describe"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_describe",
            description=(
                "Take a screenshot NOW and answer about what is visible. "
                "Use for « regarde mon écran », « look at my screen », "
                "« qu'est-ce que c'est ça ? » while helping with on-screen work. "
                "If screen share is already active, this refreshes what you see. "
                "Pass the user's question as `question`."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "What to answer about the screenshot "
                            "(default: describe what you see)."
                        ),
                    },
                    "monitor": {
                        "type": "integer",
                        "description": "1-based monitor index (default from config).",
                    },
                },
                "required": [],
            },
            category="system",
            timeout_seconds=90.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        question = str(params.get("question") or "").strip()
        monitor = params.get("monitor")
        return describe_screen(
            question=question,
            monitor=int(monitor) if monitor is not None else None,
        )


@ToolRegistry.register("screen_share_start")
class ScreenShareStartTool(BaseTool):
    """Start continuous screen sharing until the user stops it."""

    tool_id = "screen_share_start"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_share_start",
            description=(
                "Start SCREEN SHARING: periodically look at the user's screen "
                "until they ask to stop. Use when the user says "
                "« je veux partager mon écran », « share my screen », "
                "« on partage l'écran », « watch my screen ». "
                "Confirm sharing started in one short sentence. "
                "When they say « arrête », « stop sharing », « arrête le partage », "
                "call screen_share_stop."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "monitor": {
                        "type": "integer",
                        "description": "1-based monitor index (optional).",
                    },
                },
                "required": [],
            },
            category="system",
            timeout_seconds=120.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        cfg = _vision_config()
        if not _vision_enabled(cfg):
            return ToolResult(
                tool_name="screen_share_start",
                content=(
                    "Screen vision is disabled. Enable [desktop.vision] enabled = true "
                    "first (Screen Recording permission required)."
                ),
                success=False,
            )

        monitor = params.get("monitor")
        if monitor is None:
            monitor = int(getattr(cfg, "monitor", 1) or 1)
        interval = float(getattr(cfg, "share_interval_s", 5.0) or 5.0)
        max_min = float(getattr(cfg, "share_max_minutes", 30.0) or 30.0)

        share = get_screen_share()
        out = share.start(
            monitor=int(monitor),
            interval_s=interval,
            max_minutes=max_min,
            describe_fn=_share_describe_fn,
        )
        return ToolResult(
            tool_name="screen_share_start",
            content=out.get("message") or str(out),
            success=bool(out.get("ok")),
            metadata={k: v for k, v in out.items() if k != "message"},
        )


@ToolRegistry.register("screen_share_stop")
class ScreenShareStopTool(BaseTool):
    """Stop continuous screen sharing."""

    tool_id = "screen_share_stop"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_share_stop",
            description=(
                "Stop SCREEN SHARING. Use when the user says « arrête », "
                "« arrête le partage », « stop sharing », « stop looking », "
                "« ne regarde plus mon écran »."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            category="system",
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        out = get_screen_share().stop(reason="user")
        return ToolResult(
            tool_name="screen_share_stop",
            content=out.get("message") or "Screen share stopped.",
            success=bool(out.get("ok")),
            metadata={k: v for k, v in out.items() if k != "message"},
        )


@ToolRegistry.register("screen_share_status")
class ScreenShareStatusTool(BaseTool):
    """Report whether screen share is active and the latest screen summary."""

    tool_id = "screen_share_status"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_share_status",
            description=(
                "Check if screen sharing is active and return the latest "
                "on-screen summary without a new capture if possible."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            category="system",
            timeout_seconds=10.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        st = get_screen_share().status()
        if st.get("active"):
            summary = st.get("latest_summary") or "(waiting for first frame)"
            content = (
                f"Screen share is ON (frame {st.get('frames')}, "
                f"{st.get('elapsed_s')}s). Latest view: {summary}"
            )
        else:
            content = "Screen share is OFF. I am not watching the screen."
        return ToolResult(
            tool_name="screen_share_status",
            content=content,
            success=True,
            metadata=st,
        )


def reset_rate_limit_for_tests() -> None:
    global _last_capture_monotonic
    _last_capture_monotonic = 0.0


__all__ = [
    "ScreenDescribeTool",
    "ScreenShareStartTool",
    "ScreenShareStopTool",
    "ScreenShareStatusTool",
    "describe_screen",
    "reset_rate_limit_for_tests",
]
