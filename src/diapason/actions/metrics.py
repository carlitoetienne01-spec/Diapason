"""Bounded, content-free latency metrics for lightning actions."""

from __future__ import annotations

import threading
from collections import Counter, deque
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any

from diapason.actions.models import ActionOutcome


@dataclass(slots=True, frozen=True)
class ActionMetric:
    action: str
    success: bool
    verified: bool
    route_ms: float
    execute_ms: float
    total_ms: float
    error_type: str = ""


class ActionMetrics:
    """Thread-safe ring buffer; deliberately excludes prompts and targets."""

    def __init__(self, maxlen: int = 500) -> None:
        self._items: deque[ActionMetric] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, outcome: ActionOutcome) -> None:
        item = ActionMetric(
            action=outcome.action,
            success=outcome.success,
            verified=outcome.verified,
            route_ms=round(outcome.route_ms, 3),
            execute_ms=round(outcome.execute_ms, 3),
            total_ms=round(outcome.total_ms, 3),
            error_type=outcome.error_type,
        )
        with self._lock:
            self._items.append(item)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            items = list(self._items)
        totals = sorted(i.total_ms for i in items)
        success = sum(i.success for i in items)
        counts = Counter(i.action for i in items)

        def percentile(p: float) -> float:
            if not totals:
                return 0.0
            return totals[min(len(totals) - 1, int((len(totals) - 1) * p))]

        return {
            "count": len(items),
            "success_rate": round(success / len(items), 4) if items else 0.0,
            "p50_ms": round(median(totals), 2) if totals else 0.0,
            "p95_ms": round(percentile(0.95), 2),
            "p99_ms": round(percentile(0.99), 2),
            "by_action": dict(counts),
            "recent": [asdict(i) for i in items[-25:]],
            "privacy": (
                "No prompts, typed text, URLs, paths, or app targets are stored."
            ),
        }


METRICS = ActionMetrics()

__all__ = ["ActionMetric", "ActionMetrics", "METRICS"]
