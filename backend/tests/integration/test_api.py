"""HTTP contract tests against a seeded PostgreSQL test database (see conftest)."""

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_intake_missing_fields(client: TestClient) -> None:
    r = client.post("/api/intake", json={})
    assert r.status_code == 200
    body = r.json()
    assert "zip" in body["missing_required"]


def test_providers_list(client: TestClient) -> None:
    r = client.get("/api/providers")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    assert "hospital" in data[0]
    assert isinstance(data[0]["specialties"], list)


def test_estimate_returns_bundles_and_prices(client: TestClient) -> None:
    payload = {
        "intake": {
            "zip": "02118",
            "insurance_carrier": "Blue Cross Blue Shield of Massachusetts",
            "care_focus": "Gastroenterology",
            "deductible_cents": 200000,
            "oop_max_cents": 800000,
            "coinsurance_pct": 20,
            "copay_cents": 2500,
        }
    }
    r = client.post("/api/estimate", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["bundle_id"] == "colonoscopy_screening"
    assert len(body["estimates"]) > 0
    est = body["estimates"][0]
    assert est["allowed_amount_range"]["min"] <= est["allowed_amount_range"]["max"]


def test_confirm_apply_ready(client: TestClient) -> None:
    r = client.post(
        "/api/confirm/apply",
        json={
            "fields": {
                "zip": "02118",
                "insurance_carrier": "BCBS MA",
                "care_focus": "Gastroenterology",
            },
            "answers": {},
        },
    )
    assert r.status_code == 200
    assert r.json()["ready_for_estimate"] is True


def test_quality_endpoint_returns_payload(client: TestClient) -> None:
    r = client.get("/api/quality")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "generatedAt" in body
