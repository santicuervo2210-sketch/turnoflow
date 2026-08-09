from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from math import ceil
from time import perf_counter

import httpx


@dataclass(frozen=True)
class RequestResult:
    duration_ms: float
    status_code: int | None


def percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, ceil((percent / 100) * len(ordered)) - 1)
    return ordered[index]


def summarize(results: list[RequestResult]) -> dict[str, float | int]:
    durations = [result.duration_ms for result in results]
    errors = sum(
        result.status_code is None or result.status_code >= 400
        for result in results
    )
    return {
        "requests": len(results),
        "errors": errors,
        "error_rate": errors / len(results) if results else 1.0,
        "p50_ms": round(percentile(durations, 50), 2),
        "p95_ms": round(percentile(durations, 95), 2),
        "p99_ms": round(percentile(durations, 99), 2),
    }


def _request(url: str, timeout_seconds: float) -> RequestResult:
    started_at = perf_counter()
    try:
        response = httpx.get(url, timeout=timeout_seconds, follow_redirects=False)
        return RequestResult((perf_counter() - started_at) * 1000, response.status_code)
    except httpx.HTTPError:
        return RequestResult((perf_counter() - started_at) * 1000, None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke de carga HTTP para TurnoFlow.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=1000.0)
    args = parser.parse_args()
    if args.requests <= 0 or args.concurrency <= 0:
        parser.error("requests y concurrency deben ser mayores a cero")

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(
            executor.map(
                lambda _: _request(args.url, args.timeout),
                range(args.requests),
            )
        )
    summary = summarize(results)
    print(
        "requests={requests} errors={errors} error_rate={error_rate:.2%} "
        "p50_ms={p50_ms} p95_ms={p95_ms} p99_ms={p99_ms}".format(**summary)
    )
    if summary["error_rate"] > args.max_error_rate or summary["p95_ms"] > args.max_p95_ms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
