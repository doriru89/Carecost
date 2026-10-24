"""Lossless staging of CMS v3.0.0 hospital files (tall CSV, wide CSV, JSON with BOM).

Golden fixtures are real rows cut by scripts/etl/cut_golden_fixtures.py (see MANIFEST.yaml).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

from app.etl import stage
from app.etl.config import load_sources

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mrf"
MANIFEST = yaml.safe_load((FIX / "MANIFEST.yaml").read_text())


def spec_for(source_id: str, **over):
    s = load_sources().get(source_id)
    # fixtures are plain files even when the real source is a zip
    return s.model_copy(update={"container": "plain", **over})


def staged(tmp_path: Path, source_id: str, fixture: str):
    spec = spec_for(source_id)
    sha = MANIFEST["fixtures"][fixture]["source_sha256"]
    res = stage.stage_file(spec, FIX / fixture, sha, tmp_path / "out.parquet")
    rows = pq.read_table(tmp_path / "out.parquet").to_pylist()
    return res, rows


@pytest.mark.parametrize(
    "raw, iso",
    [
        ("2026-03-27", date(2026, 3, 27)),
        ("03/13/2026", date(2026, 3, 13)),
        ("3/20/2026", date(2026, 3, 20)),
        ("4/1/2026", date(2026, 4, 1)),
    ],
)
def test_four_date_formats(raw, iso):
    assert stage.parse_date(raw) == iso


def test_unknown_date_format_fails_loudly():
    with pytest.raises(ValueError):
        stage.parse_date("March 27th")


# 1 + 6: Brigham 11102 -- both the facility (RC 0761) and professional (RC 0983) lines survive.
def test_brigham_tall_csv_keeps_both_component_lines(tmp_path):
    res, rows = staged(tmp_path, "brigham_mrf", "brigham_11102.csv")
    assert res.staged_rows == res.independent_count == 72  # every data row, no filter, no dedup
    hmo = [r for r in rows if r["plan_name"] == "HB AMC AETNA HMO"]
    got = sorted((r["code_values"], r["negotiated_dollar"]) for r in hmo)
    assert [d for _, d in got] == ["115.17", "417.40"] or [d for _, d in got] == [
        "417.40",
        "115.17",
    ]
    rcs = {
        next(c["code"] for c in r["codes"] if c["type"] == "RC"): r["negotiated_dollar"]
        for r in hmo
    }
    assert rcs == {"0761": "417.40", "0983": "115.17"}
    assert all(r["methodology"] == "percent of total billed charges" for r in hmo)
    assert res.meta.last_updated_on == date(2026, 3, 27)
    assert res.meta.type_2_npis == ["1790717650"]


# 3: Franciscan is a WIDE file: payer|plan groups live in the header and are unpivoted.
def test_franciscan_wide_csv_unpivots_payer_groups(tmp_path):
    res, rows = staged(tmp_path, "franciscan_mrf", "franciscan_99213.csv")
    assert res.wide_payer_groups == 21
    assert res.staged_rows == res.independent_count
    assert res.items == 11  # 11 chargemaster lines carry 99213
    payers = {(r["payer_name"], r["plan_name"]) for r in rows}
    assert ("Aetna", "Commercial") in payers  # trailing spaces from the header are stripped
    assert ("BCBS", "Indemnity, PPA, HMO Blue Out of State") in payers
    with_dollar = [r for r in rows if r["negotiated_dollar"]]
    assert with_dollar and all(r["methodology"] for r in with_dollar)
    by_item: dict[int, set[str]] = {}
    for r in rows:  # base columns (gross etc.) are repeated onto every leaf of a line
        by_item.setdefault(r["item_ordinal"], set()).add(r["gross"])
    assert all(len(g) == 1 for g in by_item.values())


# 2 + 11: BIDMC JSON (with a UTF-8 BOM) streams; payer is read from payers_information[] (E1).
def test_bidmc_json_with_bom_reads_payers_information(tmp_path):
    raw = (FIX / "bidmc_73030.json").read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"
    res, rows = staged(tmp_path, "bidmc_mrf", "bidmc_73030.json")
    assert res.items == 2 and res.staged_rows == res.independent_count == 7
    cdm = [r for r in rows if not r["payer_name"]]
    assert len(cdm) == 1 and cdm[0]["gross"] == "395.0" and cdm[0]["billing_class"] == "facillity"
    payer_rows = [r for r in rows if r["payer_name"]]
    assert len(payer_rows) == 6
    bcbs = [r for r in payer_rows if (r["payer_name"], r["plan_name"]) == ("Bcbs", "Hmo")]
    assert bcbs[0]["negotiated_dollar"] == "110.42" and bcbs[0]["methodology"] == "fee schedule"
    assert bcbs[0]["setting"] == "outpatient" and bcbs[0]["min"] == "66.69"
    assert res.meta.type_2_npis == ["1548202641"]
    assert res.modifier_items == 2


def test_dana_farber_nonstandard_modifiers_key_is_kept_in_extra(tmp_path):
    res, rows = staged(tmp_path, "dana_farber_mrf", "dana_farber_modifiers.json")
    extras = [json.loads(r["extra"]) for r in rows if r["extra"]]
    assert extras and all("charge.modifiers" in e for e in extras)
    assert all(r["modifiers"] for r in rows)  # promoted to the modifiers column too


def test_staged_rows_carry_source_sha_and_ordinal(tmp_path):
    res, rows = staged(tmp_path, "brigham_mrf", "brigham_11102.csv")
    sha = MANIFEST["fixtures"]["brigham_11102.csv"]["source_sha256"]
    assert {r["source_sha256"] for r in rows} == {sha}
    assert [r["stage_row"] for r in rows] == list(range(len(rows)))


def test_row_conservation_failure_is_loud(tmp_path, monkeypatch):
    monkeypatch.setattr(stage, "count_leaves", lambda spec, path: 999)
    spec = spec_for("brigham_mrf")
    with pytest.raises(stage.StageError, match="conservation"):
        stage.stage_file(spec, FIX / "brigham_11102.csv", "a" * 64, tmp_path / "o.parquet")
    assert not (tmp_path / "o.parquet").exists()


def test_meta_reads_multi_campus_cha_header():
    meta = stage.read_meta(spec_for("cha_mrf"), FIX / "meta" / "cha_mrf.csv")
    assert meta.type_2_npis == ["1487603585", "1447348313"]
    assert len(meta.location_names) == 3
    assert meta.last_updated_on == date(2026, 3, 20)
