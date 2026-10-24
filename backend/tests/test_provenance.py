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
