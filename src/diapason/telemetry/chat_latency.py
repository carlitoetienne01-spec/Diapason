"""Request-local chat timings; never infer queue time from generation time."""

from __future__ import annotations

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
    finally:
        _current.reset(token)
        # Timings and counters only: no prompt, answer, key, path or tool args.
        logger.info(
            "chat_performance request=%s completed=%s metrics=%s",
            measure.request_id,
            completed,
            json.dumps(measure.snapshot()),
        )


def measure_response(response: Any, measure: ChatLatency) -> Any:
    measure.phases["preparationMs"] = measure.elapsed_ms()
    response.body_iterator = measured_sse(response.body_iterator, measure)
    response.headers["X-Diapason-Request-Id"] = measure.request_id
    return response
