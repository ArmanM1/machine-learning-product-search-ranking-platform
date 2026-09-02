"""Development-only API latency harness capped below production evidence volume."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CANDIDATE_COUNTS = (10, 20, 40)
CONCURRENCY_LEVELS = (1, 4, 8)
MAX_REQUESTS_PER_CONDITION = 50


def _json_request(
    base_url: str, path: str, payload: dict[str, Any] | None = None
) -> tuple[Any, float]:
    request = urllib.request.Request(
        urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method="GET" if payload is None else "POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(1_048_577)
        status = response.status
    elapsed = (time.perf_counter() - started) * 1000
    if status != 200 or len(raw) > 1_048_576:
        raise RuntimeError(f"{path} returned an invalid bounded response")
    return json.loads(raw), elapsed


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("cannot summarize an empty latency sample")
    return {
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "mean": statistics.fmean(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _rank_once(base_url: str, query_id: str, model_id: str, top_k: int) -> dict[str, Any]:
    try:
        response, elapsed = _json_request(
            base_url,
            "/api/v1/rank",
            {"query_id": query_id, "model_id": model_id, "top_k": top_k},
        )
        return {
            "ok": True,
            "end_to_end_ms": elapsed,
            "model_ms": float(response["latency_ms"]),
        }
    except (KeyError, TypeError, ValueError, RuntimeError, urllib.error.URLError) as error:
        return {"ok": False, "error_type": type(error).__name__}


def run_harness(
    base_url: str,
    *,
    model_id: str | None,
    measured_requests: int,
    warmup_requests: int,
) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("credentials must not be embedded in the benchmark URL")
    if not 1 <= measured_requests <= MAX_REQUESTS_PER_CONDITION:
        raise ValueError(
            f"measured requests must be between 1 and {MAX_REQUESTS_PER_CONDITION} per condition"
        )
    if not 0 <= warmup_requests <= 10:
        raise ValueError("warmup requests must be between 0 and 10")

    ready, first_ready_ms = _json_request(base_url, "/readyz")
    selected_model = model_id or str(ready["model_id"])
    queries, _ = _json_request(base_url, "/api/v1/queries?limit=50")
    by_count = {
        int(item["candidate_count"]): str(item["query_id"])
        for item in queries
        if int(item["candidate_count"]) in CANDIDATE_COUNTS
    }
    missing = set(CANDIDATE_COUNTS) - set(by_count)
    if missing:
        raise ValueError(
            f"curated benchmark queries are missing candidate counts: {sorted(missing)}"
        )

    first_observed: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    for candidate_count in CANDIDATE_COUNTS:
        query_id = by_count[candidate_count]
        cold = _rank_once(base_url, query_id, selected_model, candidate_count)
        first_observed.append(
            {"candidate_count": candidate_count, "concurrency": 1, "sample": cold}
        )
        for _ in range(warmup_requests):
            warmed = _rank_once(base_url, query_id, selected_model, candidate_count)
            if not warmed["ok"]:
                raise RuntimeError("warmup request failed")
        for concurrency in CONCURRENCY_LEVELS:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                samples = list(
                    executor.map(
                        lambda _, query=query_id, count=candidate_count: _rank_once(
                            base_url, query, selected_model, count
                        ),
                        range(measured_requests),
                    )
                )
            successful = [sample for sample in samples if sample["ok"]]
            end_to_end = [float(sample["end_to_end_ms"]) for sample in successful]
            model = [float(sample["model_ms"]) for sample in successful]
            conditions.append(
                {
                    "candidate_count": candidate_count,
                    "concurrency": concurrency,
                    "sample_count": len(samples),
                    "success_count": len(successful),
                    "failure_count": len(samples) - len(successful),
                    "end_to_end_ms": _summary(end_to_end) if end_to_end else None,
                    "model_ms": _summary(model) if model else None,
                    "raw_samples": samples,
                }
            )

    return {
        "schema_version": "1.0.0",
        "scope": "bounded_development_latency_harness",
        "model_id": selected_model,
        "origin": f"{parsed.scheme}://{parsed.netloc}",
        "first_ready_request_ms": first_ready_ms,
        "first_observed_requests": first_observed,
        "warmup_requests_per_candidate_count": warmup_requests,
        "conditions": conditions,
        "memory_measurement": None,
        "cpu_measurement": None,
        "model_load_measurement": None,
        "production_claim_eligible": False,
        "limitations": [
            "The harness is capped below 200 measured requests per primary condition.",
            "First-observed requests are not controlled Lambda cold-start measurements.",
            "Client-side timing cannot measure server CPU or resident memory.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--model-id")
    parser.add_argument("--measured-requests", type=int, default=8)
    parser.add_argument("--warmup-requests", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_harness(
            args.base_url,
            model_id=args.model_id,
            measured_requests=args.measured_requests,
            warmup_requests=args.warmup_requests,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, sort_keys=True))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote bounded development measurements to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
