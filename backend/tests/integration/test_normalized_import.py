"""Integration tests for normalized CSV → DB import (Phase 10.6).

Tests the 3 import functions and directory orchestrator that read
ETL-generated normalized CSVs into the 3 normalized tables.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.tables import HospitalBenchmark, HospitalPayerRate, HospitalProcedure

_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "registries"


def _seed_dimensions(db: Session) -> None:
    """Populate hospitals and payers dimension tables from YAML registries."""
    import yaml

    from app.db.tables import Hospital, Payer, Procedure

    hospitals_data = yaml.safe_load((_DATA_DIR / "hospitals.yaml").read_text())["hospitals"]
    for hid, h in hospitals_data.items():
        db.add(Hospital(
            hospital_id=hid, name=h["name"], system_name=h.get("system", ""),
            state=h["state"], metro_area=h["metro_area"],
            neighborhood=h.get("neighborhood", ""),
            lat=h.get("lat"), lng=h.get("lng"), npi=h.get("npi", ""),
        ))

    payers_data = yaml.safe_load((_DATA_DIR / "payers.yaml").read_text())["payers"]
    for pid, p in payers_data.items():
        db.add(Payer(
            payer_id=pid, canonical_name=p["label"],
            parent_brand=p.get("parent_brand", ""),
            payer_type="commercial",
            operating_states=p.get("operating_states", []),
            tic_portal=p.get("tic_portal", ""),
        ))

    bundles = yaml.safe_load((_DATA_DIR / "cpt_bundles.yaml").read_text())["bundles"]
    for bid, b in bundles.items():
        db.merge(Procedure(
            bundle_id=bid, label=b["label"],
            specialty=b.get("specialty", ""),
            description=b.get("description", ""),
            cpt_codes=[b["cpt"]], tags=b.get("tags", []),
            source="cpt_bundles.yaml",
        ))
    db.flush()


@pytest.fixture
def dim_db(db_session: Session) -> Session:
    _seed_dimensions(db_session)
    db_session.commit()
    return db_session


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(rows)


# ── Procedure import tests ──


def test_import_procedures_csv(dim_db: Session, tmp_path: Path) -> None:
    from app.services.csv_import import import_hospital_procedures_csv

    csv_path = tmp_path / "hospital_procedures.csv"
    from app.etl.csv_builder import PROCEDURE_COLUMNS

    rows = [
        {c: "" for c in PROCEDURE_COLUMNS}
        | {"hospital_id": "mgh", "cpt": "45378", "cpt_desc": "Colonoscopy",
           "gross_charge": "5000.50", "discounted_cash": "2500.25",
           "data_completeness": "full", "source_type": "mrf", "rate_quality": "negotiated"},
        {c: "" for c in PROCEDURE_COLUMNS}
        | {"hospital_id": "bmc", "cpt": "45378", "cpt_desc": "Colonoscopy",
           "gross_charge": "4200.00", "data_completeness": "partial",
           "source_type": "mrf", "rate_quality": "unknown"},
    ]
    _write_csv(csv_path, PROCEDURE_COLUMNS, rows)

    count = import_hospital_procedures_csv(dim_db, csv_path)
    dim_db.commit()

    assert count == 2
    stored = dim_db.query(HospitalProcedure).all()
    assert len(stored) == 2
    mgh = dim_db.query(HospitalProcedure).filter_by(hospital_id="mgh", cpt="45378").one()
    assert mgh.id == "mgh:45378"
    assert mgh.gross_charge == pytest.approx(5000.50)
    assert mgh.discounted_cash == pytest.approx(2500.25)


def test_import_procedures_idempotent(dim_db: Session, tmp_path: Path) -> None:
    from app.services.csv_import import import_hospital_procedures_csv

    csv_path = tmp_path / "hospital_procedures.csv"
    from app.etl.csv_builder import PROCEDURE_COLUMNS

    rows = [{c: "" for c in PROCEDURE_COLUMNS}
            | {"hospital_id": "mgh", "cpt": "45378", "cpt_desc": "Colonoscopy",
               "gross_charge": "5000.50", "source_type": "mrf"}]
    _write_csv(csv_path, PROCEDURE_COLUMNS, rows)

    import_hospital_procedures_csv(dim_db, csv_path)
    dim_db.commit()
    count = import_hospital_procedures_csv(dim_db, csv_path)
    dim_db.commit()

    assert count == 1
    assert dim_db.query(HospitalProcedure).count() == 1


# ── Payer rate import tests ──


def test_import_payer_rates_csv(dim_db: Session, tmp_path: Path) -> None:
    from app.services.csv_import import import_hospital_payer_rates_csv

    csv_path = tmp_path / "hospital_payer_rates.csv"
    from app.etl.csv_builder import PAYER_RATE_COLUMNS

    rows = [
        {c: "" for c in PAYER_RATE_COLUMNS}
        | {"hospital_id": "mgh", "cpt": "45378", "payer_id": "BCBS_MA",
           "negotiated_rate": "2000.50", "plan_name": "Blue Care Elect",
           "source_origin": "mrf", "setting": "outpatient",
           "source_file": "mgh_standard.zip"},
        {c: "" for c in PAYER_RATE_COLUMNS}
        | {"hospital_id": "mgh", "cpt": "45378", "payer_id": "BCBS_MA",
           "negotiated_rate": "1800.00", "plan_name": "Blue Care PPO",
           "source_origin": "mrf", "setting": "both"},
    ]
    _write_csv(csv_path, PAYER_RATE_COLUMNS, rows)

    count = import_hospital_payer_rates_csv(dim_db, csv_path)
    dim_db.commit()

    assert count == 2
    stored = dim_db.query(HospitalPayerRate).filter_by(
        hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
    ).all()
    assert len(stored) == 2
    plans = {r.plan_name for r in stored}
    assert plans == {"Blue Care Elect", "Blue Care PPO"}


def test_import_payer_rates_empty_plan_name(dim_db: Session, tmp_path: Path) -> None:
    """Empty string plan_name is valid — not filtered out."""
    from app.services.csv_import import import_hospital_payer_rates_csv

    csv_path = tmp_path / "hospital_payer_rates.csv"
    from app.etl.csv_builder import PAYER_RATE_COLUMNS

    rows = [{c: "" for c in PAYER_RATE_COLUMNS}
            | {"hospital_id": "mgh", "cpt": "45378", "payer_id": "UHC",
               "negotiated_rate": "1500.00", "plan_name": "",
               "source_origin": "mrf"}]
    _write_csv(csv_path, PAYER_RATE_COLUMNS, rows)

    count = import_hospital_payer_rates_csv(dim_db, csv_path)
    dim_db.commit()

    assert count == 1
    stored = dim_db.query(HospitalPayerRate).filter_by(hospital_id="mgh", payer_id="UHC").one()
    assert stored.plan_name == ""


def test_import_payer_rates_idempotent(dim_db: Session, tmp_path: Path) -> None:
    from app.services.csv_import import import_hospital_payer_rates_csv

    csv_path = tmp_path / "hospital_payer_rates.csv"
    from app.etl.csv_builder import PAYER_RATE_COLUMNS

    rows = [{c: "" for c in PAYER_RATE_COLUMNS}
            | {"hospital_id": "mgh", "cpt": "45378", "payer_id": "BCBS_MA",
               "negotiated_rate": "2000.00", "plan_name": "Test Plan",
               "source_origin": "mrf"}]
    _write_csv(csv_path, PAYER_RATE_COLUMNS, rows)

    import_hospital_payer_rates_csv(dim_db, csv_path)
    dim_db.commit()
    count = import_hospital_payer_rates_csv(dim_db, csv_path)
    dim_db.commit()

    assert count == 1
    assert dim_db.query(HospitalPayerRate).count() == 1


def test_import_payer_rates_rate_methodology_spaces(dim_db: Session, tmp_path: Path) -> None:
    """CMS rate_methodology uses spaces: 'fee schedule' not 'fee_schedule'."""
    from app.services.csv_import import import_hospital_payer_rates_csv

    csv_path = tmp_path / "hospital_payer_rates.csv"
    from app.etl.csv_builder import PAYER_RATE_COLUMNS

    rows = [{c: "" for c in PAYER_RATE_COLUMNS}
            | {"hospital_id": "mgh", "cpt": "45378", "payer_id": "AETNA",
               "negotiated_rate": "1800.00", "plan_name": "Aetna HMO",
               "source_origin": "mrf", "rate_methodology": "fee schedule"}]
    _write_csv(csv_path, PAYER_RATE_COLUMNS, rows)

    count = import_hospital_payer_rates_csv(dim_db, csv_path)
    dim_db.commit()

    assert count == 1
    stored = dim_db.query(HospitalPayerRate).filter_by(payer_id="AETNA").one()
    assert stored.rate_methodology == "fee schedule"


# ── Benchmark import tests ──


def test_import_benchmarks_csv(dim_db: Session, tmp_path: Path) -> None:
    from app.services.csv_import import import_hospital_benchmarks_csv

    csv_path = tmp_path / "hospital_benchmarks.csv"
    from app.etl.csv_builder import BENCHMARK_COLUMNS

    rows = [
        {c: "" for c in BENCHMARK_COLUMNS}
        | {"hospital_id": "mgh", "cpt": "45378", "benchmark_source": "turquoise",
           "component": "total", "price": "3500.00", "quality_rating": "4.2"},
    ]
    _write_csv(csv_path, BENCHMARK_COLUMNS, rows)

    count = import_hospital_benchmarks_csv(dim_db, csv_path)
    dim_db.commit()

    assert count == 1
    stored = dim_db.query(HospitalBenchmark).one()
    assert stored.price == pytest.approx(3500.00)
    assert stored.quality_rating == pytest.approx(4.2)


# ── Directory orchestrator tests ──


def test_import_normalized_directory(dim_db: Session, tmp_path: Path) -> None:
    from app.services.csv_import import import_normalized_directory

    from app.etl.csv_builder import BENCHMARK_COLUMNS, PAYER_RATE_COLUMNS, PROCEDURE_COLUMNS

    _write_csv(tmp_path / "hospital_procedures.csv", PROCEDURE_COLUMNS, [
        {c: "" for c in PROCEDURE_COLUMNS}
        | {"hospital_id": "mgh", "cpt": "45378", "cpt_desc": "Colonoscopy",
           "gross_charge": "5000.00", "source_type": "mrf"},
    ])
    _write_csv(tmp_path / "hospital_payer_rates.csv", PAYER_RATE_COLUMNS, [
        {c: "" for c in PAYER_RATE_COLUMNS}
        | {"hospital_id": "mgh", "cpt": "45378", "payer_id": "BCBS_MA",
           "negotiated_rate": "2000.00", "plan_name": "Test",
           "source_origin": "mrf"},
    ])
    _write_csv(tmp_path / "hospital_benchmarks.csv", BENCHMARK_COLUMNS, [
        {c: "" for c in BENCHMARK_COLUMNS}
        | {"hospital_id": "mgh", "cpt": "45378", "benchmark_source": "turquoise",
           "component": "total", "price": "3500.00"},
    ])

    counts = import_normalized_directory(dim_db, tmp_path)
    dim_db.commit()

    assert counts["hospital_procedures"] == 1
    assert counts["hospital_payer_rates"] == 1
    assert counts["hospital_benchmarks"] == 1


def test_import_normalized_directory_partial(dim_db: Session, tmp_path: Path) -> None:
    """Directory with only procedures CSV — skips missing files."""
    from app.services.csv_import import import_normalized_directory

    from app.etl.csv_builder import PROCEDURE_COLUMNS

    _write_csv(tmp_path / "hospital_procedures.csv", PROCEDURE_COLUMNS, [
        {c: "" for c in PROCEDURE_COLUMNS}
        | {"hospital_id": "mgh", "cpt": "45378", "cpt_desc": "Colonoscopy",
           "source_type": "mrf"},
    ])

    counts = import_normalized_directory(dim_db, tmp_path)
    dim_db.commit()

    assert counts == {"hospital_procedures": 1}
    assert dim_db.query(HospitalPayerRate).count() == 0
