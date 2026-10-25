"""P1 thin real slice: request -> engine -> validated QuoteResponse, on the committed extract.

The extract (contracts/fixtures/rate_row_extract.csv + .sources.yaml) is every rate row the two
golden quotes looked at, written by ``python -m app.quote.fixtures_gen`` from the real build, so
CI needs none of the 1 GB of data. The real-data load runs only where the data exists locally.
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.etl.contracts import PriceBasis
from app.quote.api import create_app
from app.quote.contracts import QuoteRequest, QuoteResponse
from app.quote.engine import Engine
from app.quote.slice_data import load_from_extract

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "contracts" / "fixtures"
AS_OF = date(2026, 10, 24)  # the day the golden fixtures were generated
PAYMENTS = ("bcbs_hmo", "cash")


def _doc(name: str) -> dict:
    doc = json.loads((FIX / f"{name}.json").read_text())
    doc.pop("_fixture")
    doc.pop("_schema")
    return doc


def _request(p: str) -> dict:
    return _doc(f"quote_request_{p}_shoulder")


@pytest.fixture(scope="module")
def data():
    return load_from_extract()


@pytest.fixture(scope="module")
def engine(data):
    return Engine(data)


@pytest.fixture(scope="module")
def client(data):
    with TestClient(create_app(data, today=lambda: AS_OF)) as c:
        yield c


# --------------------------------------------------------------------------- startup load


def test_startup_load_builds_the_in_memory_indexes(data):
    counts = data.counts()
    for sid in ("tufts_mrf", "mtauburn_mrf", "tic_bcbs_ma_hmo_blue_fi", "tic_bcbs_ma_hmo_blue_si"):
        assert counts[sid] > 0, sid
    assert set(data.sources) >= set(counts)  # every row has its freshness inputs
    assert data.version.build_id == "20261024-10d8a893"
    assert data.version.tic_release == "tic-2026-10"
    # every row can carry a contract Provenance (basename, sha, row_ref prefix), with no
    # placeholder allowance
    for r in data.rows.values():
        r.prov(PriceBasis.negotiated)
    assert len(data.rows) == sum(counts.values())
    # indexes: hospital rows by (file, code, payer); TiC rows by (file, TIN, code)
    assert data.hospital[("tufts_mrf", "73030", "BCBS_MA")]
    assert data.tic[("tic_bcbs_ma_hmo_blue_fi", "460903626", "99203")]
    # cash index keeps one row per distinct price, so a tall CSV's repeated cash column is small
    for rows in data.cash.values():
        keys = [(r.modifiers, r.component, r.setting, r.discounted_cash, r.gross) for r in rows]
        assert len(keys) == len(set(keys))


def test_startup_load_from_real_data_when_present():
    build = os.environ.get("CARECOST_HOSPITAL_BUILD")
    tic = os.environ.get("CARECOST_TIC_ROOT")
    if not (build and tic and Path(build).exists() and Path(tic).exists()):
        pytest.skip("set CARECOST_HOSPITAL_BUILD and CARECOST_TIC_ROOT to the local real data")
    pytest.importorskip("pyarrow")
    real = Engine.load_real(Path(build), Path(tic))
    ex = load_from_extract()
    for sid in ("tufts_mrf", "mtauburn_mrf", "tic_bcbs_ma_hmo_blue_fi"):
        assert real.counts()[sid] >= ex.counts()[sid]
    eng = Engine(real)
    for p in PAYMENTS:
        resp = eng.quote(QuoteRequest.model_validate(_request(p)), AS_OF)
        assert resp.model_dump(mode="json") == _doc(f"quote_{p}_shoulder")


# --------------------------------------------------------------------------- end to end


@pytest.mark.parametrize("payment", PAYMENTS)
def test_engine_reproduces_the_golden_fixture(engine, payment):
    resp = engine.quote(QuoteRequest.model_validate(_request(payment)), AS_OF)
    assert resp.model_dump(mode="json") == _doc(f"quote_{payment}_shoulder")


@pytest.mark.parametrize("payment", PAYMENTS)
def test_post_quote_returns_a_validated_response(client, payment):
    r = client.post("/api/quote", json=_request(payment), headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    body = r.json()
    QuoteResponse.model_validate(body)  # real data: no allow_placeholders
    assert body == _doc(f"quote_{payment}_shoulder")


def test_gzip_really_shrinks_the_payload(client):
    r = client.post("/api/quote", json=_request("bcbs_hmo"), headers={"Accept-Encoding": "gzip"})
    raw = len(r.content)
    packed = len(gzip.compress(r.content))
    assert packed < raw / 4


def test_bcbs_receipt_numbers_come_from_rows(engine, data):
    resp = engine.quote(QuoteRequest.model_validate(_request("bcbs_hmo")), AS_OF)
    for sq in resp.sites:
        for ln in sq.receipt.lines:
            if ln.cell is not None and ln.cell.kind == "money":
                rows = [r for r in data.rows.values() if r.row_ref == ln.cell.prov.row_ref]
                assert any(r.amount == ln.cell.low and r.code in ln.codes for r in rows)
                assert ln.cell.prov.payer_id == "BCBS_MA"


def test_cash_skips_a_site_without_a_loaded_cash_source(engine):
    resp = engine.quote(QuoteRequest.model_validate(_request("cash")), AS_OF)
    assert resp.sites_without_service == ["afc_watertown"]
    assert {sq.site.site_id for sq in resp.sites} == {
        "tufts_medical_center",
        "mount_auburn_hospital",
    }
    for sq in resp.sites:
        doctor = [ln for ln in sq.receipt.lines if ln.component == "professional"]
        assert doctor and all(ln.cell.kind == "no_source" for ln in doctor)


def test_freshness_is_computed_per_request(engine):
    """An image nobody rebuilt turns 'stale on our side' after our monthly schedule (D18)."""
    req = QuoteRequest.model_validate(_request("bcbs_hmo"))
    later = engine.quote(req, date(2026, 12, 1))
    assert "stale_on_our_side_sources" in later.notices
    assert all(s.freshness.stale_on_our_side for s in later.sources.values())
    assert all(not s.freshness.late_to_refresh for s in later.sources.values())
    assert all(sq.receipt.totals.likely.includes_stale_source for sq in later.sites)


def test_outside_the_slice_is_a_422(client):
    r = client.post("/api/quote", json=_doc("quote_request_medicare_shoulder"))
    assert r.status_code == 422
    assert "P1" in r.json()["detail"]
    bad = _request("bcbs_hmo") | {"site_ids": ["brigham_and_womens_hospital"]}
    assert client.post("/api/quote", json=bad).status_code == 422


def test_request_is_validated_by_the_contract(client):
    bad = _request("bcbs_hmo") | {"answers": {"Q1": ["<script>"]}}
    assert client.post("/api/quote", json=bad).status_code == 422


def test_health_reports_what_was_loaded(client):
    h = client.get("/api/health").json()
    assert h["build_id"] == "20261024-10d8a893" and h["rows"]["tufts_mrf"] > 0
