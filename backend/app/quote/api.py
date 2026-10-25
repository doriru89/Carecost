"""Quote + catalog routes (``app.server`` mounts this router at ``/api``).

* ``POST /api/quote``: QuoteRequest -> QuoteResponse. The response is validated once by
  ``QuoteResponse`` inside the engine and returned as its JSON; the route declares no
  ``response_model`` (FastAPI would validate and serialize it a second time).
* ``GET /api/catalog``: D3 "Skip AI -> browse prices": every care path and every service.
  ``GET /api/catalog/paths`` and ``GET /api/catalog/paths/{path_id}/services`` are the two
  picker steps; the chosen service is then quoted with ``POST /api/quote`` and
  ``service_codes``.
* ``GET /api/our-data``: every loaded source with both freshness sides (D18), so "we are behind"
  (stale_on_our_side) is visible apart from "the publisher is late".
* ``GET /api/health``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import ValidationError

from app.quote.contracts import OurDataResponse, QuoteRequest
from app.quote.engine import Engine

router = APIRouter()


def _engine(request: Request) -> Engine:
    return request.app.state.engine


def _json(body: str) -> Response:
    return Response(body, media_type="application/json")


@router.post("/quote")
def quote(req: QuoteRequest, request: Request) -> Response:
    eng = _engine(request)
    try:
        resp = eng.quote(req, request.app.state.today())
    except ValidationError:
        raise  # the engine broke a contract rule: our bug, a 500, never a quote
    except ValueError as e:  # unknown payer / path / site, or a network that is not loaded
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _json(resp.model_dump_json())


@router.get("/catalog")
def catalog(request: Request) -> Response:
    return _json(request.app.state.catalog_json)


@router.get("/catalog/paths")
def catalog_paths(request: Request) -> list[dict]:
    return [p.model_dump(mode="json") for p in request.app.state.catalog.care_paths]


@router.get("/catalog/paths/{path_id}/services")
def catalog_path_services(path_id: str, request: Request) -> list[dict]:
    cat = request.app.state.catalog
    if path_id not in {p.id for p in cat.care_paths}:
        raise HTTPException(status_code=404, detail=f"unknown care path {path_id}")
    return [s.model_dump(mode="json") for s in cat.services if path_id in s.care_paths]


@router.get("/our-data")
def our_data(request: Request) -> Response:
    eng = _engine(request)
    as_of = request.app.state.today()
    metas = {**eng.store.sources, **eng.posted_by_source}
    sources = {
        sid: {
            "source_kind": m.source_kind,
            "publisher": m.publisher,
            "freshness": eng.freshness(m, as_of).model_dump(mode="json"),
        }
        for sid, m in sorted(metas.items())
    }
    body = OurDataResponse.model_validate({"as_of": as_of.isoformat(), "sources": sources})
    return _json(body.model_dump_json())


@router.get("/health")
def health(request: Request) -> dict:
    eng = _engine(request)
    return {
        "ok": True,
        "rows": len(eng.store.rows),
        "rows_by_source": eng.store.counts(),
        "build_id": eng.store.version.build_id,
        "tic_release": eng.store.version.tic_release,
        "sites": len(eng.reg.sites),
        "sites_version": eng.reg.sites_version,
        "care_paths": len(eng.reg.paths),
    }
