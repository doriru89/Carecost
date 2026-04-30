"""TDD tests for csv_builder — written BEFORE implementation."""

import csv
from pathlib import Path

from app.etl.types import (
    BenchmarkRecord,
    MergeResult,
    PayerRateRecord,
    ProcedureRecord,
)


def _make_result():
    return MergeResult(
        procedures=[
            ProcedureRecord(
                hospital_id="mgh", cpt="45378", cpt_desc="Colonoscopy",
                gross_charge=3883.456, discounted_cash=2912.0,
                de_identified_min=2200.0, de_identified_max=5500.0,
            ),
        ],
        payer_rates=[
            PayerRateRecord(
                hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
                negotiated_rate=3411.789, source_origin="mrf",
            ),
        ],
        benchmarks=[
            BenchmarkRecord(
                hospital_id="mgh", cpt="45378",
                benchmark_source="fair_health", component="physician_in_network",
                price=604.0,
            ),
        ],
    )


class TestBuildCsvs:
    def test_procedure_csv_header(self, tmp_path):
        from app.etl.csv_builder import PROCEDURE_COLUMNS, build_csvs
        build_csvs(_make_result(), tmp_path)
        with open(tmp_path / "hospital_procedures.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == list(PROCEDURE_COLUMNS)

    def test_payer_rate_csv_header(self, tmp_path):
        from app.etl.csv_builder import PAYER_RATE_COLUMNS, build_csvs
        build_csvs(_make_result(), tmp_path)
        with open(tmp_path / "hospital_payer_rates.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == list(PAYER_RATE_COLUMNS)

    def test_benchmark_csv_header(self, tmp_path):
        from app.etl.csv_builder import BENCHMARK_COLUMNS, build_csvs
        build_csvs(_make_result(), tmp_path)
        with open(tmp_path / "hospital_benchmarks.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == list(BENCHMARK_COLUMNS)

    def test_float_rounding(self, tmp_path):
        from app.etl.csv_builder import build_csvs
        build_csvs(_make_result(), tmp_path)
        with open(tmp_path / "hospital_procedures.csv") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["gross_charge"] == "3883.46"

    def test_none_as_empty_string(self, tmp_path):
        from app.etl.csv_builder import build_csvs
        result = MergeResult(
            procedures=[ProcedureRecord(
                hospital_id="bidmc", cpt="43235", cpt_desc="EGD",
                gross_charge=2834.0, discounted_cash=None,
                de_identified_min=None, de_identified_max=None,
            )],
        )
        build_csvs(result, tmp_path)
        with open(tmp_path / "hospital_procedures.csv") as f:
            row = list(csv.DictReader(f))[0]
        assert row["discounted_cash"] == ""

    def test_sorted_output(self, tmp_path):
        from app.etl.csv_builder import build_csvs
        result = MergeResult(
            procedures=[
                ProcedureRecord(hospital_id="mgh", cpt="45378", cpt_desc="C",
                                gross_charge=None, discounted_cash=None,
                                de_identified_min=None, de_identified_max=None),
                ProcedureRecord(hospital_id="bidmc", cpt="43235", cpt_desc="E",
                                gross_charge=None, discounted_cash=None,
                                de_identified_min=None, de_identified_max=None),
            ],
        )
        build_csvs(result, tmp_path)
        with open(tmp_path / "hospital_procedures.csv") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["hospital_id"] == "bidmc"
        assert rows[1]["hospital_id"] == "mgh"

    def test_returns_row_counts(self, tmp_path):
        from app.etl.csv_builder import build_csvs
        counts = build_csvs(_make_result(), tmp_path)
        assert counts["hospital_procedures.csv"] == 1
        assert counts["hospital_payer_rates.csv"] == 1
        assert counts["hospital_benchmarks.csv"] == 1


class TestBuildLegacyWideCsv:
    def test_35_columns(self, tmp_path):
        from app.etl.csv_builder import build_legacy_wide_csv
        out = tmp_path / "hospital_rates.csv"
        build_legacy_wide_csv(_make_result(), out)
        with open(out) as f:
            header = next(csv.reader(f))
        assert len(header) == 35

    def test_header_matches_seed(self, tmp_path):
        from app.etl.csv_builder import LEGACY_WIDE_COLUMNS
        seed_path = Path(__file__).parent.parent.parent.parent / "data" / "seed" / "hospital_rates_clean.csv"
        with open(seed_path) as f:
            seed_header = next(csv.reader(f))
        assert list(LEGACY_WIDE_COLUMNS) == seed_header

    def test_payer_pivot(self, tmp_path):
        from app.etl.csv_builder import build_legacy_wide_csv
        result = MergeResult(
            procedures=[ProcedureRecord(
                hospital_id="mgh", cpt="45378", cpt_desc="Colonoscopy",
                gross_charge=3883.0, discounted_cash=2912.0,
                de_identified_min=2200.0, de_identified_max=5500.0,
            )],
            payer_rates=[
                PayerRateRecord(hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
                                negotiated_rate=3411.0, plan_name="HMO Blue",
                                source="negotiated_dollar", source_origin="mrf"),
                PayerRateRecord(hospital_id="mgh", cpt="45378", payer_id="AETNA",
                                negotiated_rate=2900.0, source_origin="mrf"),
            ],
            benchmarks=[],
        )
        out = tmp_path / "hospital_rates.csv"
        build_legacy_wide_csv(result, out)
        with open(out) as f:
            row = list(csv.DictReader(f))[0]
        assert row["bcbs_price"] == "3411.00"
        assert row["aetna_price"] == "2900.00"
        assert row["bcbs_plan"] == "HMO Blue"
