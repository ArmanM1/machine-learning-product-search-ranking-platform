"""Bounded, read-only smoke test for a deployed or local ranking API."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class SmokeFailure(RuntimeError):
    """Raised when a release endpoint violates its public contract."""


def _request(base_url: str, path: str, payload: dict[str, Any] | None = None) -> tuple[Any, float]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="GET" if payload is None else "POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "search-rank-smoke/1.0",
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status
            raw = response.read(1_048_577)
    except urllib.error.HTTPError as error:
        raw = error.read(1_048_577)
        raise SmokeFailure(f"{path} returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise SmokeFailure(f"{path} could not be reached: {error.reason}") from error
    latency_ms = (time.perf_counter() - started) * 1000
    if status != 200:
        raise SmokeFailure(f"{path} returned HTTP {status}")
    if len(raw) > 1_048_576:
        raise SmokeFailure(f"{path} response exceeded 1 MiB")
    try:
        return json.loads(raw), latency_ms
    except json.JSONDecodeError as error:
        raise SmokeFailure(f"{path} did not return valid JSON") from error


def run_smoke(base_url: str, *, repeat: int) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("credentials must not be embedded in the smoke-test URL")
    if not 1 <= repeat <= 20:
        raise ValueError("repeat must be between 1 and 20")

    samples: list[float] = []
    health, latency = _request(base_url, "/healthz")
    samples.append(latency)
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise SmokeFailure("health response is not ok")
    ready, latency = _request(base_url, "/readyz")
    samples.append(latency)
    if not isinstance(ready, dict) or ready.get("status") != "ready":
        raise SmokeFailure("readiness response is not ready")
    models, latency = _request(base_url, "/api/v1/models")
    samples.append(latency)
    queries, latency = _request(base_url, "/api/v1/queries?limit=1")
    samples.append(latency)
    if not isinstance(models, list) or not models:
        raise SmokeFailure("model registry is empty")
    if not isinstance(queries, list) or not queries:
        raise SmokeFailure("curated query registry is empty")

    query = queries[0]
    query_id = str(query["query_id"])
    candidate_count = int(query["candidate_count"])
    promoted_id = str(ready["model_id"])
    model_ids = [str(item["model_id"]) for item in models]
    if promoted_id not in model_ids:
        raise SmokeFailure("ready model is absent from the public model registry")
    top_k = min(10, candidate_count)
    rank_latencies: list[float] = []
    for _ in range(repeat):
        ranking, latency = _request(
            base_url,
            "/api/v1/rank",
            {"query_id": query_id, "model_id": promoted_id, "top_k": top_k},
        )
        samples.append(latency)
        rank_latencies.append(latency)
        if not isinstance(ranking, dict) or len(ranking.get("results", [])) != top_k:
            raise SmokeFailure("rank response has an unexpected result count")

    baseline_id = next((model_id for model_id in model_ids if model_id != promoted_id), None)
    comparison_checked = False
    if baseline_id:
        query_string = urllib.parse.urlencode(
            {"baseline": baseline_id, "candidate": promoted_id, "include_judgments": "true"}
        )
        comparison, latency = _request(
            base_url, f"/api/v1/comparisons/{urllib.parse.quote(query_id)}?{query_string}"
        )
        samples.append(latency)
        comparison_checked = bool(
            isinstance(comparison, dict)
            and comparison.get("baseline_model_id") == baseline_id
            and comparison.get("candidate_model_id") == promoted_id
        )
        if not comparison_checked:
            raise SmokeFailure("comparison response did not preserve selected model IDs")

    return {
        "schema_version": "1.0.0",
        "status": "passed",
        "scope": "bounded_release_smoke",
        "base_url_origin": f"{parsed.scheme}://{parsed.netloc}",
        "model_id": promoted_id,
        "query_id": query_id,
        "candidate_count": candidate_count,
        "rank_requests": repeat,
        "comparison_checked": comparison_checked,
        "request_count": len(samples),
        "error_count": 0,
        "latency_ms": {
            "minimum": min(samples),
            "median": statistics.median(samples),
            "maximum": max(samples),
            "rank_median": statistics.median(rank_latencies),
        },
        "production_error_rate_claim_eligible": False,
        "note": "This bounded smoke is not the PRD's 100-request error-rate test.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_smoke(args.base_url, repeat=args.repeat)
    except (KeyError, TypeError, ValueError, SmokeFailure) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, sort_keys=True))
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
