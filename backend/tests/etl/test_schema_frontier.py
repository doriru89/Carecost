"""Frontier tests — verify ETL output schema matches seed data and DB models."""

import csv
import dataclasses
from pathlib import Path


def test_legacy_wide_csv_header_matches_seed():
    from app.etl.csv_builder import LEGACY_WIDE_COLUMNS

    seed_path = Path(__file__).parent.parent.parent.parent / "data" / "seed" / "hospital_rates_clean.csv"
    with open(seed_path) as f:
        seed_header = next(csv.reader(f))
    assert list(LEGACY_WIDE_COLUMNS) == seed_header


def test_procedure_record_covers_procedure_table():
    from app.db.tables import HospitalProcedure
    from app.etl.types import ProcedureRecord

    orm_cols = {c.name for c in HospitalProcedure.__table__.columns} - {"id", "source"}
    dc_fields = {f.name for f in dataclasses.fields(ProcedureRecord)}
    missing = orm_cols - dc_fields
    assert not missing, f"ORM columns missing from ProcedureRecord: {missing}"


def test_payer_rate_record_covers_payer_rate_table():
    from app.db.tables import HospitalPayerRate
    from app.etl.types import PayerRateRecord

    orm_cols = {c.name for c in HospitalPayerRate.__table__.columns} - {"id"}
    dc_fields = {f.name for f in dataclasses.fields(PayerRateRecord)}
    missing = orm_cols - dc_fields
    assert not missing, f"ORM columns missing from PayerRateRecord: {missing}"
