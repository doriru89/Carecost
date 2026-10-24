"""Frontier test: the legacy seed CSV columns still match the DB model."""


def test_payer_rate_csv_columns_subset_of_orm():
    from app.db.tables import HospitalPayerRate
    from app.etl.csv_builder import PAYER_RATE_COLUMNS

    orm_cols = {c.name for c in HospitalPayerRate.__table__.columns} - {"id"}
    csv_cols = set(PAYER_RATE_COLUMNS)
    missing = csv_cols - orm_cols
    assert not missing, f"CSV columns not in ORM: {missing}"
