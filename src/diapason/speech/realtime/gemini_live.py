"""Gemini Live (BidiGenerateContent) realtime voice session."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional, Sequence

from diapason.speech.realtime.base import RealtimeVoiceSession, SessionEvent
from diapason.speech.realtime.pcm import pcm16_to_b64
from diapason.speech.realtime.tools import (
    VoiceToolBudget,
    execute_voice_tool,
    gemini_function_declarations,
)

logger = logging.getLogger(__name__)

_DEFAULT_WS = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
_DEFAULT_MODEL = "gemini-2.0-flash-live-001"


class GeminiLiveSession(RealtimeVoiceSession):
    """Duplex audio session against Gemini Live over WebSockets."""

    provider_id = "gemini"
    input_sample_rate = 16000
    output_sample_rate = 24000

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
        voice: str = "Puck",
        instructions: str = "",
        language: str = "",
        enable_tools: bool = True,
        max_tool_steps: int = 12,
        allowed_tools: Optional[Sequence[str]] = None,
    ) -> None:
        from diapason.core.cloud_keys import get_cloud_key

        # Environment first, then the desktop app's Keychain store — the
        # LaunchAgent server never receives the app's env injection, so the
        # key pasted into Settings must be reachable from here too.
        self._api_key = api_key or get_cloud_key(
            "GEMINI_API_KEY", "GOOGLE_API_KEY"
        )
        self._model = model or _DEFAULT_MODEL
        self._voice = voice or "Zephyr"
        self._instructions = instructions
        self._language = language
        self._enable_tools = enable_tools
        self._allowed_tools = list(allowed_tools) if allowed_tools else None
        self._budget = VoiceToolBudget(max_tool_steps)
        self._ws: Any = None
        self._queue: asyncio.Queue[Optional[SessionEvent]] = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._closed = False

    async def connect(self) -> None:
        if not self._api_key:
            raise RuntimeError(
                "GEMINI_API_KEY or GOOGLE_API_KEY required for Gemini Live"
            )
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("websockets package required") from exc

        url = f"{_DEFAULT_WS}?key={self._api_key}"
        self._ws = await websockets.connect(
            url,
            max_size=8 * 1024 * 1024,
            ping_interval=20,
        )
        setup: dict[str, Any] = {
            "model": f"models/{self._model.removeprefix('models/')}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": self._voice},
                    }
                },
            },
        }
        if self._instructions:
            setup["systemInstruction"] = {
                "parts": [{"text": self._instructions}],
            }
        if self._enable_tools:
            decls = gemini_function_declarations(self._allowed_tools)
            if decls:
                setup["tools"] = [{"functionDeclarations": decls}]
        await self._ws.send(json.dumps({"setup": setup}))
        self._reader_task = asyncio.create_task(self._read_loop())
        await self._queue.put(SessionEvent(kind="ready"))

    async def send_audio(self, pcm16: bytes) -> None:
        if self._closed or self._ws is None or not pcm16:
            return
        msg = {
            "realtimeInput": {
                "audio": {
                    "data": pcm16_to_b64(pcm16),
                    "mimeType": f"audio/pcm;rate={self.input_sample_rate}",
                }
            }
        }
        await self._ws.send(json.dumps(msg))

    async def send_text(self, text: str) -> None:
        self._budget.reset()  # a typed turn is a turn too

        if self._closed or self._ws is None or not text.strip():
            return
        msg = {
            "clientContent": {
                "turns": [
                    {
                        "role": "user",
                        "parts": [{"text": text}],
                    }
                ],
                "turnComplete": True,
            }
        }
        await self._ws.send(json.dumps(msg))

    async def interrupt(self) -> None:
        if self._closed or self._ws is None:
            return
        try:
            await self._ws.send(
                json.dumps({"realtimeInput": {"activityEnd": {}}})
            )
        except Exception:
            logger.debug("Gemini interrupt send failed", exc_info=True)
        await self._queue.put(SessionEvent(kind="interrupted"))

    async def events(self) -> AsyncIterator[SessionEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        await self._queue.put(None)

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if self._closed:
                    break
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if "toolCall" in data:
                    await self._handle_tool_call(data["toolCall"])
                    continue
                for event in self._parse_server_message(data):
                    await self._queue.put(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                await self._queue.put(
                    SessionEvent(kind="error", detail=str(exc))
                )
        finally:
            await self._queue.put(SessionEvent(kind="closed"))
            await self._queue.put(None)

    async def _handle_tool_call(self, tool_call: dict[str, Any]) -> None:
        assert self._ws is not None
        responses: list[dict[str, Any]] = []
        for fc in tool_call.get("functionCalls") or []:
            name = fc.get("name") or ""
            call_id = fc.get("id") or ""
            args = fc.get("args") or {}
            if not self._budget.allow():
                payload = {
                    "ok": False,
                    "error": f"Voice tool budget exceeded ({self._budget.max_steps})",
                }
                ok = False
                detail = payload["error"]
            else:
                self._budget.consume()
                payload = await asyncio.to_thread(
                    execute_voice_tool, name, args, self._allowed_tools
                )
                ok = bool(payload.get("ok"))
                detail = str(payload.get("content") or payload.get("error") or "")
            await self._queue.put(
                SessionEvent(
                    kind="tool",
                    tool_name=name,
                    tool_ok=ok,
                    detail=detail,
                    text=name,
                )
            )
            responses.append(
                {
                    "id": call_id,
                    "name": name,
                    "response": payload,
                }
            )
        await self._ws.send(
            json.dumps({"toolResponse": {"functionResponses": responses}})
        )

    def _parse_server_message(self, data: dict[str, Any]) -> list[SessionEvent]:
        events: list[SessionEvent] = []
        if "error" in data:
            err = data["error"]
            detail = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            events.append(SessionEvent(kind="error", detail=detail, raw=data))
            return events

        sc = data.get("serverContent") or {}
        if sc.get("interrupted"):
            events.append(SessionEvent(kind="interrupted", raw=data))

        model_turn = sc.get("modelTurn") or {}
        for part in model_turn.get("parts") or []:
            inline = part.get("inlineData") or {}
            mime = (inline.get("mimeType") or "").lower()
            if "audio" in mime and inline.get("data"):
                events.append(
                    SessionEvent(
                        kind="audio",
                        audio_b64=inline["data"],
                        sample_rate=self.output_sample_rate,
                        raw=data,
                    )
                )
            text = part.get("text")
            if text:
                events.append(
                    SessionEvent(
                        kind="transcript",
                        role="assistant",
                        text=text,
                        final=False,
                        raw=data,
                    )
                )

        # The tool budget is a per-turn chain bound, not a session-lifetime
        # ration. turnComplete is the one boundary a real session actually
        # delivers (inputTranscription is opt-in and the setup never asks
        # for it); it also cannot re-arm an in-flight tool loop, because a
        # turn that keeps calling tools never completes.
        if sc.get("turnComplete"):
            self._budget.reset()

        input_tx = sc.get("inputTranscription") or {}
        if input_tx.get("text"):
            events.append(
                SessionEvent(
                    kind="transcript",
                    role="user",
                    text=input_tx["text"],
                    final=bool(sc.get("turnComplete")),
                    raw=data,
                )
            )
        output_tx = sc.get("outputTranscription") or {}
        if output_tx.get("text"):
            events.append(
                SessionEvent(
                    kind="transcript",
                    role="assistant",
                    text=output_tx["text"],
                    final=bool(sc.get("turnComplete")),
                    raw=data,
                )
            )
        return events


__all__ = ["GeminiLiveSession"]
