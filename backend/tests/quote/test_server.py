"""The one backend app (D19): quote, catalog, our-data, health, chat mounted at /api, GZip."""

from __future__ import annotations

import gzip
import json

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.quote.contracts import Catalog, OurDataResponse, QuoteResponse
from app.server import create_app
from tests.quote.conftest import AS_OF, FIX, fixture_doc


@pytest.fixture(scope="module")
def client(store, registry):
    with TestClient(create_app(store, registry=registry, today=lambda: AS_OF)) as c:
        yield c


@pytest.mark.parametrize("name", ["bcbs_hmo_shoulder", "cash_shoulder", "medicare_shoulder",
                                  "masshealth_manual"])  # fmt: skip
def test_post_quote_returns_the_golden_response(client, name):
    r = client.post("/api/quote", json=fixture_doc(f"quote_request_{name}"))
    assert r.status_code == 200, r.text
    QuoteResponse.model_validate(r.json())
    want = fixture_doc(f"quote_{name}")
    assert r.json() == want


def test_gzip_really_shrinks_the_payload(client):
    body = fixture_doc("quote_request_bcbs_hmo_shoulder")
    r = client.post("/api/quote", json=body, headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"
    raw = client.post("/api/quote", json=body, headers={"Accept-Encoding": "identity"})
    assert len(gzip.compress(raw.content)) < len(raw.content) / 4


def test_request_is_validated_by_the_contract(client):
    bad = fixture_doc("quote_request_bcbs_hmo_shoulder") | {"zip": "02138"}
    assert client.post("/api/quote", json=bad).status_code == 422


def test_unknown_payer_is_a_422(client):
    body = fixture_doc("quote_request_bcbs_hmo_shoulder")
    body["payment"]["payer_id"] = "NOT_A_PAYER"
    r = client.post("/api/quote", json=body)
    assert r.status_code == 422 and "unknown payer" in r.text


def test_catalog_browse_then_quote_a_service(client):
    """D3 Skip AI -> browse prices: list paths, list a path's services, quote one."""
    cat = Catalog.model_validate(client.get("/api/catalog").json())
    paths = client.get("/api/catalog/paths").json()
    assert {p["id"] for p in paths} == {p.id for p in cat.care_paths}
    svcs = client.get("/api/catalog/paths/shoulder_chronic_clicking_v1/services").json()
    xray = next(s for s in svcs if s["service_id"] == "svc_73030")
    primary = [c["code"] for c in xray["codes"] if c["role"] == "primary"]
    r = client.post("/api/quote", json={
        "payment": {"kind": "cash"}, "care_path_id": None, "answers": {},
        "service_codes": primary, "picked_by": "person", "site_ids": None,
    })  # fmt: skip
    assert r.status_code == 200
    assert client.get("/api/catalog/paths/nope_v1/services").status_code == 404


def test_catalog_covers_every_care_path_and_primary_code(registry):
    from app.quote.catalog import build_catalog

    cat = build_catalog(registry)
    assert {p.id for p in cat.care_paths} == set(registry.paths)
    listed = {(c.code, pid) for s in cat.services for c in s.codes for pid in s.care_paths}
    for pid, path in registry.paths.items():
        for st in path.steps:
            for c in st.cpts:
                if c.role == "primary" and not st.no_price:
                    assert (c.code, pid) in listed, (pid, st.id, c.code)
    # the committed catalog fixture (D's mock data) names the same services
    fx = json.loads((FIX / "catalog.json").read_text())
    assert {s["service_id"] for s in fx["services"]} == {s.service_id for s in cat.services}


def test_our_data_lists_both_freshness_sides(client):
    r = client.get("/api/our-data")
    body = OurDataResponse.model_validate(r.json())
    assert "tufts_mrf" in body.sources and "posted_afc_watertown" in body.sources


def test_health(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["rows"] > 1000 and h["build_id"] == "20261024-10d8a893"


def test_chat_router_is_mounted_at_api(store, registry):
    """C mounts app.chat.api.router at /api; the Chat stream fills it."""
    from app.chat import api as chat_api

    probe = APIRouter()

    @probe.get("/chat-probe")
    def _p() -> dict:
        return {"ok": True}

    chat_api.router.include_router(probe)
    try:
        with TestClient(create_app(store, registry=registry, today=lambda: AS_OF)) as c:
            assert c.get("/api/chat-probe").json() == {"ok": True}
    finally:
        chat_api.router.routes[:] = [
            r for r in chat_api.router.routes if getattr(r, "path", "") != "/chat-probe"
        ]
