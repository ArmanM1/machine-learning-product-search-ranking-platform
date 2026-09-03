"""FastAPI public evidence and curated-reranking service."""

from __future__ import annotations

import importlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mangum import Mangum

from search_rank.logging import configure_logging, log_event
from search_rank.schemas.api import (
    ApiError,
    BenchmarkJudgment,
    ComparisonResponse,
    CuratedQuerySummary,
    HealthResponse,
    ModelSummary,
    PublicEvidenceEnvelope,
    PublicRequestIdentifier,
    RankedProduct,
    RankMovement,
    RankRequest,
    RankResponse,
    ReadyResponse,
)

from .dependencies import ServiceSettings, ServiceState

LOGGER = logging.getLogger(__name__)

_OBSERVABILITY_ROUTES = frozenset(
    {
        "/healthz",
        "/readyz",
        "/api/v1/models",
        "/api/v1/queries",
        "/api/v1/rank",
        "/api/v1/comparisons/{query_id}",
        "/api/v1/runs/{run_id}",
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _new_request_id(request: Request) -> str:
    """Accept only canonical UUID trace IDs; never echo arbitrary public text."""

    supplied = request.headers.get("x-request-id", "")
    try:
        return str(uuid.UUID(supplied))
    except (ValueError, AttributeError):
        return str(uuid.uuid4())


def _observability_route(request: Request) -> str:
    """Return a code-defined route template instead of the untrusted URL path."""

    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if template in _OBSERVABILITY_ROUTES else "unmatched"


def _error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request.state.error_code = code
    body = ApiError(status=status, code=code, message=message, request_id=_request_id(request))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _memory_used_mb() -> float | None:
    """Return peak process memory on Lambda/Linux without adding a runtime dependency."""

    try:
        resource = importlib.import_module("resource")
    except ImportError:  # pragma: no cover - the deployed Linux runtime provides resource
        return None
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def create_app(
    settings: ServiceSettings | None = None,
    *,
    state: ServiceState | None = None,
) -> FastAPI:
    settings = settings or ServiceSettings()
    service_state = state or ServiceState(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        if not service_state.ready:
            service_state.load()
        yield

    app = FastAPI(
        title="Machine Learning Product Search Ranking Platform",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.service = service_state

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        request.state.request_id = _new_request_id(request)
        request.state.model_id = None
        request.state.query_id = None
        request.state.candidate_count = None
        request.state.model_latency_ms = None
        request.state.error_code = None
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.maximum_body_bytes:
            response = _error(request, 413, "request_too_large", "Request body exceeds the limit.")
        else:
            response = await call_next(request)
        response.headers["x-request-id"] = _request_id(request)
        log_event(
            LOGGER,
            "api_request",
            request_id=_request_id(request),
            route=_observability_route(request),
            model_id=request.state.model_id,
            query_id=request.state.query_id,
            candidate_count=request.state.candidate_count,
            total_latency_ms=(time.perf_counter() - started) * 1000.0,
            model_latency_ms=request.state.model_latency_ms,
            memory_used_mb=_memory_used_mb(),
            status_code=response.status_code,
            error_code=request.state.error_code,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        return _error(request, 422, "validation_error", "Request validation failed.")

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        request.state.error_code = "internal_error"
        LOGGER.exception(
            "unhandled_api_error", extra={"context": {"request_id": _request_id(request)}}
        )
        return _error(request, 500, "internal_error", "Unexpected server error.")

    @app.get("/healthz", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(service_version=settings.service_version)

    @app.get("/readyz", response_model=ReadyResponse, responses={409: {"model": ApiError}})
    async def ready(request: Request) -> ReadyResponse | JSONResponse:
        if not service_state.ready:
            return _error(request, 409, "model_not_ready", "Model and evidence are not ready.")
        assert service_state.release_manifest is not None
        request.state.model_id = service_state.release_manifest["promoted_model_id"]
        return ReadyResponse(
            model_id=service_state.release_manifest["promoted_model_id"],
            dataset_manifest_hash=service_state.release_manifest["dataset_manifest_hash"],
        )

    @app.get("/api/v1/models", response_model=list[ModelSummary])
    async def models() -> list[ModelSummary]:
        return service_state.model_summaries()

    @app.get(
        "/api/v1/queries",
        response_model=list[CuratedQuerySummary],
        responses={409: {"model": ApiError}},
    )
    async def queries(
        request: Request,
        search: str = "",
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> list[CuratedQuerySummary] | JSONResponse:
        if not service_state.ready or not service_state.query_store:
            return _error(request, 409, "model_not_ready", "Query evidence is not ready.")
        return [
            CuratedQuerySummary(
                query_id=query.query_id,
                query=query.query,
                candidate_count=len(query.products),
            )
            for query in service_state.query_store.search(search, limit=limit)
        ]

    @app.post("/api/v1/rank", response_model=RankResponse)
    async def rank(request: Request, body: RankRequest) -> RankResponse | JSONResponse:
        if not service_state.ready:
            return _error(request, 409, "model_not_ready", "Model and evidence are not ready.")
        assert service_state.query_store is not None
        assert service_state.rankers is not None
        assert service_state.release_manifest is not None
        try:
            query = service_state.query_store.get(body.query_id)
        except KeyError:
            return _error(request, 404, "unknown_query", "Unknown curated query.")
        request.state.query_id = query.query_id
        request.state.candidate_count = len(query.products)
        ranker = service_state.rankers.get(body.model_id)
        if not ranker:
            return _error(request, 404, "unknown_model", "Unknown public model.")
        request.state.model_id = ranker.model_id
        if body.top_k > len(query.products):
            return _error(request, 422, "top_k_out_of_range", "top_k exceeds candidate count.")
        output = ranker.rank(query)
        request.state.model_latency_ms = output.latency_ms
        return RankResponse(
            request_id=_request_id(request),
            query_id=query.query_id,
            query=query.query,
            model_id=ranker.model_id,
            model_artifact_checksum=ranker.artifact_checksum,
            dataset_manifest_hash=service_state.release_manifest["dataset_manifest_hash"],
            candidate_count=len(query.products),
            top_k=body.top_k,
            latency_ms=output.latency_ms,
            results=[
                RankedProduct(
                    rank=item.rank,
                    product_id=item.product_id,
                    title=item.title,
                    score=item.score,
                )
                for item in output.results[: body.top_k]
            ],
        )

    @app.get("/api/v1/comparisons/{query_id}", response_model=ComparisonResponse)
    async def comparison(
        request: Request,
        query_id: PublicRequestIdentifier,
        baseline: PublicRequestIdentifier,
        candidate: PublicRequestIdentifier,
        include_judgments: bool = False,
    ) -> ComparisonResponse | JSONResponse:
        if not service_state.ready:
            return _error(request, 409, "model_not_ready", "Model and evidence are not ready.")
        assert service_state.query_store is not None
        assert service_state.rankers is not None
        try:
            query = service_state.query_store.get(query_id)
        except KeyError:
            return _error(request, 404, "unknown_query", "Unknown curated query.")
        request.state.query_id = query.query_id
        request.state.candidate_count = len(query.products)
        baseline_ranker = service_state.rankers.get(baseline)
        candidate_ranker = service_state.rankers.get(candidate)
        if not baseline_ranker or not candidate_ranker:
            return _error(request, 404, "unknown_model", "Unknown public model.")
        request.state.model_id = candidate_ranker.model_id
        baseline_output = baseline_ranker.rank(query)
        candidate_output = candidate_ranker.rank(query)
        request.state.model_latency_ms = candidate_output.latency_ms
        baseline_by_id = {item.product_id: item for item in baseline_output.results}
        candidate_by_id = {item.product_id: item for item in candidate_output.results}
        movements = [
            RankMovement(
                product_id=product.product_id,
                baseline_rank=baseline_by_id[product.product_id].rank,
                candidate_rank=candidate_by_id[product.product_id].rank,
                rank_delta=(
                    baseline_by_id[product.product_id].rank
                    - candidate_by_id[product.product_id].rank
                ),
            )
            for product in query.products
        ]
        judgments = (
            [
                BenchmarkJudgment(product_id=product.product_id, esci_label=product.esci_label)
                for product in query.products
                if product.esci_label is not None
            ]
            if include_judgments
            else None
        )
        return ComparisonResponse(
            request_id=_request_id(request),
            query_id=query.query_id,
            query=query.query,
            baseline_model_id=baseline,
            candidate_model_id=candidate,
            candidate_count=len(query.products),
            baseline_latency_ms=baseline_output.latency_ms,
            candidate_latency_ms=candidate_output.latency_ms,
            baseline_results=[RankedProduct(**item.__dict__) for item in baseline_output.results],
            candidate_results=[RankedProduct(**item.__dict__) for item in candidate_output.results],
            rank_movements=movements,
            benchmark_judgments=judgments,
        )

    @app.get(
        "/api/v1/runs/{run_id}",
        response_model=PublicEvidenceEnvelope,
        responses={404: {"model": ApiError}},
    )
    async def run_summary(
        request: Request, run_id: PublicRequestIdentifier
    ) -> PublicEvidenceEnvelope | JSONResponse:
        if not service_state.evidence or service_state.evidence.run.run_id != run_id:
            return _error(request, 404, "unknown_run", "Unknown public run.")
        assert service_state.release_manifest is not None
        request.state.model_id = service_state.release_manifest["promoted_model_id"]
        return service_state.evidence

    dist = settings.web_dist
    if Path(dist).is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


app = create_app()
handler = Mangum(app, lifespan="auto")
