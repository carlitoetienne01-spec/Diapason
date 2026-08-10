"""WebSocket routes for realtime duplex voice (/v1/voice/live)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

voice_live_router = APIRouter(tags=["voice-live"])


def _parse_tools_csv(raw: str) -> Optional[list[str]]:
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    return parts or None


def _realtime_defaults(app_state: Any) -> dict[str, Any]:
    config = getattr(app_state, "config", None)
    speech = getattr(config, "speech", None) if config is not None else None
    rt = getattr(speech, "realtime", None) if speech is not None else None
    if rt is None:
        return {
            "provider": "gemini",
            "model": "",
            "voice": "",
            "language": "",
            "enabled": True,
            "enable_tools": True,
            "max_tool_steps": 12,
            "tools": "",
        }
    return {
        "provider": getattr(rt, "provider", "gemini") or "gemini",
        "model": getattr(rt, "model", "") or "",
        "voice": getattr(rt, "voice", "") or "",
        "language": getattr(rt, "language", "") or "",
        "enabled": bool(getattr(rt, "enabled", True)),
        "enable_tools": bool(getattr(rt, "enable_tools", True)),
        "max_tool_steps": int(getattr(rt, "max_tool_steps", 12) or 12),
        "tools": getattr(rt, "tools", "") or "",
    }


def _load_system_instructions(app_state: Any, *, enable_tools: bool) -> str:
    """Best-effort SOUL/USER + oral rules for the live session."""
    from openjarvis.speech.realtime.oral_prompt import build_live_agent_template

    agent_template = build_live_agent_template(enable_tools=enable_tools)
    try:
        config = getattr(app_state, "config", None)
        if config is None:
            from openjarvis.core.config import load_config

            config = load_config()
        from openjarvis.prompt.builder import SystemPromptBuilder

        builder = SystemPromptBuilder(
            agent_template=agent_template,
            memory_files_config=getattr(config, "memory_files", None),
            system_prompt_config=getattr(config, "system_prompt", None),
        )
        return builder.build()
    except Exception:
        logger.debug("voice live: could not build system prompt", exc_info=True)
        return agent_template


@voice_live_router.websocket("/v1/voice/live")
async def websocket_voice_live(websocket: WebSocket) -> None:
    """Realtime duplex voice bridge.

    Client protocol (JSON)::

        {"type": "start", "provider": "gemini"|"openai", "voice": "...", ...}
        {"type": "audio", "data": "<base64 pcm16>", "sample_rate": 16000}
        {"type": "text", "text": "..."}
        {"type": "interrupt"}
        {"type": "stop"}

    Server protocol::

        {"type": "ready"}
        {"type": "audio", "data": "<base64 pcm16>", "sample_rate": 24000}
        {"type": "transcript", "role": "user"|"assistant", "text": "...", "final": bool}
        {"type": "tool", "name": "...", "ok": bool, "detail": "..."}
        {"type": "interrupted"}
        {"type": "error", "detail": "..."}
        {"type": "closed"}
    """
    from openjarvis.server.auth_middleware import websocket_authorized
    from openjarvis.speech.realtime.bridge import VoiceLiveBridge
    from openjarvis.speech.realtime.factory import create_realtime_session

    expected_key = getattr(websocket.app.state, "api_key", "")
    if not websocket_authorized(websocket, expected_key):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    defaults = _realtime_defaults(websocket.app.state)
    if not defaults.get("enabled", True):
        await websocket.send_json(
            {"type": "error", "detail": "Realtime voice is disabled in config"}
        )
        await websocket.close()
        return

    session = None
    try:
        provider = websocket.query_params.get("provider") or defaults["provider"]
        voice = websocket.query_params.get("voice") or defaults["voice"]
        model = websocket.query_params.get("model") or defaults["model"]
        language = websocket.query_params.get("language") or defaults["language"]
        enable_tools = defaults["enable_tools"]
        max_tool_steps = defaults["max_tool_steps"]
        allowed_tools = _parse_tools_csv(defaults.get("tools") or "")
        instructions: Optional[str] = None

        raw = await websocket.receive_json()
        if (raw.get("type") or "").lower() != "start":
            await websocket.send_json(
                {"type": "error", "detail": "First message must be type=start"}
            )
            await websocket.close()
            return

        provider = (raw.get("provider") or provider or "gemini").lower()
        voice = raw.get("voice") or voice
        model = raw.get("model") or model
        language = raw.get("language") or language
        if "enable_tools" in raw:
            enable_tools = bool(raw["enable_tools"])
        if raw.get("max_tool_steps") is not None:
            max_tool_steps = int(raw["max_tool_steps"])
        if raw.get("tools"):
            allowed_tools = _parse_tools_csv(str(raw["tools"]))
        if raw.get("instructions"):
            instructions = str(raw["instructions"])
        elif raw.get("include_memory", True):
            instructions = _load_system_instructions(
                websocket.app.state, enable_tools=enable_tools
            )

        try:
            session = create_realtime_session(
                provider,
                model=model or "",
                voice=voice or "",
                instructions=instructions or "",
                language=language or "",
                enable_tools=enable_tools,
                max_tool_steps=max_tool_steps,
                allowed_tools=allowed_tools,
            )
        except ValueError as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close()
            return

        bridge = VoiceLiveBridge(websocket, session)
        await bridge.run()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("voice live session failed")
        try:
            await websocket.send_json({"type": "error", "detail": str(exc)})
        except Exception:
            pass
    finally:
        if session is not None:
            try:
                await session.close()
            except Exception:
                pass


@voice_live_router.get("/v1/voice/live/health")
async def voice_live_health(request: Request) -> dict[str, Any]:
    """Report realtime voice availability (keys + config)."""
    import os

    defaults = _realtime_defaults(request.app.state)
    gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    openai = bool(os.environ.get("OPENAI_API_KEY"))
    tool_ids: list[str] = []
    if defaults.get("enable_tools"):
        try:
            from openjarvis.speech.realtime.tools import list_voice_tool_ids

            tool_ids = list_voice_tool_ids(_parse_tools_csv(defaults.get("tools") or ""))
        except Exception:
            tool_ids = []
    return {
        "available": defaults.get("enabled", True) and (gemini or openai),
        "enabled": defaults.get("enabled", True),
        "default_provider": defaults.get("provider", "gemini"),
        "enable_tools": defaults.get("enable_tools", True),
        "max_tool_steps": defaults.get("max_tool_steps", 6),
        "tools": tool_ids,
        "hotkey": "Alt+Space",
        "providers": {
            "gemini": {"configured": gemini},
            "openai": {"configured": openai},
        },
    }


__all__ = ["voice_live_router"]
