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


def outils_demandes_par_le_client(csv: str) -> Optional[list[str]]:
    """Ce qu'un client a le droit de demander à la voix — au plus le défaut.

    RESTREINDRE, jamais élargir. Cette liste vient de la trame WebSocket du
    client ; `list_voice_tool_ids` ne la confrontait qu'au registre GLOBAL,
    si bien qu'un client pouvait demander n'importe quel outil enregistré —
    y compris ceux que `DEFAULT_VOICE_TOOL_IDS` tient délibérément hors du
    chemin vocal, et qu'un test-fusible prétend garder. La restriction était
    décorative : elle se contournait en nommant l'outil.

    Ce n'est pas une élévation de privilège : le WebSocket est derrière la
    clé d'API, et le même outil s'atteint par le chat. C'est une décision de
    portée qui ne s'appliquait pas — ce qui est pire qu'une décision absente,
    parce qu'un test la disait tenue.

    La liste du SERVEUR (`defaults`) n'est pas bridée ici : elle vient de la
    configuration, donc de la machine, pas du réseau.

    Rend ``None`` quand il ne reste rien — même contrat que
    ``_parse_tools_csv``, et même conséquence en aval : « aucune restriction
    demandée », donc la liste par défaut. Un client qui ne nomme QUE des
    outils hors portée obtient le défaut, pas le vide : refuser toute voix à
    qui a mal demandé serait une punition, pas une garde.
    """
    from diapason.speech.realtime.tools import DEFAULT_VOICE_TOOL_IDS

    demandes = _parse_tools_csv(csv) or []
    plafond = set(DEFAULT_VOICE_TOOL_IDS)
    retenus = [t for t in demandes if t in plafond]
    return retenus or None


def _realtime_defaults(app_state: Any) -> dict[str, Any]:
    config = getattr(app_state, "config", None)
    speech = getattr(config, "speech", None) if config is not None else None
    rt = getattr(speech, "realtime", None) if speech is not None else None
    if rt is None:
        return {
            # Local is the default everywhere: the cloud is the opt-in.
            "provider": "local",
            "model": "",
            "voice": "",
            "language": "",
            "enabled": True,
            "enable_tools": True,
            "max_tool_steps": 12,
            "tools": "",
        }
    return {
        "provider": getattr(rt, "provider", "local") or "local",
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
    from diapason.speech.realtime.oral_prompt import build_live_agent_template

    agent_template = build_live_agent_template(enable_tools=enable_tools)
    try:
        config = getattr(app_state, "config", None)
        if config is None:
            from diapason.core.config import load_config

            config = load_config()
        from diapason.prompt.builder import SystemPromptBuilder

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
        {"type": "transcript", "role": ..., "text": ..., "final": bool, "replace": bool}
        {"type": "tool", "name": "...", "ok": bool, "detail": "..."}
        {"type": "interrupted"}
        {"type": "error", "detail": "..."}
        {"type": "closed"}
    """
    from diapason.server.auth_middleware import (
        websocket_authorized,
        websocket_response_subprotocol,
    )
    from diapason.speech.realtime.bridge import VoiceLiveBridge
    from diapason.speech.realtime.factory import create_realtime_session

    expected_key = getattr(websocket.app.state, "api_key", "")
    if not websocket_authorized(websocket, expected_key):
        await websocket.close(code=1008)
        return

    await websocket.accept(subprotocol=websocket_response_subprotocol(websocket))
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
            allowed_tools = outils_demandes_par_le_client(str(raw["tools"]))
        if raw.get("instructions"):
            instructions = str(raw["instructions"])
        elif raw.get("include_memory", True):
            instructions = _load_system_instructions(
                websocket.app.state, enable_tools=enable_tools
            )

        # La voix nourrit la mémoire vivante COMME le chat (24 août 2026) :
        # sans ce raccord, un fait confié à l'oral — le mode d'usage
        # principal — attendait la consolidation de 3h30 du lendemain.
        def _vers_la_memoire(question: str, reponse: str) -> None:
            from diapason.memory.service import publish_completed_exchange

            publish_completed_exchange(
                getattr(websocket.app.state, "bus", None),
                question,
                reponse,
                source="voice.live",
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
                sur_echange=_vers_la_memoire,
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

    defaults = _realtime_defaults(request.app.state)
    from diapason.core.cloud_keys import get_cloud_key

    # Same resolution as the sessions themselves (env, then the desktop
    # Keychain) — a health check that looks in fewer places than the code it
    # describes reports "unconfigured" for keys that would in fact work.
    gemini = bool(get_cloud_key("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    openai = bool(get_cloud_key("OPENAI_API_KEY"))
    from diapason.speech.realtime.local_voice import local_voice_readiness

    # Local has no API key, but its optional STT/TTS stack and phonemizer must
    # exist too. Reporting only Ollama made the UI enable Start for a session
    # that was guaranteed to fail during Kokoro warm-up.
    local, local_reason = local_voice_readiness()
    tool_ids: list[str] = []
    if defaults.get("enable_tools"):
        try:
            from diapason.speech.realtime.tools import list_voice_tool_ids

            tool_ids = list_voice_tool_ids(
                _parse_tools_csv(defaults.get("tools") or "")
            )
        except Exception:
            tool_ids = []
    return {
        "available": defaults.get("enabled", True) and (gemini or openai or local),
        "enabled": defaults.get("enabled", True),
        "default_provider": defaults.get("provider", "gemini"),
        "enable_tools": defaults.get("enable_tools", True),
        "max_tool_steps": defaults.get("max_tool_steps", 6),
        "tools": tool_ids,
        "hotkey": "Alt+Space",
        "providers": {
            "gemini": {"configured": gemini},
            "openai": {"configured": openai},
            "local": {"configured": local, "reason": local_reason},
        },
    }


__all__ = ["voice_live_router"]
