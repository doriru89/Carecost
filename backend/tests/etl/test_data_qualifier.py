"""TDD tests for data_qualifier — written BEFORE implementation."""

from app.etl.types import NormalizedRecord


def _make_normalized(hospital_id="mgh", cpt="45378", **kwargs) -> NormalizedRecord:
    defaults = dict(
        hospital_id=hospital_id, cpt=cpt, cpt_desc="Colonoscopy",
        description="HC COLONOSCOPY", payer_id="BCBS_MA", payer_raw="BLUE CROSS",
        plan="HMO Blue", setting="outpatient", gross=3883.0, cash=2912.0,
        negotiated_dollar=3411.0, estimated_amount=None, de_id_min=2200.0,
        de_id_max=5500.0, billing_class="institutional",
        source_file="mgh_charges.zip", source_origin="mrf", mrf_format="standard_csv",
    )
    defaults.update(kwargs)
    return NormalizedRecord(**defaults)


class TestQualifyRecord:
    def test_negotiated_rate(self):
        from app.etl.data_qualifier import qualify_record
        rec = _make_normalized(negotiated_dollar=3411.0)
        q = qualify_record(rec)
        assert q.rate_quality == "negotiated"
        assert q.price_source == "negotiated_dollar"
        assert q.source_type == "mrf"

    def test_zero_rate_guard_not_negotiated(self):
        from app.etl.data_qualifier import qualify_record
        rec = _make_normalized(negotiated_dollar=0.0)
        q = qualify_record(rec)
        assert q.rate_quality != "negotiated"

    def test_zero_rate_guard_no_fallback(self):
        from app.etl.data_qualifier import qualify_record
        rec = _make_normalized(
            negotiated_dollar=0.0, estimated_amount=None,
            gross=None, cash=None,
        )
        q = qualify_record(rec)
        assert q.rate_quality == "unknown"

    def test_estimated_amount_fallback(self):
        from app.etl.data_qualifier import qualify_record
        rec = _make_normalized(negotiated_dollar=None, estimated_amount=2400.0)
        q = qualify_record(rec)
        assert q.rate_quality == "negotiated"
        assert q.price_source == "estimated_amount"

    def test_gross_only(self):
        from app.etl.data_qualifier import qualify_record
        rec = _make_normalized(
            negotiated_dollar=None, estimated_amount=None, gross=3883.0,
        )
        q = qualify_record(rec)
        assert q.rate_quality == "gross_only"
        assert q.price_source == "gross"

    def test_unknown(self):
        from app.etl.data_qualifier import qualify_record
        rec = _make_normalized(
            negotiated_dollar=None, estimated_amount=None,
            gross=None, cash=None,
        )
        q = qualify_record(rec)
        assert q.rate_quality == "unknown"
        assert q.price_source == ""

    def test_source_type_mrf(self):
        from app.etl.data_qualifier import qualify_record
        rec = _make_normalized(source_origin="mrf")
        q = qualify_record(rec)
        assert q.source_type == "mrf"

    def test_source_type_tic(self):
        from app.etl.data_qualifier import qualify_record
        rec = _make_normalized(source_origin="tic")
        q = qualify_record(rec)
        assert q.source_type == "tic"

    def test_price_granularity_always_itemized(self):
        from app.etl.data_qualifier import qualify_record
        q = qualify_record(_make_normalized())
        assert q.price_granularity == "itemized"


class TestQualifyBatch:
    def test_preserves_order(self):
        from app.etl.data_qualifier import qualify_batch
        records = [
            _make_normalized(hospital_id="mgh", cpt="45378"),
            _make_normalized(hospital_id="bidmc", cpt="43235"),
            _make_normalized(hospital_id="bmc", cpt="45380"),
        ]
        result = qualify_batch(records)
        assert len(result) == 3
        assert result[0].hospital_id == "mgh"
        assert result[1].hospital_id == "bidmc"
        assert result[2].hospital_id == "bmc"


class TestDeriveDataCompleteness:
    def test_full(self):
        from app.etl.data_qualifier import qualify_batch, derive_data_completeness
        records = qualify_batch([
            _make_normalized(hospital_id="mgh", payer_id="BCBS_MA", negotiated_dollar=3411.0),
        ])
        assert derive_data_completeness(records, "mgh") == "full"

    def test_gross_only(self):
        from app.etl.data_qualifier import qualify_batch, derive_data_completeness
        records = qualify_batch([
            _make_normalized(
                hospital_id="bidmc", payer_id=None,
                negotiated_dollar=None, estimated_amount=None,
                gross=2834.0,
            ),
        ])
        assert derive_data_completeness(records, "bidmc") == "gross_only"

    def test_unknown(self):
        from app.etl.data_qualifier import qualify_batch, derive_data_completeness
        records = qualify_batch([
            _make_normalized(
                hospital_id="test", payer_id=None,
                negotiated_dollar=None, estimated_amount=None,
                gross=None, cash=None,
            ),
        ])
        assert derive_data_completeness(records, "test") == "unknown"


class TestComputeComplianceScore:
    def test_full(self):
        from app.etl.data_qualifier import compute_compliance_score
        assert compute_compliance_score(
            has_gross=True, has_cash=True, has_de_id=True, payer_count=2,
        ) == "full"

    def test_partial(self):
        from app.etl.data_qualifier import compute_compliance_score
        assert compute_compliance_score(
            has_gross=True, has_cash=False, has_de_id=False, payer_count=1,
        ) == "partial"

    def test_minimal(self):
        from app.etl.data_qualifier import compute_compliance_score
        assert compute_compliance_score(
            has_gross=True, has_cash=False, has_de_id=False, payer_count=0,
        ) == "minimal"

    def test_non_compliant(self):
        from app.etl.data_qualifier import compute_compliance_score
        assert compute_compliance_score(
            has_gross=False, has_cash=False, has_de_id=False, payer_count=0,
        ) == "non_compliant"


class TestDeriveRateQualityFromCsvRow:
    def test_negotiated_from_csv(self):
        from app.etl.data_qualifier import derive_rate_quality_from_csv_row
        row = {"bcbs_price": "3411.0", "gross_charge": "3883.0"}
        assert derive_rate_quality_from_csv_row(row) == "negotiated"

    def test_gross_only_from_csv(self):
        from app.etl.data_qualifier import derive_rate_quality_from_csv_row
        row = {"gross_charge": "2834.0", "bcbs_price": ""}
        assert derive_rate_quality_from_csv_row(row) == "gross_only"

    def test_unknown_from_csv(self):
        from app.etl.data_qualifier import derive_rate_quality_from_csv_row
        row = {"gross_charge": "", "bcbs_price": ""}
        assert derive_rate_quality_from_csv_row(row) == "unknown"
