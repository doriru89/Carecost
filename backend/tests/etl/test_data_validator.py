"""TDD tests for data_validator — written BEFORE implementation."""

from app.etl.types import (
    MergeResult,
    PayerRateRecord,
    ProcedureRecord,
)


def _make_proc(hospital_id="mgh", cpt="45378", **kwargs):
    defaults = dict(
        hospital_id=hospital_id,
        cpt=cpt,
        cpt_desc="Colonoscopy",
        gross_charge=3883.0,
        discounted_cash=2912.0,
        de_identified_min=2200.0,
        de_identified_max=5500.0,
    )
    defaults.update(kwargs)
    return ProcedureRecord(**defaults)


def _make_payer_rate(hospital_id="mgh", cpt="45378", payer_id="BCBS_MA", **kwargs):
    defaults = dict(
        hospital_id=hospital_id,
        cpt=cpt,
        payer_id=payer_id,
        negotiated_rate=3411.0,
        source_origin="mrf",
    )
    defaults.update(kwargs)
    return PayerRateRecord(**defaults)


def _valid_result():
    return MergeResult(
        procedures=[_make_proc()],
        payer_rates=[_make_payer_rate()],
        benchmarks=[],
    )


class TestValidateEtlOutput:
    def test_empty_records_fails(self):
        from app.etl.data_validator import validate_etl_output

        report = validate_etl_output(MergeResult())
        assert not report.passed
        assert any("empty" in e.lower() or "no procedure" in e.lower() for e in report.errors)

    def test_valid_records_pass(self):
        from app.etl.data_validator import validate_etl_output

        report = validate_etl_output(_valid_result())
        assert report.passed

    def test_missing_hospital_is_error(self):
        from app.etl.data_validator import validate_etl_output

        report = validate_etl_output(
            _valid_result(),
            expected_hospitals=["mgh", "bidmc"],
        )
        assert not report.passed
        assert any("bidmc" in e for e in report.errors)

    def test_invalid_cpt_fails(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc(cpt="ABC")],
            payer_rates=[],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert not report.passed
        assert any("cpt" in e.lower() for e in report.errors)

    def test_negative_price_fails(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc()],
            payer_rates=[_make_payer_rate(negotiated_rate=-100.0)],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert not report.passed

    def test_zero_payer_rate_fails(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc()],
            payer_rates=[_make_payer_rate(negotiated_rate=0.0)],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert not report.passed

    def test_price_out_of_range_warns(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc()],
            payer_rates=[_make_payer_rate(negotiated_rate=600_000.0)],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert any("out of range" in w for w in report.warnings)

    def test_gross_less_than_negotiated_warning(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc(gross_charge=1000.0)],
            payer_rates=[_make_payer_rate(negotiated_rate=5000.0)],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert report.passed
        assert len(report.warnings) > 0

    def test_cross_validation_15pct_warning(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc()],
            payer_rates=[
                _make_payer_rate(payer_id="BCBS_MA", source_origin="mrf", negotiated_rate=1000.0),
                _make_payer_rate(payer_id="BCBS_MA", source_origin="tic", negotiated_rate=1500.0),
            ],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert report.passed
        assert any("cross" in w.lower() or "diverge" in w.lower() for w in report.warnings)

    def test_cross_validation_within_threshold_no_warning(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc()],
            payer_rates=[
                _make_payer_rate(payer_id="BCBS_MA", source_origin="mrf", negotiated_rate=1000.0),
                _make_payer_rate(payer_id="BCBS_MA", source_origin="tic", negotiated_rate=1100.0),
            ],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        cross_warnings = [
            w for w in report.warnings if "cross" in w.lower() or "diverge" in w.lower()
        ]
        assert len(cross_warnings) == 0

    def test_duplicate_procedure_fails(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc(), _make_proc()],
            payer_rates=[],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert not report.passed
        assert any("duplicate" in e.lower() for e in report.errors)

    def test_duplicate_payer_rate_is_error(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc()],
            payer_rates=[
                _make_payer_rate(plan_name="PPO"),
                _make_payer_rate(plan_name="PPO"),
            ],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert not report.passed
        assert any("duplicate payer rate" in e.lower() for e in report.errors)

    def test_different_plan_payer_rates_not_duplicate(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc()],
            payer_rates=[
                _make_payer_rate(plan_name="HMO"),
                _make_payer_rate(plan_name="PPO"),
            ],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert report.passed

    def test_missing_required_fields_fails(self):
        from app.etl.data_validator import validate_etl_output

        result = MergeResult(
            procedures=[_make_proc(hospital_id="", cpt="45378")],
            payer_rates=[],
            benchmarks=[],
        )
        report = validate_etl_output(result)
        assert not report.passed
