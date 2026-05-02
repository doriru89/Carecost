"""Hospitals endpoint integration tests — normalized shape with dimension enrichment."""

from fastapi.testclient import TestClient


def test_hospitals_returns_200_with_normalized_shape(client: TestClient) -> None:
    r = client.get("/api/hospitals?cpt=45378")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0, "Expected at least one hospital"
    h = data[0]
    assert "payer_rates" in h
    assert "benchmarks" in h
    assert isinstance(h["payer_rates"], list)
    assert isinstance(h["benchmarks"], list)


def test_hospitals_has_dimension_fields(client: TestClient) -> None:
    r = client.get("/api/hospitals?cpt=45378")
    data = r.json()
    assert len(data) > 0
    h = data[0]
    for field in ["name", "lat", "lng", "metro_area", "hospital_id"]:
        assert field in h, f"Missing dimension field: {field}"
    assert h["lat"] is not None
    assert h["lng"] is not None


def test_hospitals_metro_area_filter(client: TestClient) -> None:
    r = client.get("/api/hospitals?cpt=45378&metro_area=boston")
    assert r.status_code == 200
    data = r.json()
    for h in data:
        assert h["metro_area"] == "boston", f"Hospital {h['name']} has wrong metro_area"


def test_hospitals_specialties_endpoint(client: TestClient) -> None:
    r = client.get("/api/hospitals/specialties")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    labels = {s["label"] for s in data}
    assert "Gastroenterology" in labels
    assert "Dermatology" in labels


def test_hospitals_missing_dim_graceful(client: TestClient) -> None:
    """CPT with no hospitals in dimension table should return empty, not 500."""
    r = client.get("/api/hospitals?cpt=99999")
    assert r.status_code == 200
    assert r.json() == []


def test_hospitals_excludes_seed_era_rows(seeded_db, client: TestClient) -> None:
    """Seed-era rows (source_file='') must not appear; ETL rows (source_file set) must."""
    from app.db.tables import HospitalPayerRate

    seed_row = HospitalPayerRate(
        hospital_id="bmc", cpt="45378", payer_id="TEST_SEED",
        negotiated_rate=100.0, plan_name="seed plan",
        source_file="", source_origin="mrf",
    )
    etl_row = HospitalPayerRate(
        hospital_id="bmc", cpt="45378", payer_id="TEST_ETL",
        negotiated_rate=200.0, plan_name="etl plan",
        source_file="etl_2026.csv", source_origin="mrf",
    )
    seeded_db.add_all([seed_row, etl_row])
    seeded_db.commit()

    r = client.get("/api/hospitals?cpt=45378")
    data = r.json()
    bmc = next((h for h in data if h["hospital_id"] == "bmc"), None)
    assert bmc is not None, "BMC not found in response"

    payer_ids = [pr["payer_id"] for pr in bmc["payer_rates"]]
    assert "test_etl" in payer_ids, "ETL row should appear in payer_rates"
    assert "test_seed" not in payer_ids, "Seed-era row should be excluded"
