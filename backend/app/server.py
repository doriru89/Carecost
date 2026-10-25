"""The one CareCost backend app (D19): quote, catalog, chat, health. No database, no login.

    cd backend
    uv run --frozen uvicorn app.server:app --host 127.0.0.1 --port 8100

Data is loaded once at startup into memory:

* rate rows: ``CARECOST_QUOTE_PACK`` (the runtime SQLite pack, ``python -m app.quote.pack``) or,
  when unset, the committed extract (``contracts/fixtures/rate_row_extract.csv``);
* sites: ``CARECOST_SITES_PATH`` (A3's ``data/sites/sites.yaml``) or ``contracts/fixtures/sites.json``;
* care paths, payer networks and rules from ``data/``.

Only the TiC rows of billing TINs the site registry links are kept in memory.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.chat.api import router as chat_router
from app.quote.api import router as quote_router
from app.quote.catalog import build_catalog
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
        reg = registry() if callable(registry) else registry
        data = store(tins=reg.tins) if callable(store) else store
        app.state.engine = Engine(data, reg)
        app.state.catalog = build_catalog(reg)
        app.state.catalog_json = app.state.catalog.model_dump_json()
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
