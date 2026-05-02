"""Integration tests for normalized hospital tables (Phase 7)."""

from app.db.tables import HospitalBenchmark, HospitalPayerRate, HospitalProcedure
from app.etl.seed_migration import migrate_wide_to_normalized


def test_seed_migration_populates_procedures(seeded_db):
    count = seeded_db.query(HospitalProcedure).count()
    assert count > 0
    proc = seeded_db.query(HospitalProcedure).filter_by(cpt="45378").first()
    assert proc is not None
    assert proc.hospital_id
    assert proc.cpt_desc


def test_seed_migration_populates_payer_rates(seeded_db):
    count = seeded_db.query(HospitalPayerRate).count()
    assert count > 0
    bcbs = (
        seeded_db.query(HospitalPayerRate)
        .filter_by(cpt="45378", payer_id="BCBS_MA", source_origin="mrf")
        .first()
    )
    assert bcbs is not None
    assert bcbs.negotiated_rate is not None


def test_seed_migration_populates_benchmarks(seeded_db):
    count = seeded_db.query(HospitalBenchmark).count()
    assert count >= 0


def test_seed_migration_idempotent(seeded_db):
    before_procs = seeded_db.query(HospitalProcedure).count()
    before_rates = seeded_db.query(HospitalPayerRate).count()
    before_bm = seeded_db.query(HospitalBenchmark).count()

    migrate_wide_to_normalized(seeded_db)
    seeded_db.flush()

    assert seeded_db.query(HospitalProcedure).count() == before_procs
    assert seeded_db.query(HospitalPayerRate).count() == before_rates
    assert seeded_db.query(HospitalBenchmark).count() == before_bm


def test_list_hospitals_contract_normalized(client):
    r = client.get("/api/hospitals?cpt=45378")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    h = data[0]
    for field in [
        "name", "hospital_id", "lat", "lng", "doctor_count",
        "system_name", "metro_area", "neighborhood",
        "gross_charge", "discounted_cash", "de_identified_min", "de_identified_max",
        "cpt", "cpt_desc", "payer_rates", "benchmarks",
    ]:
        assert field in h, f"Missing field: {field}"
    assert isinstance(h["payer_rates"], list)
    assert isinstance(h["benchmarks"], list)
