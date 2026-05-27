"""TDD tests for hospital MRF rate parser — Phase 2a.

Each test creates minimal inline fixtures (tmp_path) to test one parser behavior.
"""

from __future__ import annotations

import csv
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from app.etl.hospital_rate_parser import parse_all_hospital_rates, parse_hospital_rates
from app.etl.types import RawMrfRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
DERM_CPTS = {
    "99213",
    "99214",
    "11102",
    "11104",
    "11106",
    "11300",
    "11305",
    "11400",
    "11401",
    "11600",
    "11602",
    "17110",
    "17111",
    "17311",
    "17312",
    "88305",
    "88312",
    "96910",
    "96920",
    "96922",
}


def _write_csv(path: Path, rows: list[list[str]], encoding: str = "utf-8") -> Path:
    with open(path, "w", newline="", encoding=encoding) as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return path


def _make_standard_csv_row(
    cpt: str = "45378",
    description: str = "COLONOSCOPY WITH BIOPSY",
    cpt_desc: str = "Colonoscopy diagnostic",
    payer: str = "BCBS",
    plan: str = "PPO",
    setting: str = "outpatient",
    gross: str = "5000.00",
    cash: str = "3000.00",
    negotiated: str = "2500.00",
    estimated: str = "2400.00",
    min_val: str = "2000.00",
    max_val: str = "3000.00",
) -> list[str]:
    """Build a 23-column standard_csv row matching MGB layout.

    Indices: 0=description, 3=cpt, 4=cpt_desc, 5=description_alt,
    9=setting, 12=gross, 13=cash, 14=payer, 15=plan,
    17=negotiated_dollar, 18=estimated_amount, 19=min, 20=max.
    """
    row = [""] * 23
    row[0] = description
    row[3] = cpt
    row[4] = cpt_desc
    row[5] = description
    row[9] = setting
    row[12] = gross
    row[13] = cash
    row[14] = payer
    row[15] = plan
    row[17] = negotiated
    row[18] = estimated
    row[19] = min_val
    row[20] = max_val
    return row


# ---------------------------------------------------------------------------
# 1) test_parse_standard_csv_filters_by_cpt
# ---------------------------------------------------------------------------


def test_parse_standard_csv_filters_by_cpt(tmp_path: Path):
    """5 rows, only 2 match GI CPTs — verify filtering."""
    rows = [
        # 2 metadata rows to skip
        ["Hospital Name", "MGB"],
        ["Report Date", "2025-01-01"],
        # Data rows (no header row — positional)
        _make_standard_csv_row(cpt="45378", payer="BCBS", gross="5000"),
        _make_standard_csv_row(cpt="99999", payer="Aetna", gross="100"),  # non-GI
        _make_standard_csv_row(cpt="43239", payer="UHC", gross="4000"),
        _make_standard_csv_row(cpt="00000", payer="Cigna", gross="200"),  # non-GI
        _make_standard_csv_row(cpt="12345", payer="BCBS", gross="300"),  # non-GI
    ]
    csv_path = _write_csv(tmp_path / "mgh_standardcharges.csv", rows)

    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=2):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)

    assert len(results) == 2
    assert all(isinstance(r, RawMrfRecord) for r in results)
    cpts = {r.cpt for r in results}
    assert cpts == {"45378", "43239"}


# ---------------------------------------------------------------------------
# 2) test_parse_standard_csv_skips_header_rows
# ---------------------------------------------------------------------------


def test_parse_standard_csv_skips_header_rows(tmp_path: Path):
    """Verify metadata rows are skipped per skip_header_rows config."""
    rows = [
        ["Hospital Name", "MGB"],  # metadata row 1
        ["Report Date", "2025-01-01"],  # metadata row 2
        # If skip=2, parsing starts here — this IS a data row with matching CPT
        _make_standard_csv_row(cpt="45378", payer="BCBS"),
    ]
    csv_path = _write_csv(tmp_path / "test.csv", rows)

    # With skip=2, should find the matching row
    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=2):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)
    assert len(results) == 1

    # With skip=3, should skip the data row too
    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=3):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# 3) test_parse_cms_json_extracts_matching_cpts
# ---------------------------------------------------------------------------


def test_parse_cms_json_extracts_matching_cpts(tmp_path: Path):
    """Minimal JSON fixture: 3 standard_charge_information items, 1 matches GI."""
    data = {
        "standard_charge_information": [
            {
                "description": "EGD with biopsy",
                "code_information": [
                    {"code": "43239", "type": "CPT"},
                ],
                "standard_charges": [
                    {
                        "payer_name": "BCBS",
                        "plan_name": "PPO",
                        "setting": "outpatient",
                        "gross_charge": 6000,
                        "discounted_cash": 4000,
                        "standard_charge_dollar": 3500,
                        "minimum": 3000,
                        "maximum": 7000,
                    },
                ],
            },
            {
                "description": "MRI Brain",
                "code_information": [
                    {"code": "70553", "type": "CPT"},
                ],
                "standard_charges": [
                    {
                        "payer_name": "Aetna",
                        "plan_name": "HMO",
                        "setting": "outpatient",
                        "gross_charge": 8000,
                    },
                ],
            },
            {
                "description": "Lab panel",
                "code_information": [
                    {"code": "80053", "type": "CPT"},
                ],
                "standard_charges": [
                    {
                        "payer_name": "UHC",
                        "plan_name": "EPO",
                        "gross_charge": 200,
                    },
                ],
            },
        ]
    }
    json_path = tmp_path / "bidmc_standardcharges.json"
    json_path.write_text(json.dumps(data))

    with _mock_hospital_source("bidmc", "cms_json"):
        results = parse_hospital_rates(json_path, "bidmc", GI_CPTS)

    assert len(results) == 1
    rec = results[0]
    assert rec.cpt == "43239"
    assert rec.gross == 6000.0
    assert rec.cash == 4000.0
    assert rec.payer_raw == "BCBS"
    assert rec.plan == "PPO"
    assert rec.de_id_min == 3000.0
    assert rec.de_id_max == 7000.0
    assert rec.mrf_format == "cms_json"


# ---------------------------------------------------------------------------
# 4) test_parse_cms_v3_csv_dynamic_headers
# ---------------------------------------------------------------------------


def test_parse_cms_v3_csv_dynamic_headers(tmp_path: Path):
    """CMS v3 with code|1, code|2 columns — CPT in code|2."""
    header = [
        "description",
        "code|1",
        "code|1|type",
        "code|2",
        "code|2|type",
        "modifiers",
        "setting",
        "drug_unit_of_measurement",
        "drug_type_of_measurement",
        "standard_charge|gross",
        "standard_charge|discounted_cash",
        "payer_name",
        "plan_name",
        "standard_charge|negotiated_dollar",
        "standard_charge|negotiated_percentage",
        "standard_charge|negotiated_algorithm",
        "median_amount",
        "10th_percentile",
        "90th_percentile",
        "count",
        "standard_charge|methodology",
        "standard_charge|min",
        "standard_charge|max",
        "additional_generic_notes",
    ]
    rows = [
        ["META ROW 1"],
        ["META ROW 2"],
        ["META ROW 3"],
        header,
        # Matching row: code|2 = 45378 (CPT)
        [
            "Colonoscopy diagnostic",
            "CDM123",
            "CDM",
            "45378",
            "CPT",
            "",
            "outpatient",
            "",
            "",
            "5000",
            "3000",
            "BCBS",
            "PPO",
            "2500",
            "",
            "",
            "2400",
            "",
            "",
            "",
            "",
            "2000",
            "3000",
            "",
        ],
        # Non-matching row
        [
            "MRI Brain",
            "CDM456",
            "CDM",
            "70553",
            "CPT",
            "",
            "outpatient",
            "",
            "",
            "8000",
            "6000",
            "Aetna",
            "HMO",
            "5000",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
    ]
    csv_path = _write_csv(tmp_path / "tufts.csv", rows)

    with _mock_hospital_source("tufts", "cms_v3_csv", skip_header_rows=3):
        results = parse_hospital_rates(csv_path, "tufts", GI_CPTS)

    assert len(results) == 1
    rec = results[0]
    assert rec.cpt == "45378"
    assert rec.gross == 5000.0
    assert rec.cash == 3000.0
    assert rec.negotiated_dollar == 2500.0
    assert rec.payer_raw == "BCBS"
    assert rec.de_id_min == 2000.0
    assert rec.de_id_max == 3000.0
    assert rec.mrf_format == "cms_v3_csv"


# ---------------------------------------------------------------------------
# 5) test_parse_csv_wide_unpivots_payer_columns
# ---------------------------------------------------------------------------


def test_parse_csv_wide_unpivots_payer_columns(tmp_path: Path):
    """1 row with 2 payer columns -> 2 RawMrfRecords."""
    header = [
        "description",
        "code|1",
        "code|1|type",
        "code|2",
        "code|2|type",
        "modifiers",
        "setting",
        "standard_charge|gross",
        "standard_charge|discounted_cash",
        "standard_charge|BCBS|PPO|negotiated_dollar",
        "standard_charge|Aetna|HMO|negotiated_dollar",
        "standard_charge|min",
        "standard_charge|max",
    ]
    rows = [
        header,
        [
            "Colonoscopy diagnostic",
            "CDM123",
            "CDM",
            "45378",
            "CPT",
            "",
            "outpatient",
            "5000",
            "3000",
            "2500",  # BCBS PPO
            "2800",  # Aetna HMO
            "2000",
            "3500",
        ],
    ]
    csv_path = _write_csv(tmp_path / "franciscan.csv", rows)

    with _mock_hospital_source("franciscan", "csv_wide"):
        results = parse_hospital_rates(csv_path, "franciscan", GI_CPTS)

    assert len(results) == 2
    payer_plans = {(r.payer_raw, r.plan) for r in results}
    assert ("BCBS", "PPO") in payer_plans
    assert ("Aetna", "HMO") in payer_plans

    bcbs = [r for r in results if r.payer_raw == "BCBS"][0]
    assert bcbs.negotiated_dollar == 2500.0
    assert bcbs.gross == 5000.0
    assert bcbs.cpt == "45378"

    aetna = [r for r in results if r.payer_raw == "Aetna"][0]
    assert aetna.negotiated_dollar == 2800.0


# ---------------------------------------------------------------------------
# 6) test_empty_file_returns_empty_list
# ---------------------------------------------------------------------------


def test_empty_file_returns_empty_list(tmp_path: Path):
    """Empty CSV should return [] without crashing."""
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("")

    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)

    assert results == []


# ---------------------------------------------------------------------------
# 7) test_both_specialty_cpt_sets_work
# ---------------------------------------------------------------------------


def test_both_specialty_cpt_sets_work(tmp_path: Path):
    """Same parser works with both gi and derm CPT sets."""
    # Row with a derm CPT
    rows = [
        _make_standard_csv_row(cpt="99213", payer="BCBS", gross="200"),
        _make_standard_csv_row(cpt="45378", payer="BCBS", gross="5000"),
    ]
    csv_path = _write_csv(tmp_path / "test.csv", rows)

    # With gi specialty, only 45378 matches
    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        gi_results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)
    assert len(gi_results) == 1
    assert gi_results[0].cpt == "45378"

    # With derm specialty, only 99213 matches
    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        derm_results = parse_hospital_rates(csv_path, "mgh", DERM_CPTS)
    assert len(derm_results) == 1
    assert derm_results[0].cpt == "99213"


# ---------------------------------------------------------------------------
# 8) test_parse_all_hospital_rates_warns_on_missing
# ---------------------------------------------------------------------------


def test_parse_all_hospital_rates_warns_on_missing(tmp_path: Path, caplog):
    """Missing MRF file logs a warning but doesn't crash."""
    # Create a directory with NO files for mgh
    with caplog.at_level(logging.WARNING):
        results = parse_all_hospital_rates(tmp_path, GI_CPTS)

    # Should return empty (no files found)
    assert isinstance(results, list)
    # Should have logged warnings about missing files
    assert any(
        "not found" in r.message.lower() or "missing" in r.message.lower() for r in caplog.records
    )


# ---------------------------------------------------------------------------
# 9) test_unknown_hospital_raises
# ---------------------------------------------------------------------------


def test_unknown_hospital_raises(tmp_path: Path):
    """Unknown hospital_id raises KeyError."""
    csv_path = tmp_path / "fake.csv"
    csv_path.write_text("a,b,c")

    with pytest.raises(KeyError, match="unknown_hospital_xyz"):
        parse_hospital_rates(csv_path, "unknown_hospital_xyz", GI_CPTS)


# ---------------------------------------------------------------------------
# 10) test_parse_float_edge_cases (bonus: validates _parse_float helper)
# ---------------------------------------------------------------------------


def test_monetary_fields_are_float_or_none(tmp_path: Path):
    """Monetary fields parse to float; invalid/empty -> None."""
    rows = [
        _make_standard_csv_row(
            cpt="45378",
            gross="5000.50",
            cash="",
            negotiated="N/A",
            estimated="2400",
            min_val="abc",
            max_val="3000",
        ),
    ]
    csv_path = _write_csv(tmp_path / "test.csv", rows)

    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)

    assert len(results) == 1
    rec = results[0]
    assert rec.gross == 5000.50
    assert rec.cash is None  # empty string
    assert rec.negotiated_dollar is None  # "N/A"
    assert rec.estimated_amount == 2400.0
    assert rec.de_id_min is None  # "abc"
    assert rec.de_id_max == 3000.0


# ---------------------------------------------------------------------------
# 11) test_source_file_and_mrf_format_populated
# ---------------------------------------------------------------------------


def test_source_file_and_mrf_format_populated(tmp_path: Path):
    """source_file and mrf_format are set on every record."""
    rows = [
        _make_standard_csv_row(cpt="45378"),
    ]
    csv_path = _write_csv(tmp_path / "test.csv", rows)

    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)

    assert len(results) == 1
    assert results[0].source_file == str(csv_path)
    assert results[0].mrf_format == "standard_csv"


# ---------------------------------------------------------------------------
# Mock helper — patches registry lookups for test isolation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 12) test_dedup_collapses_description_aliases
# ---------------------------------------------------------------------------


def test_dedup_collapses_description_aliases(tmp_path: Path):
    """Two rows with same (cpt, payer, plan) but different descriptions are deduped."""
    rows = [
        _make_standard_csv_row(
            cpt="45385",
            description="Colonoscopy Flex W/Rem Tumor Snare",
            payer="AETNA",
            plan="HMO",
            negotiated="1442.09",
        ),
        _make_standard_csv_row(
            cpt="45385",
            description="Colsc Flx W/Rmvl of Tumor Polyp Lesion",
            payer="AETNA",
            plan="HMO",
            negotiated="1442.09",
        ),
    ]
    csv_path = _write_csv(tmp_path / "test.csv", rows)

    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)

    assert len(results) == 1
    assert results[0].cpt == "45385"
    assert results[0].negotiated_dollar == 1442.09


# ---------------------------------------------------------------------------
# 13) test_dedup_keeps_max_negotiated_rate
# ---------------------------------------------------------------------------


def test_dedup_keeps_max_negotiated_rate(tmp_path: Path):
    """Facility ($769) vs professional ($182) fee rows: keep higher rate."""
    rows = [
        _make_standard_csv_row(
            cpt="11106",
            description="Incisional Biopsy Skin",
            payer="WELLPOINT",
            plan="PPO",
            negotiated="769.53",
        ),
        _make_standard_csv_row(
            cpt="11106",
            description="Pf Incisional Biopsy Skin",
            payer="WELLPOINT",
            plan="PPO",
            negotiated="182.24",
        ),
    ]
    csv_path = _write_csv(tmp_path / "test.csv", rows)

    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        results = parse_hospital_rates(csv_path, "mgh", DERM_CPTS)

    assert len(results) == 1
    assert results[0].negotiated_dollar == 769.53


# ---------------------------------------------------------------------------
# 14) test_dedup_preserves_different_plans
# ---------------------------------------------------------------------------


def test_dedup_preserves_different_plans(tmp_path: Path):
    """Same CPT+payer but different plans must NOT be deduped."""
    rows = [
        _make_standard_csv_row(
            cpt="45378", payer="BCBS", plan="HMO", negotiated="2500.00"
        ),
        _make_standard_csv_row(
            cpt="45378", payer="BCBS", plan="PPO", negotiated="3200.00"
        ),
    ]
    csv_path = _write_csv(tmp_path / "test.csv", rows)

    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)

    assert len(results) == 2
    plans = {r.plan for r in results}
    assert plans == {"HMO", "PPO"}


# ---------------------------------------------------------------------------
# 15) test_dedup_preserves_different_payers
# ---------------------------------------------------------------------------


def test_dedup_preserves_different_payers(tmp_path: Path):
    """Same CPT+plan but different payers must NOT be deduped."""
    rows = [
        _make_standard_csv_row(
            cpt="45378", payer="BCBS", plan="PPO", negotiated="2500.00"
        ),
        _make_standard_csv_row(
            cpt="45378", payer="AETNA", plan="PPO", negotiated="3000.00"
        ),
    ]
    csv_path = _write_csv(tmp_path / "test.csv", rows)

    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)

    assert len(results) == 2
    payers = {r.payer_raw for r in results}
    assert payers == {"BCBS", "AETNA"}


# ---------------------------------------------------------------------------
# 16) test_dedup_all_none_negotiated_keeps_first
# ---------------------------------------------------------------------------


def test_dedup_all_none_negotiated_keeps_first(tmp_path: Path):
    """When all records have None negotiated_dollar, keep first seen."""
    rows = [
        _make_standard_csv_row(
            cpt="45378",
            description="Colonoscopy A",
            payer="BCBS",
            plan="PPO",
            negotiated="",
            gross="5000.00",
        ),
        _make_standard_csv_row(
            cpt="45378",
            description="Colonoscopy B",
            payer="BCBS",
            plan="PPO",
            negotiated="",
            gross="5000.00",
        ),
    ]
    csv_path = _write_csv(tmp_path / "test.csv", rows)

    with _mock_hospital_source("mgh", "standard_csv", skip_header_rows=0):
        results = parse_hospital_rates(csv_path, "mgh", GI_CPTS)

    assert len(results) == 1
    assert results[0].negotiated_dollar is None
    assert results[0].gross == 5000.0


@contextmanager
def _mock_hospital_source(
    hospital_id: str,
    fmt: str,
    encoding: str = "utf-8",
    container: str = "plain",
    skip_header_rows: int = 0,
):
    """Mock the registry lookups so tests don't need real YAML files."""
    source_config = {
        "format": fmt,
        "encoding": encoding,
        "container": container,
        "skip_header_rows": skip_header_rows,
    }

    class FakeEtlConfig:
        mrf_formats = {
            "standard_csv": {
                "cpt_column_index": 3,
                "payer_column_index": 14,
                "plan_column_index": 15,
                "setting_column_index": 9,
                "skip_header_rows": 0,
            },
            "cms_v3_csv": {
                "header_pattern": "code|",
                "skip_header_rows": 3,
            },
            "cms_json": {
                "cpt_path": "standard_charge_information[].code_information[].code",
            },
            "xlsx": {
                "cpt_column": "CPT/HCPCS Code",
            },
            "csv_wide": {
                "header_pattern": "standard_charge|",
            },
        }
        cpt_extraction_sets = {
            "gi": [
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
            ],
            "derm": [
                "99213",
                "99214",
                "11102",
                "11104",
                "11106",
                "11300",
                "11305",
                "11400",
                "11401",
                "11600",
                "11602",
                "17110",
                "17111",
                "17311",
                "17312",
                "88305",
                "88312",
                "96910",
                "96920",
                "96922",
            ],
        }
        hospital_mrf_sources = {hospital_id: source_config}

    class FakeHospital:
        name = "Test Hospital"

    with (
        patch("app.etl.hospital_rate_parser.load_etl_config", return_value=FakeEtlConfig()),
        patch("app.etl.hospital_rate_parser.get_hospital", return_value=FakeHospital()),
    ):
        yield
