"""Tests for source provenance and rate quality enums + derivation."""


def test_source_type_enum_values():
    from app.models.provenance import SourceType

    assert SourceType.MRF.value == "mrf"
    assert SourceType.TIC.value == "tic"
    assert SourceType.BENCHMARK.value == "benchmark"
    assert SourceType.MANUAL.value == "manual"


def test_rate_quality_enum_values():
    from app.models.provenance import RateQuality

    assert RateQuality.NEGOTIATED.value == "negotiated"
    assert RateQuality.GROSS_ONLY.value == "gross_only"
    assert RateQuality.BENCHMARK_ONLY.value == "benchmark_only"
    assert RateQuality.UNKNOWN.value == "unknown"


def test_derive_rate_quality_negotiated():
    from app.etl.data_qualifier import derive_rate_quality_from_csv_row

    row = {"bcbs_price": "1234.56", "gross_charge": "5000"}
    assert derive_rate_quality_from_csv_row(row) == "negotiated"


def test_derive_rate_quality_gross_only():
    from app.etl.data_qualifier import derive_rate_quality_from_csv_row

    row = {"bcbs_price": "", "aetna_price": "", "gross_charge": "5000"}
    assert derive_rate_quality_from_csv_row(row) == "gross_only"


def test_derive_rate_quality_benchmark_only():
    from app.etl.data_qualifier import derive_rate_quality_from_csv_row

    row = {"gross_charge": "", "turquoise_bundled_price": "2500"}
    assert derive_rate_quality_from_csv_row(row) == "benchmark_only"


def test_derive_rate_quality_unknown():
    from app.etl.data_qualifier import derive_rate_quality_from_csv_row

    row = {}
    assert derive_rate_quality_from_csv_row(row) == "unknown"
