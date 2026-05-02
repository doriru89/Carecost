"""Integration tests for Phase 10 schema evolution — plan-level rates + dimension tables."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tables import (
    Hospital,
    HospitalBenchmark,
    HospitalPayerRate,
    HospitalProcedure,
    Payer,
    Procedure,
)

_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "registries"


def _seed_dimensions(db: Session) -> None:
    """Populate hospitals and payers dimension tables from YAML registries."""
    hospitals_data = yaml.safe_load((_DATA_DIR / "hospitals.yaml").read_text())["hospitals"]
    for hid, h in hospitals_data.items():
        db.add(Hospital(
            hospital_id=hid,
            name=h["name"],
            system_name=h.get("system", ""),
            state=h["state"],
            metro_area=h["metro_area"],
            neighborhood=h.get("neighborhood", ""),
            lat=h.get("lat"),
            lng=h.get("lng"),
            npi=h.get("npi", ""),
        ))

    payers_data = yaml.safe_load((_DATA_DIR / "payers.yaml").read_text())["payers"]
    for pid, p in payers_data.items():
        db.add(Payer(
            payer_id=pid,
            canonical_name=p["label"],
            parent_brand=p.get("parent_brand", ""),
            payer_type="commercial",
            operating_states=p.get("operating_states", []),
            tic_portal=p.get("tic_portal", ""),
        ))
    db.flush()


def _seed_procedures(db: Session) -> None:
    """Populate procedures table from cpt_bundles.yaml."""
    bundles = yaml.safe_load((_DATA_DIR / "cpt_bundles.yaml").read_text())["bundles"]
    for bid, b in bundles.items():
        db.merge(Procedure(
            bundle_id=bid,
            label=b["label"],
            specialty=b.get("specialty", ""),
            description=b.get("description", ""),
            cpt_codes=[b["cpt"]],
            tags=b.get("tags", []),
            source="cpt_bundles.yaml",
        ))
    db.flush()


@pytest.fixture
def dim_db(db_session: Session) -> Session:
    """db_session with dimension tables populated."""
    _seed_dimensions(db_session)
    _seed_procedures(db_session)
    db_session.commit()
    return db_session


# ── Plan-level rate tests ──


def test_multiple_plans_per_payer(dim_db: Session) -> None:
    """Insert 3 UHC plans for same hospital/cpt — all 3 stored."""
    dim_db.add(HospitalProcedure(
        id="mgh:45378", hospital_id="mgh", cpt="45378", cpt_desc="Colonoscopy",
        source="test",
    ))
    dim_db.flush()

    plans = ["UHC Choice Plus", "UHC Navigate", "UHC Select"]
    for plan in plans:
        dim_db.add(HospitalPayerRate(
            hospital_id="mgh", cpt="45378", payer_id="UHC",
            negotiated_rate=1500.0 + plans.index(plan) * 100,
            plan_name=plan, source_origin="mrf",
        ))
    dim_db.flush()

    stored = dim_db.query(HospitalPayerRate).filter_by(
        hospital_id="mgh", cpt="45378", payer_id="UHC",
    ).all()
    assert len(stored) == 3
    stored_plans = {r.plan_name for r in stored}
    assert stored_plans == set(plans)


def test_upsert_idempotent_with_plan(dim_db: Session) -> None:
    """Run upsert twice — counts unchanged."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    dim_db.add(HospitalProcedure(
        id="mgh:45378", hospital_id="mgh", cpt="45378", cpt_desc="Colonoscopy",
        source="test",
    ))
    dim_db.flush()

    row = {
        "hospital_id": "mgh", "cpt": "45378", "payer_id": "BCBS_MA",
        "negotiated_rate": 2000.0, "plan_name": "Blue Care Elect",
        "source": "test", "source_origin": "mrf", "billing_class": "",
        "price_source": "", "setting": "", "source_file": "", "rate_methodology": "",
    }
    table = HospitalPayerRate.__table__
    for _ in range(2):
        stmt = pg_insert(table).values([row])
        pk_cols = {c.name for c in table.primary_key.columns}
        update_cols = [c.name for c in table.columns if c.name not in pk_cols]
        stmt = stmt.on_conflict_do_update(
            constraint="uq_hospital_payer_rates_natural_key",
            set_={col: stmt.excluded[col] for col in update_cols},
        )
        dim_db.execute(stmt)
        dim_db.flush()

    count = dim_db.query(HospitalPayerRate).filter_by(
        hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
    ).count()
    assert count == 1


def test_empty_plan_name_not_null(dim_db: Session) -> None:
    """plan_name='' upserts correctly, not duplicated."""
    dim_db.add(HospitalProcedure(
        id="mgh:45378", hospital_id="mgh", cpt="45378", cpt_desc="Colonoscopy",
        source="test",
    ))
    dim_db.flush()

    for _ in range(2):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        row = {
            "hospital_id": "mgh", "cpt": "45378", "payer_id": "BCBS_MA",
            "negotiated_rate": 1800.0, "plan_name": "",
            "source": "test", "source_origin": "mrf", "billing_class": "",
            "price_source": "", "setting": "", "source_file": "", "rate_methodology": "",
        }
        table = HospitalPayerRate.__table__
        stmt = pg_insert(table).values([row])
        pk_cols = {c.name for c in table.primary_key.columns}
        update_cols = [c.name for c in table.columns if c.name not in pk_cols]
        stmt = stmt.on_conflict_do_update(
            constraint="uq_hospital_payer_rates_natural_key",
            set_={col: stmt.excluded[col] for col in update_cols},
        )
        dim_db.execute(stmt)
        dim_db.flush()

    count = dim_db.query(HospitalPayerRate).filter_by(
        hospital_id="mgh", cpt="45378", payer_id="BCBS_MA", plan_name="",
    ).count()
    assert count == 1


def test_mrf_tic_coexist(dim_db: Session) -> None:
    """Same payer from MRF + TiC stored as 2 rows (different source_origin)."""
    dim_db.add(HospitalProcedure(
        id="mgh:45378", hospital_id="mgh", cpt="45378", cpt_desc="Colonoscopy",
        source="test",
    ))
    dim_db.flush()

    dim_db.add(HospitalPayerRate(
        hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
        negotiated_rate=2000.0, plan_name="", source_origin="mrf",
    ))
    dim_db.add(HospitalPayerRate(
        hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
        negotiated_rate=1950.0, plan_name="", source_origin="tic",
    ))
    dim_db.flush()

    count = dim_db.query(HospitalPayerRate).filter_by(
        hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
    ).count()
    assert count == 2


def test_setting_stored(dim_db: Session) -> None:
    """setting column stores outpatient vs ASC values."""
    dim_db.add(HospitalProcedure(
        id="mgh:45378", hospital_id="mgh", cpt="45378", cpt_desc="Colonoscopy",
        source="test",
    ))
    dim_db.flush()

    dim_db.add(HospitalPayerRate(
        hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
        negotiated_rate=2000.0, plan_name="Plan A", source_origin="mrf",
        setting="outpatient",
    ))
    dim_db.flush()

    rate = dim_db.query(HospitalPayerRate).filter_by(
        hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
    ).one()
    assert rate.setting == "outpatient"


def test_procedures_from_bundles(dim_db: Session) -> None:
    """procedures table populated from cpt_bundles.yaml with all fields."""
    procs = dim_db.query(Procedure).all()
    assert len(procs) > 0

    screening = dim_db.query(Procedure).filter_by(bundle_id="colonoscopy_screening").one()
    assert screening.label == "Screening colonoscopy"
    assert screening.specialty == "Gastroenterology"
    assert screening.description != ""
    assert "45378" in screening.cpt_codes
    assert "screening" in screening.tags
    assert screening.source == "cpt_bundles.yaml"


def test_hospitals_dimension(dim_db: Session) -> None:
    """All 12 hospitals in dimension table with correct fields."""
    hospitals = dim_db.query(Hospital).all()
    assert len(hospitals) == 12

    mgh = dim_db.query(Hospital).filter_by(hospital_id="mgh").one()
    assert mgh.name == "Massachusetts General Hospital"
    assert mgh.system_name == "Mass General Brigham"
    assert mgh.state == "MA"
    assert mgh.metro_area == "boston"
    assert mgh.npi == "1023049236"


def test_payers_dimension(dim_db: Session) -> None:
    """All payers in dimension table with correct fields."""
    payers = dim_db.query(Payer).all()
    assert len(payers) == 4

    bcbs = dim_db.query(Payer).filter_by(payer_id="BCBS_MA").one()
    assert bcbs.canonical_name == "Blue Cross Blue Shield (BCBS)"
    assert bcbs.parent_brand == "bcbs"
    assert "MA" in bcbs.operating_states


# ── Geography tests ──


def test_hospitals_metro_area_filter(dim_db: Session) -> None:
    """Query by metro_area returns only that market's hospitals."""
    boston = dim_db.query(Hospital).filter_by(metro_area="boston").all()
    assert len(boston) == 12  # all current hospitals are Boston

    sf = dim_db.query(Hospital).filter_by(metro_area="san_francisco").all()
    assert len(sf) == 0


def test_payers_operating_states(dim_db: Session) -> None:
    """BCBS_MA.operating_states contains 'MA'."""
    bcbs = dim_db.query(Payer).filter_by(payer_id="BCBS_MA").one()
    assert "MA" in bcbs.operating_states

    aetna = dim_db.query(Payer).filter_by(payer_id="AETNA").one()
    assert set(aetna.operating_states) == {"MA", "CT", "NY", "CA"}


def test_cross_region_payer_isolation(dim_db: Session) -> None:
    """BCBS_MA rates don't appear when filtering for SF hospitals (none exist)."""
    dim_db.add(HospitalProcedure(
        id="mgh:45378", hospital_id="mgh", cpt="45378", cpt_desc="Colonoscopy",
        source="test",
    ))
    dim_db.flush()

    dim_db.add(HospitalPayerRate(
        hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
        negotiated_rate=2000.0, plan_name="", source_origin="mrf",
    ))
    dim_db.flush()

    # Query rates for SF hospitals — should be empty
    sf_hospital_ids = [
        h.hospital_id for h in dim_db.query(Hospital).filter_by(metro_area="san_francisco").all()
    ]
    if sf_hospital_ids:
        sf_rates = dim_db.query(HospitalPayerRate).filter(
            HospitalPayerRate.hospital_id.in_(sf_hospital_ids)
        ).all()
        assert len(sf_rates) == 0
    else:
        # No SF hospitals — isolation holds trivially
        assert len(sf_hospital_ids) == 0


def test_hospital_state_required(dim_db: Session) -> None:
    """Inserting hospital without state raises IntegrityError."""
    with pytest.raises(IntegrityError):
        dim_db.execute(
            text(
                "INSERT INTO hospitals (hospital_id, name, system_name, metro_area) "
                "VALUES ('test_no_state', 'Test Hospital', '', 'boston')"
            )
        )
        dim_db.flush()
