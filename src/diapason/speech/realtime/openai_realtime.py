"""OpenAI Realtime API voice session."""

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
    openai_tools_schema,
)

logger = logging.getLogger(__name__)

_DEFAULT_URL = "wss://api.openai.com/v1/realtime"
_DEFAULT_MODEL = "gpt-4o-realtime-preview"


class OpenAIRealtimeSession(RealtimeVoiceSession):
    """Duplex audio session against OpenAI Realtime WebSocket API."""

    provider_id = "openai"
    input_sample_rate = 24000
    output_sample_rate = 24000

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
        voice: str = "alloy",
        instructions: str = "",
        language: str = "",
        enable_tools: bool = True,
        max_tool_steps: int = 12,
        allowed_tools: Optional[Sequence[str]] = None,
    ) -> None:
        from diapason.core.cloud_keys import get_cloud_key

        self._api_key = api_key or get_cloud_key("OPENAI_API_KEY")
        self._model = model or _DEFAULT_MODEL
        self._voice = voice or "alloy"
        self._instructions = instructions
        self._language = language
        self._enable_tools = enable_tools
        self._allowed_tools = list(allowed_tools) if allowed_tools else None
        self._budget = VoiceToolBudget(max_tool_steps)
        self._ws: Any = None
        self._queue: asyncio.Queue[Optional[SessionEvent]] = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._closed = False
        self._pending_args: dict[str, str] = {}

    async def connect(self) -> None:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY required for OpenAI Realtime")
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("websockets package required") from exc

        url = f"{_DEFAULT_URL}?model={self._model}"
        self._ws = await websockets.connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {self._api_key}",
                "OpenAI-Beta": "realtime=v1",
            },
            max_size=8 * 1024 * 1024,
            ping_interval=20,
        )
        session: dict[str, Any] = {
            "modalities": ["text", "audio"],
            "voice": self._voice,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": {
                "type": "server_vad",
                "create_response": True,
                "interrupt_response": True,
            },
            "input_audio_transcription": {"model": "whisper-1"},
        }
        if self._instructions:
            session["instructions"] = self._instructions
        if self._enable_tools:
            tools = openai_tools_schema(self._allowed_tools)
            if tools:
                session["tools"] = tools
                session["tool_choice"] = "auto"
        await self._ws.send(json.dumps({"type": "session.update", "session": session}))
        self._reader_task = asyncio.create_task(self._read_loop())

    async def send_audio(self, pcm16: bytes) -> None:
        if self._closed or self._ws is None or not pcm16:
            return
        await self._ws.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": pcm16_to_b64(pcm16),
                }
            )
        )

    async def send_text(self, text: str) -> None:
        if self._closed or self._ws is None or not text.strip():
            return
        self._budget.reset()  # a typed turn is a turn too
        await self._ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    },
                }
            )
        )
        await self._ws.send(json.dumps({"type": "response.create"}))

    async def interrupt(self) -> None:
        if self._closed or self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "response.cancel"}))
        except Exception:
            logger.debug("OpenAI interrupt send failed", exc_info=True)
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
                etype = data.get("type", "")
                if etype == "response.function_call_arguments.delta":
                    call_id = data.get("call_id") or data.get("item_id") or ""
                    self._pending_args[call_id] = (
                        self._pending_args.get(call_id, "") + (data.get("delta") or "")
                    )
                    continue
                if etype == "response.function_call_arguments.done":
                    await self._handle_function_done(data)
                    continue
                for event in self._parse_event(data):
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

    async def _handle_function_done(self, data: dict[str, Any]) -> None:
        assert self._ws is not None
        call_id = data.get("call_id") or ""
        name = data.get("name") or ""
        args_raw = data.get("arguments") or self._pending_args.pop(call_id, "{}")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except json.JSONDecodeError:
            args = {}

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
        await self._ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(payload),
                    },
                }
            )
        )
        await self._ws.send(json.dumps({"type": "response.create"}))

    def _parse_event(self, data: dict[str, Any]) -> list[SessionEvent]:
        events: list[SessionEvent] = []
        etype = data.get("type", "")

        if etype == "session.updated" or etype == "session.created":
            events.append(SessionEvent(kind="ready", raw=data))
        elif etype == "error":
            err = data.get("error") or {}
            detail = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            events.append(SessionEvent(kind="error", detail=detail, raw=data))
        elif etype in (
            "response.audio.delta",
            "response.output_audio.delta",
        ):
            delta = data.get("delta") or ""
            if delta:
                events.append(
                    SessionEvent(
                        kind="audio",
                        audio_b64=delta,
                        sample_rate=self.output_sample_rate,
                        raw=data,
                    )
                )
        elif etype in (
            "response.audio_transcript.delta",
            "response.output_audio_transcript.delta",
        ):
            delta = data.get("delta") or ""
            if delta:
                events.append(
                    SessionEvent(
                        kind="transcript",
                        role="assistant",
                        text=delta,
                        final=False,
                        raw=data,
                    )
                )
        elif etype in (
            "response.audio_transcript.done",
            "response.output_audio_transcript.done",
        ):
            text = data.get("transcript") or ""
            if text:
                events.append(
                    SessionEvent(
                        kind="transcript",
                        role="assistant",
                        text=text,
                        final=True,
                        raw=data,
                    )
                )
        elif etype == "conversation.item.input_audio_transcription.completed":
            text = data.get("transcript") or ""
            if text:
                events.append(
                    SessionEvent(
                        kind="transcript",
                        role="user",
                        text=text,
                        final=True,
                        raw=data,
                    )
                )
        elif etype in ("response.cancelled", "input_audio_buffer.speech_started"):
            if etype == "input_audio_buffer.speech_started":
                # New user speech = new turn: re-arm the per-turn tool budget.
                self._budget.reset()
            events.append(SessionEvent(kind="interrupted", raw=data))
        return events


__all__ = ["OpenAIRealtimeSession"]
