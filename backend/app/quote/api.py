"""P1 minimal API: ``POST /api/quote`` on a fresh FastAPI app (the legacy ``app.main`` is untouched).

    cd backend
    # real data (needs pyarrow for the TiC parquet: the etl extra)
    CARECOST_HOSPITAL_BUILD=/path/to/data/build/20261024-10d8a893 \\
    CARECOST_TIC_ROOT=/path/to/data/intermediate/tic \\
      uv run --frozen --extra etl uvicorn app.quote.api:app --host 127.0.0.1 --port 8100
    # or the committed extract (no env vars)
      uv run --frozen uvicorn app.quote.api:app --host 127.0.0.1 --port 8100

Rate rows are loaded once at startup into in-memory dicts (no database per request). The response
is validated once by ``QuoteResponse`` inside the engine and returned as its JSON; the route does
not declare ``response_model`` (FastAPI would validate and serialize it a second time).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from pydantic import ValidationError

from app.quote.contracts import QuoteRequest
from app.quote.engine import Engine
from app.quote.slice_data import SliceData, load_from_env

PAGE_ORIGINS = ["http://127.0.0.1:5180", "http://localhost:5180"]


def create_app(
    data: SliceData | Callable[[], SliceData] = load_from_env,
    today: Callable[[], date] = date.today,
) -> FastAPI:
    """``data``: a loaded SliceData, or a loader called once at startup. ``today``: the as_of
    day freshness is computed for (per request, D18); tests pin it."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loaded = data() if callable(data) else data
        app.state.engine = Engine(loaded)
        app.state.today = today
        yield

    app = FastAPI(title="CareCost quote (P1 slice)", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware, allow_origins=PAGE_ORIGINS, allow_methods=["POST", "GET"],
        allow_headers=["content-type"],
    )  # fmt: skip

    @app.get("/api/health")
    def health(request: Request) -> dict:
        eng: Engine = request.app.state.engine
        return {
            "rows": eng.data.counts(),
            "build_id": eng.data.version.build_id,
            "tic_release": eng.data.version.tic_release,
        }

    @app.post("/api/quote")
    def quote(req: QuoteRequest, request: Request) -> Response:
        eng: Engine = request.app.state.engine
        try:
            resp = eng.quote(req, request.app.state.today())
        except ValidationError:
            raise  # the engine broke a contract rule: our bug, a 500, never a quote
        except ValueError as e:  # outside the P1 slice (other payer, manual codes, other site)
            raise HTTPException(status_code=422, detail=str(e)) from e
        return Response(resp.model_dump_json(), media_type="application/json")

    return app


app = create_app()
