"""Hospital endpoint contract tests — all payer prices must be present."""

from fastapi.testclient import TestClient


def test_hospitals_returns_all_payer_prices(client: TestClient) -> None:
    """GET /api/hospitals must return all 4 payer prices + metadata fields."""
    r = client.get("/api/hospitals?cpt=45378")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0, "Expected at least one hospital"
    h = data[0]
    for field in [
        "bcbs_price",
        "aetna_price",
        "harvard_pilgrim_price",
        "uhc_price",
    ]:
        assert field in h, f"Missing payer field: {field}"
    assert "cpt_desc" in h
    assert "gross_charge" in h
    assert "discounted_cash" in h
