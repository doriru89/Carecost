"""TDD tests for csv_builder — written BEFORE implementation."""

import csv

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


