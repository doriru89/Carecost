"""TDD tests for merger — written BEFORE implementation."""

import json

from app.etl.types import (
    MergeResult,
    QualifiedRecord,
)
from app.registries import default_payer_id

_DEFAULT_PAYER = default_payer_id()


def _make_qualified(hospital_id="mgh", cpt="45378", payer_id=None, **kwargs):
    if payer_id is None:
        payer_id = _DEFAULT_PAYER
    defaults = dict(
        hospital_id=hospital_id, cpt=cpt, cpt_desc="Colonoscopy",
        description="HC COLONOSCOPY", payer_id=payer_id,
        payer_raw="BLUE CROSS", plan="HMO Blue", setting="outpatient",
        gross=3883.0, cash=2912.0, negotiated_dollar=3411.0,
        estimated_amount=None, de_id_min=2200.0, de_id_max=5500.0,
        billing_class="institutional", source_file="mgh_charges.zip",
        source_origin="mrf", mrf_format="standard_csv",
        source_type="mrf", rate_quality="negotiated",
        price_source="negotiated_dollar", rate_methodology="",
        price_granularity="itemized",
    )
    defaults.update(kwargs)
    return QualifiedRecord(**defaults)


class TestLoadBenchmarks:
    def test_fair_health(self, tmp_path):
        from app.etl.merger import load_benchmarks

        ppt_data = [
            {
                "hospital_id": "mgh", "cpt": "45378", "specialty": "Gastroenterology",
                "fh_physician_in_network": 604.0,
                "fh_anesthesia_in_network": None,
                "fh_facility_hosp_in_network": 1359.0,
                "fh_pathology_in_network": None,
            },
        ]
        seed_dir = tmp_path / "seed"
        seed_dir.mkdir()
        (seed_dir / "plan_payment_table.json").write_text(json.dumps(ppt_data))
        benchmarks = load_benchmarks(seed_dir, "Gastroenterology")
        fh = benchmarks.fair_health.get(("mgh", "45378"))
        assert fh is not None
        assert fh["fh_physician_in_network"] == 604.0
        assert fh["fh_facility_hosp_in_network"] == 1359.0

    def test_missing_files_graceful(self, tmp_path):
        from app.etl.merger import load_benchmarks

        seed_dir = tmp_path / "seed"
        seed_dir.mkdir()
        (seed_dir / "plan_payment_table.json").write_text("[]")
        benchmarks = load_benchmarks(seed_dir, "Gastroenterology")
        assert benchmarks.turquoise == {}
        assert benchmarks.masscomparecare == {}


class TestBenchmarkWarnings:
    def test_missing_benchmark_files_warn(self, tmp_path, caplog):
        import logging
        from app.etl.merger import load_benchmarks

        seed_dir = tmp_path / "empty"
        seed_dir.mkdir()
        with caplog.at_level(logging.WARNING, logger="app.etl.merger"):
            bd = load_benchmarks(seed_dir, "Gastroenterology")
        assert bd.fair_health == {}
        assert bd.turquoise == {}
        assert bd.masscomparecare == {}
        assert "Fair Health benchmark file not found" in caplog.text
        assert "Turquoise benchmark file not found" in caplog.text
        assert "MassCompareCare benchmark file not found" in caplog.text


class TestMergeRecords:
    def test_single_mrf_record(self):
        from app.etl.merger import merge_records

        records = [_make_qualified()]
        result = merge_records(records)
        assert isinstance(result, MergeResult)
        assert len(result.procedures) == 1
        assert len(result.payer_rates) == 1
        assert result.procedures[0].hospital_id == "mgh"
        assert result.procedures[0].cpt == "45378"
        assert result.payer_rates[0].payer_id == "BCBS_MA"
        assert result.payer_rates[0].negotiated_rate == 3411.0

    def test_multi_payer(self):
        from app.etl.merger import merge_records

        records = [
            _make_qualified(payer_id="BCBS_MA", negotiated_dollar=3411.0),
            _make_qualified(payer_id="AETNA", payer_raw="AETNA", negotiated_dollar=2900.0),
            _make_qualified(payer_id="HARVARD_PILGRIM", payer_raw="HP", negotiated_dollar=3100.0),
            _make_qualified(payer_id="UHC", payer_raw="UHC", negotiated_dollar=3200.0),
        ]
        result = merge_records(records)
        assert len(result.procedures) == 1
        assert len(result.payer_rates) == 4
        payer_ids = {r.payer_id for r in result.payer_rates}
        assert payer_ids == {"BCBS_MA", "AETNA", "HARVARD_PILGRIM", "UHC"}

    def test_mrf_and_tic_same_payer(self):
        from app.etl.merger import merge_records

        records = [
            _make_qualified(payer_id="BCBS_MA", source_origin="mrf", negotiated_dollar=3411.0),
            _make_qualified(
                payer_id="BCBS_MA", source_origin="tic", negotiated_dollar=487.5,
                source_type="tic",
            ),
        ]
        result = merge_records(records)
        assert len(result.procedures) == 1
        assert len(result.payer_rates) == 2
        origins = {r.source_origin for r in result.payer_rates}
        assert origins == {"mrf", "tic"}

    def test_hospital_metadata_from_registry(self):
        from app.etl.merger import merge_records

        records = [_make_qualified(hospital_id="mgh")]
        result = merge_records(records)
        proc = result.procedures[0]
        assert proc.hospital_id == "mgh"

    def test_gross_from_mrf(self):
        from app.etl.merger import merge_records

        records = [_make_qualified(gross=3883.0, cash=2912.0, de_id_min=2200.0, de_id_max=5500.0)]
        result = merge_records(records)
        proc = result.procedures[0]
        assert proc.gross_charge == 3883.0
        assert proc.discounted_cash == 2912.0
        assert proc.de_identified_min == 2200.0
        assert proc.de_identified_max == 5500.0

    def test_estimated_amount_fallback(self):
        from app.etl.merger import merge_records

        records = [_make_qualified(
            negotiated_dollar=None, estimated_amount=2400.0,
            rate_quality="negotiated", price_source="estimated_amount",
        )]
        result = merge_records(records)
        assert len(result.payer_rates) == 1
        pr = result.payer_rates[0]
        assert pr.negotiated_rate == 2400.0
        assert pr.price_source == "estimated_amount"

    def test_zero_rate_excluded(self):
        from app.etl.merger import merge_records

        records = [_make_qualified(
            negotiated_dollar=0.0, estimated_amount=None,
            rate_quality="unknown", price_source="",
        )]
        result = merge_records(records)
        assert len(result.payer_rates) == 0

    def test_benchmark_fh_components(self, tmp_path):
        from app.etl.merger import load_benchmarks, merge_records

        ppt_data = [
            {
                "hospital_id": "mgh", "cpt": "45378", "specialty": "Gastroenterology",
                "fh_physician_in_network": 604.0,
                "fh_anesthesia_in_network": 200.0,
                "fh_facility_hosp_in_network": 1359.0,
                "fh_pathology_in_network": 150.0,
            },
        ]
        seed_dir = tmp_path / "seed"
        seed_dir.mkdir()
        (seed_dir / "plan_payment_table.json").write_text(json.dumps(ppt_data))
        benchmarks = load_benchmarks(seed_dir, "Gastroenterology")
        records = [_make_qualified()]
        result = merge_records(records, benchmarks)
        fh_benchmarks = [b for b in result.benchmarks if b.benchmark_source == "fair_health"]
        assert len(fh_benchmarks) == 4
        components = {b.component for b in fh_benchmarks}
        assert "physician_in_network" in components
        assert "facility_hosp_in_network" in components

    def test_benchmark_turquoise(self, tmp_path):
        from app.etl.merger import load_benchmarks, merge_records

        seed_dir = tmp_path / "seed"
        seed_dir.mkdir()
        turq_data = [
            {"hospital_name": "MGH", "hospital_id": "mgh", "cpt": "45378",
             "bundled_price": 5200.0, "quality_rating": 4.2},
        ]
        (seed_dir / "turquoise_data.json").write_text(json.dumps(turq_data))
        benchmarks = load_benchmarks(seed_dir, "Gastroenterology")
        records = [_make_qualified()]
        result = merge_records(records, benchmarks)
        turq = [b for b in result.benchmarks if b.benchmark_source == "turquoise"]
        assert len(turq) == 1
        assert turq[0].price == 5200.0
        assert turq[0].quality_rating == 4.2
        assert turq[0].component == "total"

    def test_missing_fh_fields(self, tmp_path):
        from app.etl.merger import load_benchmarks, merge_records

        ppt_data = [
            {
                "hospital_id": "mgh", "cpt": "45378", "specialty": "Gastroenterology",
                "fh_physician_in_network": 604.0,
                "fh_anesthesia_in_network": None,
                "fh_facility_hosp_in_network": None,
                "fh_pathology_in_network": None,
            },
        ]
        seed_dir = tmp_path / "seed"
        seed_dir.mkdir()
        (seed_dir / "plan_payment_table.json").write_text(json.dumps(ppt_data))
        benchmarks = load_benchmarks(seed_dir, "Gastroenterology")
        records = [_make_qualified()]
        result = merge_records(records, benchmarks)
        fh = [b for b in result.benchmarks if b.benchmark_source == "fair_health"]
        assert len(fh) == 1
        assert fh[0].component == "physician_in_network"

    def test_completeness_full(self):
        from app.etl.merger import merge_records

        records = [_make_qualified(
            payer_id="BCBS_MA", negotiated_dollar=3411.0,
            rate_quality="negotiated",
        )]
        result = merge_records(records)
        assert result.procedures[0].data_completeness == "full"

    def test_completeness_gross_only(self):
        from app.etl.merger import merge_records

        records = [_make_qualified(
            payer_id=None, negotiated_dollar=None,
            estimated_amount=None, gross=2834.0,
            rate_quality="gross_only", price_source="gross",
        )]
        result = merge_records(records)
        assert result.procedures[0].data_completeness == "gross_only"

    def test_compliance_score_computed(self):
        from app.etl.merger import merge_records

        records = [
            _make_qualified(payer_id="BCBS_MA", negotiated_dollar=3411.0,
                            gross=3883.0, cash=2912.0, de_id_min=2200.0, de_id_max=5500.0),
            _make_qualified(payer_id="AETNA", negotiated_dollar=2900.0,
                            gross=3883.0, cash=2912.0, de_id_min=2200.0, de_id_max=5500.0),
        ]
        result = merge_records(records)
        assert result.procedures[0].compliance_score == "full"

    def test_multiple_groups(self):
        from app.etl.merger import merge_records

        records = [
            _make_qualified(hospital_id="mgh", cpt="45378"),
            _make_qualified(hospital_id="mgh", cpt="43235", cpt_desc="EGD diagnostic"),
            _make_qualified(hospital_id="bidmc", cpt="45378"),
        ]
        result = merge_records(records)
        assert len(result.procedures) == 3
        keys = {(p.hospital_id, p.cpt) for p in result.procedures}
        assert keys == {("mgh", "45378"), ("mgh", "43235"), ("bidmc", "45378")}

    def test_non_canonical_payer_excluded(self):
        from app.etl.merger import merge_records

        records = [_make_qualified(
            payer_id=None, payer_raw="Medicare",
            negotiated_dollar=None, gross=3883.0,
            rate_quality="gross_only",
        )]
        result = merge_records(records)
        assert len(result.payer_rates) == 0

    def test_hospital_id_not_in_registry(self):
        from app.etl.merger import merge_records

        records = [_make_qualified(hospital_id="nonexistent_hospital")]
        result = merge_records(records)
        assert len(result.procedures) == 0
