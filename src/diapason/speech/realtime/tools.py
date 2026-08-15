"""Safe desktop tools for realtime voice sessions (capped step budget)."""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

# Diapason-parity allow-list for live voice.
DEFAULT_VOICE_TOOL_IDS: tuple[str, ...] = (
    "open_anything",
    "open_uri",
    "focus_app",
    "open_browser_on_monitor",
    "run_voice_command",
    "calendar_query",
    "spotify_play",
    "web_search",
    "find_files",
    "mail_compose",
    "messages_compose",
    "mail_send",
    "messages_send",
    "screen_describe",
    "screen_share_start",
    "screen_share_stop",
    "screen_share_status",
    "succes_tasks",
    "succes_workspace",
    "succes_continuity",
)

# (module, [(registry_key, attribute_name), ...])
_TOOL_MODULES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "diapason.tools.desktop_tools",
        (
            ("open_anything", "OpenAnythingTool"),
            ("open_uri", "OpenUriTool"),
            ("focus_app", "FocusAppTool"),
            ("open_browser_on_monitor", "OpenBrowserOnMonitorTool"),
            ("run_voice_command", "RunVoiceCommandTool"),
        ),
    ),
    (
        "diapason.tools.voice_mac_tools",
        (
            ("calendar_query", "CalendarQueryTool"),
            ("spotify_play", "SpotifyPlayTool"),
            ("find_files", "FindFilesTool"),
            ("mail_compose", "MailComposeTool"),
            ("messages_compose", "MessagesComposeTool"),
            ("mail_send", "MailSendTool"),
            ("messages_send", "MessagesSendTool"),
        ),
    ),
    (
        "diapason.tools.screen_vision_tools",
        (
            ("screen_describe", "ScreenDescribeTool"),
            ("screen_share_start", "ScreenShareStartTool"),
            ("screen_share_stop", "ScreenShareStopTool"),
            ("screen_share_status", "ScreenShareStatusTool"),
        ),
    ),
    (
        "diapason.tools.web_search",
        (("web_search", "WebSearchTool"),),
    ),
    (
        "diapason.tools.succes_tasks",
        (("succes_tasks", "SuccesTasksTool"),),
    ),
    (
        "diapason.tools.succes_workspace",
        (("succes_workspace", "SuccesWorkspaceTool"),),
    ),
    (
        "diapason.tools.succes_continuity",
        (("succes_continuity", "SuccesContinuityTool"),),
    ),
)


def _ensure_desktop_tools_loaded() -> None:
    """Import and (re)register voice tools — safe after ToolRegistry.clear()."""
    from diapason.core.registry import ToolRegistry

    for mod_name, entries in _TOOL_MODULES:
        try:
            mod = __import__(mod_name, fromlist=[name for _, name in entries])
        except Exception:
            logger.debug("could not load %s", mod_name, exc_info=True)
            continue
        for key, attr in entries:
            if ToolRegistry.contains(key):
                continue
            cls = getattr(mod, attr, None)
            if cls is None:
                continue
            try:
                ToolRegistry.register_value(key, cls)
            except Exception:
                logger.debug("could not register %s", key, exc_info=True)


def list_voice_tool_ids(
    allowed: Optional[Sequence[str]] = None,
) -> list[str]:
    _ensure_desktop_tools_loaded()
    from diapason.core.registry import ToolRegistry

    wanted = tuple(allowed) if allowed else DEFAULT_VOICE_TOOL_IDS
    available = set(ToolRegistry.keys())
    return [tid for tid in wanted if tid in available]


def gemini_function_declarations(
    allowed: Optional[Sequence[str]] = None,
) -> list[dict[str, Any]]:
    """Gemini Live ``functionDeclarations`` list."""
    _ensure_desktop_tools_loaded()
    from diapason.core.registry import ToolRegistry

    decls: list[dict[str, Any]] = []
    for tid in list_voice_tool_ids(allowed):
        try:
            tool = ToolRegistry.create(tid)
        except Exception:
            continue
        spec = tool.spec
        decls.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters or {"type": "object", "properties": {}},
            }
        )
    return decls


def openai_tools_schema(
    allowed: Optional[Sequence[str]] = None,
) -> list[dict[str, Any]]:
    """OpenAI Realtime ``session.tools`` entries."""
    _ensure_desktop_tools_loaded()
    from diapason.core.registry import ToolRegistry

    out: list[dict[str, Any]] = []
    for tid in list_voice_tool_ids(allowed):
        try:
            tool = ToolRegistry.create(tid)
        except Exception:
            continue
        out.append(tool.to_openai_function())
    return out


def execute_voice_tool(
    name: str,
    arguments: Optional[dict[str, Any]] = None,
    allowed: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Run a allow-listed tool; returns a JSON-serializable payload."""
    _ensure_desktop_tools_loaded()
    from diapason.core.registry import ToolRegistry

    tid = (name or "").strip()
    allowed_set = set(list_voice_tool_ids(allowed))
    if tid not in allowed_set:
        return {"ok": False, "error": f"Tool not allowed in voice mode: {tid}"}
    try:
        args = dict(arguments or {})
        # Never auto-send from live voice — drafts only.
        if tid in ("mail_compose", "messages_compose"):
            args.pop("send", None)
        tool = ToolRegistry.create(tid)
        result = tool.execute(**args)
        return {
            "ok": bool(result.success),
            "content": result.content,
            "metadata": getattr(result, "metadata", None) or {},
        }
    except Exception as exc:
        logger.exception("voice tool %s failed", tid)
        return {"ok": False, "error": str(exc)}


class VoiceToolBudget:
    """Limit chained tool calls inside one TURN.

    The cap used to be per-session and never reset: after twelve tool calls
    spread over a long conversation, every later "joue X" silently failed
    with "budget exceeded" for the rest of the session. The loop bound it
    exists for (a model asking for tools forever) is a per-turn problem.
    """

    def __init__(self, max_steps: int = 12) -> None:
        self.max_steps = max(0, int(max_steps))
        self.used = 0

    def allow(self) -> bool:
        return self.used < self.max_steps

    def consume(self) -> None:
        self.used += 1

    def reset(self) -> None:
        self.used = 0


__all__ = [
    "DEFAULT_VOICE_TOOL_IDS",
    "VoiceToolBudget",
    "execute_voice_tool",
    "gemini_function_declarations",
    "list_voice_tool_ids",
    "openai_tools_schema",
]
