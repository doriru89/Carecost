"""The one CareCost backend app (D19): quote, catalog, chat, health. No database, no login.

    cd backend
    uv run --frozen uvicorn app.server:app --host 127.0.0.1 --port 8100

Data is loaded once at startup into memory:

* rate rows: ``CARECOST_QUOTE_PACK`` (the runtime SQLite pack, ``python -m app.quote.pack``). The
  committed test extract (``contracts/fixtures/rate_row_extract.csv``) only with
  ``CARECOST_ALLOW_EXTRACT=1`` (tests, local dev): otherwise startup fails (R11);
* sites: ``CARECOST_SITES_PATH`` or A3's ``data/sites/sites.yaml`` (208 sites);
* care paths, payer networks and rules from ``data/``.

Only the TiC rows of billing TINs the site registry links are kept in memory.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.chat.api import router as chat_router
from app.quote.api import router as quote_router
from app.quote.catalog import build_catalog, path_service_names
from app.quote.engine import Engine
from app.quote.registry import Registry
from app.quote.store import RateStore, load_from_env

DEV_ORIGINS = (
    "http://127.0.0.1:5180,http://localhost:5180,http://127.0.0.1:8080,http://localhost:8080,"
    "http://127.0.0.1:5173,http://localhost:5173"
)


def create_app(
    store: RateStore | Callable[..., RateStore] = load_from_env,
    *,
    registry: Registry | Callable[[], Registry] = Registry.load,
    today: Callable[[], date] = date.today,
) -> FastAPI:
    """``store``: a loaded RateStore, or a loader called once at startup with the registry's
    TINs. ``today``: the day freshness is computed for (per request, D18); tests pin it."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # R11: startup phases are logged so a slow cold start says which phase was slow
        t0 = time.perf_counter()
        reg = registry() if callable(registry) else registry
        t1 = time.perf_counter()
        data = store(tins=reg.tins, census_ids=reg.census_ids) if callable(store) else store
        t2 = time.perf_counter()
        app.state.engine = Engine(data, reg)
        t3 = time.perf_counter()
        print(
            f"carecost startup: registry {t1 - t0:.1f}s, rate rows {t2 - t1:.1f}s "
            f"({'lazy, per code' if data.partitions is not None else f'{len(data.rows)} rows'}), "
            f"engine {t3 - t2:.1f}s",
            file=sys.stderr,
            flush=True,
        )
        app.state.test_extract = callable(store) and not os.environ.get("CARECOST_QUOTE_PACK")
        app.state.catalog = build_catalog(reg)
        app.state.catalog_json = app.state.catalog.model_dump_json()
        app.state.catalog_names = path_service_names(reg)
        app.state.today = today
        yield

    app = FastAPI(title="CareCost", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    origins = os.environ.get("CARECOST_CORS_ORIGINS", DEV_ORIGINS).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins if o.strip()],
        allow_methods=["POST", "GET"],
        allow_headers=["content-type"],
    )
    app.include_router(quote_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    return app


app = create_app()
