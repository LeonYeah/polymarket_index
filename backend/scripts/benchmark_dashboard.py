from __future__ import annotations

import argparse
import json
import math
import time
from typing import Any

import httpx


DEFAULT_ENDPOINTS = (
    "/wallets/top?limit=100&high_confidence_only=false",
    "/markets?limit=100",
    "/alerts?limit=100&status=open&generate=false",
)
MINIMUM_ROWS = {
    "/wallets/top?limit=100&high_confidence_only=false": 100,
    "/markets?limit=100": 100,
}


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[index]


def benchmark(
    *, base_url: str, requests: int, warmup: int, timeout: float
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        for endpoint in DEFAULT_ENDPOINTS:
            for _ in range(warmup):
                client.get(endpoint).raise_for_status()
            durations_ms: list[float] = []
            returned = 0
            total = 0
            for _ in range(requests):
                started = time.perf_counter()
                response = client.get(endpoint)
                durations_ms.append((time.perf_counter() - started) * 1000)
                response.raise_for_status()
                pagination = response.json().get("pagination", {})
                returned = int(pagination.get("returned", 0))
                total = int(pagination.get("total", 0))
            results[endpoint] = {
                "requests": requests,
                "returned": returned,
                "total": total,
                "min_ms": round(min(durations_ms), 3),
                "median_ms": round(percentile(durations_ms, 0.50), 3),
                "p95_ms": round(percentile(durations_ms, 0.95), 3),
                "max_ms": round(max(durations_ms), 3),
                "minimum_rows": MINIMUM_ROWS.get(endpoint, 0),
            }
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Week07 dashboard API acceptance endpoints.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--p95-threshold-ms", type=float, default=500.0)
    args = parser.parse_args()
    if args.requests < 1 or args.warmup < 0:
        parser.error("--requests must be positive and --warmup must be non-negative")

    results = benchmark(
        base_url=args.base_url,
        requests=args.requests,
        warmup=args.warmup,
        timeout=args.timeout,
    )
    for row in results.values():
        row["latency_passed"] = row["p95_ms"] < args.p95_threshold_ms
        row["count_passed"] = row["returned"] >= row["minimum_rows"]
    payload = {
        "base_url": args.base_url,
        "p95_threshold_ms": args.p95_threshold_ms,
        "passed": all(row["latency_passed"] and row["count_passed"] for row in results.values()),
        "endpoints": results,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
