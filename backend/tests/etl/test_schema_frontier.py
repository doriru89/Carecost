"""Frontier tests — verify ETL output schema matches seed data and DB models."""

import dataclasses


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
