#!/usr/bin/env python3
"""Micro-benchmark for the deterministic command router (no OS actions)."""

from __future__ import annotations

import argparse
import statistics
import time

from diapason.actions.router import FastActionRouter

SAMPLES = (
    "ouvre Notes",
    "open Safari",
    "cherche restaurants Montréal",
    "ouvre https://example.com",
    "ouvre Notes et écris rendez-vous à 14 h",
    "écris bonjour dans TextEdit",
    "Quelle est la capitale du Canada ?",
    "supprime tous mes fichiers",
)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--max-p95-ms", type=float, default=2.0)
    args = parser.parse_args()
    router = FastActionRouter()
    timings: list[float] = []
    for index in range(max(1, args.iterations)):
        text = SAMPLES[index % len(SAMPLES)]
        started = time.perf_counter()
        router.route(text)
        timings.append((time.perf_counter() - started) * 1000)
    p50 = statistics.median(timings)
    p95 = percentile(timings, 0.95)
    p99 = percentile(timings, 0.99)
    print(
        f"lightning-router n={len(timings)} "
        f"p50={p50:.4f}ms p95={p95:.4f}ms p99={p99:.4f}ms"
    )
    if p95 > args.max_p95_ms:
        print(f"FAIL: p95 exceeds {args.max_p95_ms:.2f}ms")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
