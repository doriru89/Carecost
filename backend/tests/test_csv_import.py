"""Import pipeline tests against az-data fixtures (PostgreSQL)."""

from pathlib import Path

import pytest

from app.db.tables import HospitalRate, Provider
from app.services.csv_import import import_az_directory

AZ_DATA = Path(__file__).resolve().parent.parent.parent / "data" / "az-data"


def test_import_az_providers_and_prices(db_session):
    if not AZ_DATA.exists():
        pytest.skip("az-data directory not available")
    counts = import_az_directory(db_session, AZ_DATA, price_hospital_id="bmc")
    db_session.commit()
    assert counts.get("providers_gi", 0) > 0
    assert counts.get("hospital_rates_gi", 0) > 0

    p = db_session.query(Provider).filter_by(npi="1811988488").first()
    assert p is not None
    assert "DIANE" in p.name.upper()
    assert "Gastroenterology" in p.specialties


def test_import_az_idempotent(db_session):
    if not AZ_DATA.exists():
        pytest.skip("az-data directory not available")
    counts1 = import_az_directory(db_session, AZ_DATA, price_hospital_id="bmc")
    db_session.commit()
    counts2 = import_az_directory(db_session, AZ_DATA, price_hospital_id="bmc")
    db_session.commit()
    assert counts1["providers_gi"] == counts2["providers_gi"]
    total_providers = sum(v for k, v in counts1.items() if k.startswith("providers"))
    row_count = db_session.query(Provider).filter_by(source="az_mvp").count()
    assert row_count == total_providers


def test_import_az_hospital_rates_content(db_session):
    if not AZ_DATA.exists():
        pytest.skip("az-data directory not available")
    import_az_directory(db_session, AZ_DATA, price_hospital_id="bmc")
    db_session.commit()

    p = db_session.query(Provider).filter_by(source="az_mvp").first()
    assert p is not None
    assert p.lat is not None
    assert p.lng is not None

    hr = db_session.query(HospitalRate).filter_by(hospital_id="bmc", cpt="45378").first()
    if hr is not None:
        assert hr.de_identified_min is not None
