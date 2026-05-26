"""Tests for hospital_query temporal filters (is_curated, rate_year)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.tables import Hospital, HospitalPayerRate, HospitalProcedure
from app.services.hospital_query import query_hospitals

CPT = "45378"


def _make_hospital(db: Session, hid: str, *, is_curated: bool = True) -> None:
    db.merge(
        Hospital(
            hospital_id=hid,
            name=f"Hospital {hid}",
            system_name="Test",
            state="MA",
            metro_area="boston",
            neighborhood="test",
            lat=42.0,
            lng=-71.0,
            npi=f"100000000{hid[-1]}",
            is_curated=is_curated,
        )
    )
    db.merge(
        HospitalProcedure(
            id=f"{hid}_{CPT}",
            hospital_id=hid,
            cpt=CPT,
            cpt_desc="Colonoscopy",
            gross_charge=5000.0,
        )
    )
    db.flush()


def _make_rate(
    db: Session,
    hid: str,
    payer_id: str,
    rate: float,
    *,
    rate_year: int = 0,
    source_file: str = "test.json",
    setting: str = "both",
    source_origin: str = "mrf",
) -> None:
    db.add(
        HospitalPayerRate(
            hospital_id=hid,
            cpt=CPT,
            payer_id=payer_id,
            negotiated_rate=rate,
            plan_name="Standard",
            source_origin=source_origin,
            billing_class="institutional",
            source_file=source_file,
            rate_year=rate_year,
            setting=setting,
        )
    )
    db.flush()


class TestIsCuratedFilter:
    def test_default_excludes_uncurated(self, db_session: Session):
        _make_hospital(db_session, "hosp_a", is_curated=True)
        _make_hospital(db_session, "hosp_b", is_curated=False)
        db_session.commit()

        results = query_hospitals(db_session, CPT)
        ids = {r["hospital_id"] for r in results}
        assert "hosp_a" in ids
        assert "hosp_b" not in ids

    def test_include_uncurated_shows_all(self, db_session: Session):
        _make_hospital(db_session, "hosp_a", is_curated=True)
        _make_hospital(db_session, "hosp_b", is_curated=False)
        db_session.commit()

        results = query_hospitals(db_session, CPT, include_uncurated=True)
        ids = {r["hospital_id"] for r in results}
        assert "hosp_a" in ids
        assert "hosp_b" in ids

    def test_all_curated_unchanged(self, db_session: Session):
        _make_hospital(db_session, "hosp_a", is_curated=True)
        _make_hospital(db_session, "hosp_b", is_curated=True)
        db_session.commit()

        results = query_hospitals(db_session, CPT)
        assert len(results) == 2


class TestRateYearFilter:
    def test_explicit_rate_year_filters(self, db_session: Session):
        _make_hospital(db_session, "hosp_a")
        _make_rate(db_session, "hosp_a", "bcbs_ma", 1000.0, rate_year=2025)
        _make_rate(db_session, "hosp_a", "bcbs_ma", 1100.0, rate_year=2026)
        db_session.commit()

        results = query_hospitals(db_session, CPT, rate_year=2026)
        rates = results[0]["payer_rates"]
        assert len(rates) == 1
        assert rates[0]["negotiated_rate"] == 1100.0

    def test_no_rate_year_returns_all(self, db_session: Session):
        _make_hospital(db_session, "hosp_a")
        _make_rate(db_session, "hosp_a", "bcbs_ma", 1000.0, rate_year=2025)
        _make_rate(db_session, "hosp_a", "bcbs_ma", 1100.0, rate_year=2026)
        db_session.commit()

        results = query_hospitals(db_session, CPT)
        rates = results[0]["payer_rates"]
        assert len(rates) == 2

    def test_rate_year_provenance_in_response(self, db_session: Session):
        _make_hospital(db_session, "hosp_a")
        _make_rate(db_session, "hosp_a", "bcbs_ma", 1100.0, rate_year=2026)
        db_session.commit()

        results = query_hospitals(db_session, CPT)
        rate = results[0]["payer_rates"][0]
        assert rate["rate_year"] == 2026


class TestSettingInResponse:
    def test_setting_included_in_payer_rates(self, db_session: Session):
        _make_hospital(db_session, "hosp_a")
        _make_rate(db_session, "hosp_a", "bcbs_ma", 3000.0, setting="outpatient")
        db_session.commit()

        results = query_hospitals(db_session, CPT)
        rate = results[0]["payer_rates"][0]
        assert rate["setting"] == "outpatient"

    def test_all_setting_values_preserved(self, db_session: Session):
        _make_hospital(db_session, "hosp_a")
        _make_rate(db_session, "hosp_a", "bcbs_ma", 1000.0, setting="both")
        _make_rate(db_session, "hosp_a", "aetna", 2000.0, setting="outpatient")
        _make_rate(
            db_session, "hosp_a", "uhc", 1500.0, setting="facility", source_origin="tic"
        )
        db_session.commit()

        results = query_hospitals(db_session, CPT)
        settings = {r["setting"] for r in results[0]["payer_rates"]}
        assert settings == {"both", "outpatient", "facility"}
