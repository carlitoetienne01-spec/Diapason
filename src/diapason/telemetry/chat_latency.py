"""Request-local chat timings; never infer queue time from generation time."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import aclosing, contextmanager
from contextvars import ContextVar
from typing import Any

from diapason.engine.scheduling import interactive_turn

logger = logging.getLogger(__name__)
_current: ContextVar[ChatLatency | None] = ContextVar("chat_latency", default=None)


class ChatLatency:
    """Measurements for one response, including its hidden generation passes."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter):
        self.clock = clock
        self.started = clock()
        self.request_id = uuid.uuid4().hex
        self.phases: dict[str, float] = {}
        self.first_model_text_ms: float | None = None
        self.first_text_ms: float | None = None
        self.inferences: list[dict[str, Any]] = []
        # Rempli quand un tour léger a été rerouté : le journal doit dire
        # quel modèle a vraiment répondu, pas celui du sélecteur.
        self.routage: dict[str, Any] | None = None
        # The exception a server generator caught and turned into an
        # "Error during generation" chunk followed by [DONE] — see
        # record_stream_error.
        self.stream_error: str | None = None

    def elapsed_ms(self) -> float:
        return round((self.clock() - self.started) * 1000, 3)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = self.clock()
        try:
            yield
        finally:
            self.phases[name] = round(
                self.phases.get(name, 0) + (self.clock() - started) * 1000, 3
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            **self.phases,
            "totalMs": self.elapsed_ms(),
            "firstModelTextMs": self.first_model_text_ms,
            "firstTextMs": self.first_text_ms,
            "routing": self.routage,
            "inferences": list(self.inferences),
        }


def record_queue_wait(wait_ms: float) -> None:
    measure = _current.get()
    if measure is not None:
        measure.phases["inferenceQueueMs"] = round(
            measure.phases.get("inferenceQueueMs", 0) + wait_ms, 3
        )


def record_stream_error(exc: BaseException) -> None:
    """Note that the response generator caught *exc* and carried on.

    28/09/2026 (review): routes._handle_stream and _handle_stream_tools catch
    every exception, emit "Error during generation: …" with finish_reason
    stop, then ``data: [DONE]``. measured_sse only saw the [DONE] and wrote
    ``completed=True end=done``: Ollama dying mid-reply read exactly like a
    normal answer in serve.err.log — a false SUCCESS (§100). The frames sent
    to the client do not change; only the log line learns the truth.
    """
    measure = _current.get()
    if measure is not None and measure.stream_error is None:
        measure.stream_error = type(exc).__name__


def mark_model_text() -> None:
    measure = _current.get()
    if measure is not None and measure.first_model_text_ms is None:
        measure.first_model_text_ms = measure.elapsed_ms()


def record_ollama_metrics(
    data: dict[str, Any], model: str, *, tools: list[dict[str, Any]] | None = None
) -> None:
    measure = _current.get()
    if measure is None:
        return
    # 19/09/2026: the shared engine's last usage belonged to whichever window
    # finished last. Keep native metrics with this request, not on the engine.
    metrics: dict[str, Any] = {"model": model}
    if tools is not None:
        # Counts only, never schemas/arguments: distinguish a slow model from
        # prefill spent reading tools that the turn does not actually use.
        metrics["toolSchemaCount"] = len(tools)
        rendu = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
        metrics["toolSchemaCharacters"] = len(rendu)
        # 20/09/2026 : deux trousses de même taille peuvent différer d'un
        # schéma ; l'empreinte dit si le préfixe rejoué par le préchauffage
        # est celui que le tour a vraiment envoyé. Une empreinte, pas un schéma.
        metrics["toolSchemaDigest"] = hashlib.sha256(rendu.encode()).hexdigest()[:12]
    for source, target, divisor in (
        ("load_duration", "loadMs", 1e6),
        ("prompt_eval_duration", "promptEvalMs", 1e6),
        ("eval_duration", "generationMs", 1e6),
        ("total_duration", "providerTotalMs", 1e6),
        ("prompt_eval_count", "promptTokensReported", 1),
        ("eval_count", "completionTokens", 1),
    ):
        value = data.get(source)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        ):
            metrics[target] = round(value / divisor, 3)
    if isinstance(data.get("done_reason"), str):
        metrics["finishReason"] = data["done_reason"]
    measure.inferences.append(metrics)


async def measured_sse(
    source: AsyncIterator[str | bytes], measure: ChatLatency
) -> AsyncIterator[str | bytes]:
    token = _current.set(measure)
    completed = False
    # 28/09/2026: a reply cut on the phone (26/09, 19:44) left
    # "completed=False" and nothing else — a client that went away and a
    # generator that raised read the same. `end` says which: done, no_done
    # (the source stopped without [DONE]), client_gone:cancelled (the
    # response task was cancelled — client disconnect or shutdown),
    # client_gone:closed (the reader stopped iterating — a failed send, the
    # tailnet gateway cutting a closed session), or error:<Type> (the source
    # raised, or caught an exception and said so in an error chunk before
    # [DONE] — record_stream_error).
    end = "aborted"
    try:
        # The server generators yield complete SSE frames. Close them on
        # cancellation as well; cancelling a client must release its inference.
        with interactive_turn():
            async with aclosing(source):
                async for frame in source:
                    text = frame.decode() if isinstance(frame, bytes) else frame
                    if text.startswith("data: ") and not text.startswith(
                        "data: [DONE]"
                    ):
                        try:
                            payload = json.loads(text[6:])
                        except (ValueError, TypeError):
                            yield frame
                            continue
                        if isinstance(payload, dict):
                            choices = payload.get("choices") or []
                            if any(c.get("delta", {}).get("content") for c in choices):
                                if measure.first_text_ms is None:
                                    measure.first_text_ms = measure.elapsed_ms()
                            if any(c.get("finish_reason") for c in choices):
                                payload.setdefault("telemetry", {})["performance"] = (
                                    measure.snapshot()
                                )
                                frame = f"data: {json.dumps(payload)}\n\n"
                    if text.startswith("data: [DONE]"):
                        completed = True
                    yield frame
        end = "done" if completed else "no_done"
        if measure.stream_error is not None:
            # A generation that failed and said so is not a completed reply,
            # whatever [DONE] followed it.
            end = f"error:{measure.stream_error}"
            completed = False
    except asyncio.CancelledError:
        end = "client_gone:cancelled"
        raise
    except GeneratorExit:
        end = "client_gone:closed"
        raise
    except Exception as exc:
        end = f"error:{type(exc).__name__}"
        raise
    finally:
        try:
            _current.reset(token)
        except ValueError:
            # 28/09/2026: a reader that stops without closing us (a send that
            # raised, ASGI 2.4) leaves this generator to the event loop's
            # asyncgen finaliser, which runs aclose() in ANOTHER task and
            # Context. reset() then raised "created in a different Context"
            # and the line below was never written — the one ending that most
            # needed it. That Context is discarded afterwards; nothing to undo.
            pass
        # Timings and counters only: no prompt, answer, key, path or tool args.
        logger.info(
            "chat_performance request=%s completed=%s end=%s metrics=%s",
            measure.request_id,
            completed,
            end,
            json.dumps(measure.snapshot()),
        )


def measure_response(response: Any, measure: ChatLatency) -> Any:
    measure.phases["preparationMs"] = measure.elapsed_ms()
    response.body_iterator = measured_sse(response.body_iterator, measure)
    response.headers["X-Diapason-Request-Id"] = measure.request_id
    return response
