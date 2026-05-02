"""V2 hospitals endpoint integration tests — normalized shape with dimension enrichment."""

from fastapi.testclient import TestClient


def test_v2_hospitals_returns_200_with_normalized_shape(client: TestClient) -> None:
    r = client.get("/api/v2/hospitals?cpt=45378")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0, "Expected at least one hospital"
    h = data[0]
    assert "payer_rates" in h
    assert "benchmarks" in h
    assert isinstance(h["payer_rates"], list)
    assert isinstance(h["benchmarks"], list)


def test_v2_hospitals_has_dimension_fields(client: TestClient) -> None:
    r = client.get("/api/v2/hospitals?cpt=45378")
    data = r.json()
    assert len(data) > 0
    h = data[0]
    for field in ["name", "lat", "lng", "metro_area", "hospital_id"]:
        assert field in h, f"Missing dimension field: {field}"
    assert h["lat"] is not None
    assert h["lng"] is not None


def test_v2_hospitals_metro_area_filter(client: TestClient) -> None:
    r = client.get("/api/v2/hospitals?cpt=45378&metro_area=boston")
    assert r.status_code == 200
    data = r.json()
    for h in data:
        assert h["metro_area"] == "boston", f"Hospital {h['name']} has wrong metro_area"


def test_v2_hospitals_specialties_endpoint(client: TestClient) -> None:
    r = client.get("/api/v2/hospitals/specialties")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    labels = {s["label"] for s in data}
    assert "Gastroenterology" in labels
    assert "Dermatology" in labels


def test_v1_regression_still_returns_wide_format(client: TestClient) -> None:
    """V1 must still work — Phase 20 is strictly additive."""
    r = client.get("/api/hospitals?cpt=45378")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    h = data[0]
    assert "bcbs_price" in h, "V1 regression: bcbs_price field missing"


def test_v2_hospitals_missing_hospital_dim_graceful(client: TestClient) -> None:
    """CPT that has no hospitals in dimension table should return empty, not 500."""
    r = client.get("/api/v2/hospitals?cpt=99999")
    assert r.status_code == 200
    assert r.json() == []


def test_v2_excludes_seed_era_rows(client: TestClient) -> None:
    """V2 payer_rates must only contain ETL data (source_file != ''), not seed-era rows."""
    r = client.get("/api/v2/hospitals?cpt=45378")
    data = r.json()
    for h in data:
        for rate in h["payer_rates"]:
            assert "source_origin" in rate, "payer_rate missing source_origin field"
