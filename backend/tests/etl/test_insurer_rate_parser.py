"""TDD tests for insurer_rate_parser — written BEFORE implementation.

Tests the two-pass TiC stream parser that matches insurer rates
to Boston hospitals via NPI lookup against the registry.
"""

from __future__ import annotations

import gzip
import json
import zipfile
from pathlib import Path

GI_CPTS = {
    "43235",
    "43239",
    "43244",
    "43249",
    "43255",
    "43259",
    "45378",
    "45380",
    "45384",
    "45385",
    "45388",
    "74176",
    "74177",
    "74178",
    "76700",
    "76705",
    "91110",
}


def _make_tic_json(
    in_network: list[dict] | None = None,
    provider_references: list[dict] | None = None,
) -> dict:
    """Build a minimal TiC JSON structure."""
    return {
        "reporting_entity_name": "Test Insurer",
        "reporting_entity_type": "health insurance issuer",
        "in_network": in_network or [],
        "provider_references": provider_references or [],
    }


def _make_in_network_item(
    billing_code: str = "45378",
    name: str = "Colonoscopy",
    description: str = "HC COLONOSCOPY DIAGNOSTIC",
    negotiated_rates: list[dict] | None = None,
) -> dict:
    return {
        "billing_code": billing_code,
        "billing_code_type": "CPT",
        "name": name,
        "description": description,
        "negotiated_rates": negotiated_rates or [],
    }


def _make_negotiated_rate(
    provider_references: list[int],
    rate: float = 487.50,
    negotiated_type: str = "negotiated",
    billing_class: str = "professional",
    service_code: list[str] | None = None,
    expiration_date: str = "2026-12-31",
) -> dict:
    return {
        "provider_references": provider_references,
        "negotiated_prices": [
            {
                "negotiated_rate": rate,
                "negotiated_type": negotiated_type,
                "billing_class": billing_class,
                "service_code": service_code or ["11"],
                "expiration_date": expiration_date,
            }
        ],
    }


def _make_provider_ref(
    provider_group_id: int,
    npis: list[str],
) -> dict:
    return {
        "provider_group_id": provider_group_id,
        "provider_groups": [
            {
                "npi": npis,
                "tin": {"type": "ein", "value": "123456789"},
            }
        ],
    }


def _write_json(tmp_path: Path, data: dict, filename: str = "tic.json") -> Path:
    """Write TiC data as plain JSON file."""
    p = tmp_path / filename
    p.write_text(json.dumps(data))
    return p


class TestTwoPassBasicMatch:
    """Minimal JSON with 1 matching CPT, 1 provider_reference with matching NPI."""

    def test_returns_one_record(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(
            in_network=[
                _make_in_network_item(
                    billing_code="45378",
                    negotiated_rates=[
                        _make_negotiated_rate(provider_references=[1], rate=487.50),
                    ],
                ),
            ],
            provider_references=[
                _make_provider_ref(provider_group_id=1, npis=["1023049236"]),
            ],
        )
        f = _write_json(tmp_path, data)
        results = parse_insurer_rates(f, insurer_key="bcbs", target_cpts=GI_CPTS)

        assert len(results) == 1
        rec = results[0]
        assert rec.cpt == "45378"
        assert rec.negotiated_rate == 487.50
        assert rec.negotiated_type == "negotiated"
        assert rec.billing_class == "professional"
        assert rec.matched_npi == "1023049236"
        assert rec.hospital_name == "Massachusetts General Hospital"
        assert rec.insurer_key == "bcbs"
        assert rec.source_file == f.name


class TestPercentageTypeFiltered:
    """Rates with negotiated_type='percentage' must be excluded (Dana-Farber artifact)."""

    def test_excludes_percentage(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(
            in_network=[
                _make_in_network_item(
                    billing_code="45378",
                    negotiated_rates=[
                        _make_negotiated_rate(
                            provider_references=[1],
                            rate=85.0,
                            negotiated_type="percentage",
                        ),
                    ],
                ),
            ],
            provider_references=[
                _make_provider_ref(provider_group_id=1, npis=["1023049236"]),
            ],
        )
        f = _write_json(tmp_path, data)
        results = parse_insurer_rates(f, insurer_key="bcbs", target_cpts=GI_CPTS)
        assert len(results) == 0


class TestChaDualNpiMatching:
    """Both CHA NPIs (primary 1275839649, alternate 1487603585) resolve to CHA."""

    def test_primary_npi(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(
            in_network=[
                _make_in_network_item(
                    billing_code="45378",
                    negotiated_rates=[
                        _make_negotiated_rate(provider_references=[1], rate=300.0),
                    ],
                ),
            ],
            provider_references=[
                _make_provider_ref(provider_group_id=1, npis=["1275839649"]),
            ],
        )
        f = _write_json(tmp_path, data)
        results = parse_insurer_rates(f, insurer_key="bcbs", target_cpts=GI_CPTS)
        assert len(results) == 1
        assert results[0].hospital_name == "CHA Cambridge Hospital"
        assert results[0].matched_npi == "1275839649"

    def test_alternate_npi(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(
            in_network=[
                _make_in_network_item(
                    billing_code="45378",
                    negotiated_rates=[
                        _make_negotiated_rate(provider_references=[2], rate=310.0),
                    ],
                ),
            ],
            provider_references=[
                _make_provider_ref(provider_group_id=2, npis=["1487603585"]),
            ],
        )
        f = _write_json(tmp_path, data)
        results = parse_insurer_rates(f, insurer_key="bcbs", target_cpts=GI_CPTS)
        assert len(results) == 1
        assert results[0].hospital_name == "CHA Cambridge Hospital"
        assert results[0].matched_npi == "1487603585"


class TestFeeSchedulePreferred:
    """When both fee_schedule and negotiated types exist for same (hospital, CPT),
    fee_schedule wins."""

    def test_prefers_fee_schedule(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(
            in_network=[
                _make_in_network_item(
                    billing_code="45378",
                    negotiated_rates=[
                        _make_negotiated_rate(
                            provider_references=[1],
                            rate=500.0,
                            negotiated_type="negotiated",
                        ),
                        _make_negotiated_rate(
                            provider_references=[1],
                            rate=450.0,
                            negotiated_type="fee schedule",
                        ),
                    ],
                ),
            ],
            provider_references=[
                _make_provider_ref(provider_group_id=1, npis=["1023049236"]),
            ],
        )
        f = _write_json(tmp_path, data)
        results = parse_insurer_rates(f, insurer_key="bcbs", target_cpts=GI_CPTS)
        assert len(results) == 1
        assert results[0].negotiated_rate == 450.0
        assert results[0].negotiated_type == "fee schedule"


class TestNonMatchingCptExcluded:
    """CPT codes not in the target extraction set are skipped."""

    def test_unknown_cpt_excluded(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(
            in_network=[
                _make_in_network_item(
                    billing_code="99999",
                    negotiated_rates=[
                        _make_negotiated_rate(provider_references=[1], rate=100.0),
                    ],
                ),
            ],
            provider_references=[
                _make_provider_ref(provider_group_id=1, npis=["1023049236"]),
            ],
        )
        f = _write_json(tmp_path, data)
        results = parse_insurer_rates(f, insurer_key="bcbs", target_cpts=GI_CPTS)
        assert len(results) == 0


class TestNonMatchingNpiExcluded:
    """NPIs not in the hospital registry are skipped."""

    def test_unknown_npi_excluded(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(
            in_network=[
                _make_in_network_item(
                    billing_code="45378",
                    negotiated_rates=[
                        _make_negotiated_rate(provider_references=[1], rate=100.0),
                    ],
                ),
            ],
            provider_references=[
                _make_provider_ref(provider_group_id=1, npis=["9999999999"]),
            ],
        )
        f = _write_json(tmp_path, data)
        results = parse_insurer_rates(f, insurer_key="bcbs", target_cpts=GI_CPTS)
        assert len(results) == 0


class TestGzipFormat:
    """Parsing works when input is .json.gz compressed."""

    def test_parses_gzip(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(
            in_network=[
                _make_in_network_item(
                    billing_code="45378",
                    negotiated_rates=[
                        _make_negotiated_rate(provider_references=[1], rate=487.50),
                    ],
                ),
            ],
            provider_references=[
                _make_provider_ref(provider_group_id=1, npis=["1023049236"]),
            ],
        )
        gz_path = tmp_path / "tic.json.gz"
        with gzip.open(gz_path, "wt", encoding="utf-8") as f:
            json.dump(data, f)

        results = parse_insurer_rates(gz_path, insurer_key="bcbs", target_cpts=GI_CPTS)
        assert len(results) == 1
        assert results[0].cpt == "45378"


class TestZipFormat:
    """Parsing works when input is a .zip archive."""

    def test_parses_zip(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(
            in_network=[
                _make_in_network_item(
                    billing_code="45378",
                    negotiated_rates=[
                        _make_negotiated_rate(provider_references=[1], rate=487.50),
                    ],
                ),
            ],
            provider_references=[
                _make_provider_ref(provider_group_id=1, npis=["1023049236"]),
            ],
        )
        zip_path = tmp_path / "tic.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("rates.json", json.dumps(data))

        results = parse_insurer_rates(zip_path, insurer_key="bcbs", target_cpts=GI_CPTS)
        assert len(results) == 1
        assert results[0].cpt == "45378"


class TestBuildHospitalNpiMap:
    """build_hospital_npi_map includes alternate NPIs with resolved names."""

    def test_includes_alternates(self):
        from app.etl.insurer_rate_parser import build_hospital_npi_map

        npi_map = build_hospital_npi_map()
        # CHA primary NPI
        assert "1275839649" in npi_map
        assert npi_map["1275839649"] == "CHA Cambridge Hospital"
        # CHA alternate NPI
        assert "1487603585" in npi_map
        assert npi_map["1487603585"] == "CHA Cambridge Hospital"


class TestEmptyFile:
    """Empty in_network array returns empty list."""

    def test_returns_empty(self, tmp_path: Path):
        from app.etl.insurer_rate_parser import parse_insurer_rates

        data = _make_tic_json(in_network=[], provider_references=[])
        f = _write_json(tmp_path, data)
        results = parse_insurer_rates(f, insurer_key="bcbs", target_cpts=GI_CPTS)
        assert results == []
