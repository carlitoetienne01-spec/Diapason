"""Bridge browser WebSocket clients to a provider realtime session."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from diapason.speech.realtime.base import RealtimeVoiceSession, SessionEvent
from diapason.speech.realtime.pcm import b64_to_pcm16, resample_pcm16

logger = logging.getLogger(__name__)


def event_to_client_json(event: SessionEvent) -> dict[str, Any]:
    """Serialize a :class:`SessionEvent` for the browser protocol."""
    if event.kind == "ready":
        return {"type": "ready"}
    if event.kind == "audio":
        return {
            "type": "audio",
            "data": event.audio_b64,
            "sample_rate": event.sample_rate,
        }
    if event.kind == "transcript":
        return {
            "type": "transcript",
            "role": event.role,
            "text": event.text,
            "final": event.final,
            "replace": event.replace,
        }
    if event.kind == "interrupted":
        return {"type": "interrupted"}
    if event.kind == "tool":
        return {
            "type": "tool",
            "name": event.tool_name,
            "ok": event.tool_ok,
            "detail": event.detail,
        }
    if event.kind == "error":
        return {"type": "error", "detail": event.detail or "unknown error"}
    if event.kind == "closed":
        return {"type": "closed"}
    return {"type": "error", "detail": f"unknown event {event.kind}"}


class VoiceLiveBridge:
    """Pump audio/control messages between a FastAPI WebSocket and a provider."""

    def __init__(
        self,
        client_ws: Any,
        session: RealtimeVoiceSession,
        *,
        client_input_rate: int = 16000,
    ) -> None:
        self._client = client_ws
        self._session = session
        self._client_input_rate = client_input_rate
        self._tasks: list[asyncio.Task[None]] = []

    async def run(self) -> None:
        await self._session.connect()
        forward = asyncio.create_task(self._forward_provider_events())
        receive = asyncio.create_task(self._receive_client_messages())
        self._tasks = [forward, receive]
        done, pending = await asyncio.wait(
            self._tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, asyncio.CancelledError):
                logger.debug("voice live bridge task error: %s", exc, exc_info=exc)
        await self._session.close()

    async def _forward_provider_events(self) -> None:
        async for event in self._session.events():
            await self._client.send_json(event_to_client_json(event))
            if event.kind in ("closed", "error"):
                break

    async def _receive_client_messages(self) -> None:
        from fastapi import WebSocketDisconnect

        try:
            while True:
                data = await self._client.receive_json()
                await self._handle_client_message(data)
        except WebSocketDisconnect:
            return
        except Exception:
            logger.debug("client receive ended", exc_info=True)
            return

    async def _handle_client_message(self, data: dict[str, Any]) -> None:
        msg_type = (data.get("type") or "").lower()
        if msg_type == "audio":
            b64 = data.get("data") or ""
            if not b64:
                return
            pcm = b64_to_pcm16(b64)
            rate = int(data.get("sample_rate") or self._client_input_rate)
            if rate != self._session.input_sample_rate:
                pcm = resample_pcm16(pcm, rate, self._session.input_sample_rate)
            await self._session.send_audio(pcm)
        elif msg_type == "text":
            await self._session.send_text(str(data.get("text") or ""))
        elif msg_type == "interrupt":
            await self._session.interrupt()
        elif msg_type == "stop":
            await self._session.close()
            return
        # "start" is handled by the route before the bridge is created


__all__ = ["VoiceLiveBridge", "event_to_client_json"]
