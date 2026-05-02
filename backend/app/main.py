from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Awaitable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.registries import validate_all_registries
from app.routes import api_router

settings = get_settings()
logger = logging.getLogger(__name__)


class _LatencyTracker:
    def __init__(self, maxlen: int) -> None:
        self.samples_ms: deque[float] = deque(maxlen=maxlen)
        self.request_count = 0

    def add_sample(self, elapsed_ms: float) -> None:
        self.samples_ms.append(elapsed_ms)
        self.request_count += 1

    def percentile(self, p: float) -> float:
        if not self.samples_ms:
            return 0.0
        samples = sorted(self.samples_ms)
        idx = int(round((len(samples) - 1) * p))
        return samples[max(0, min(idx, len(samples) - 1))]


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    counts = validate_all_registries()
    logger.info(
        "registries loaded: %d bundles, %d hospitals, %d payers, %d specialties",
        counts["bundles"], counts["hospitals"], counts["payers"], counts["specialties"],
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=_lifespan)
    latency_tracker = _LatencyTracker(maxlen=max(10, settings.latency_metrics_window_size))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def latency_metrics_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        latency_tracker.add_sample(elapsed_ms)

        if (
            settings.latency_metrics_log_every_n_requests > 0
            and latency_tracker.request_count % settings.latency_metrics_log_every_n_requests == 0
        ):
            logger.info(
                "latency_metrics p50=%.1fms p95=%.1fms sample_size=%d",
                latency_tracker.percentile(0.50),
                latency_tracker.percentile(0.95),
                len(latency_tracker.samples_ms),
            )
        return response

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
