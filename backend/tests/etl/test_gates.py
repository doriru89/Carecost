"""Quality gates fail loudly: anchors, row-count drops, stale files."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from app.etl import gates, normalize, stage
from app.etl.config import load_sources, load_yaml

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mrf"
MANIFEST = yaml.safe_load((FIX / "MANIFEST.yaml").read_text())
CFG = load_yaml("gates.yaml")


def _brigham_rows(tmp_path):
    spec = load_sources().get("brigham_mrf").model_copy(update={"container": "plain"})
    sha = MANIFEST["fixtures"]["brigham_11102.csv"]["source_sha256"]
    s = stage.stage_file(spec, FIX / "brigham_11102.csv", sha, tmp_path / "s.parquet")
    normalize.normalize_file(spec, tmp_path / "s.parquet", s, tmp_path / "r.parquet")
    return pq.read_table(tmp_path / "r.parquet").to_pylist()


def _status(results, gate):
    return {r.subject: r.status for r in results if r.gate == gate}


def test_brigham_anchor_passes_on_real_rows(tmp_path):
    rows = _brigham_rows(tmp_path)
    res = gates.check_anchors(rows, [a for a in CFG["anchors"] if a["entity_id"] == "brigham"])
    assert all(r.status == "pass" for r in res), res


def test_missing_anchor_fails(tmp_path):
    rows = [r for r in _brigham_rows(tmp_path) if r["rev_code"] != "0983"]
    res = gates.check_anchors(rows, [a for a in CFG["anchors"] if a["entity_id"] == "brigham"])
    assert _status(res, "anchor")["brigham_11102_aetna_hmo_professional"] == "fail"


def test_anchor_amount_must_be_exact_on_the_same_file(tmp_path):
    rows = _brigham_rows(tmp_path)
    for r in rows:
        if r["rev_code"] == "0761" and r["plan_raw"] == "HB AMC AETNA HMO":
            r["amount"] = 417.41
    res = gates.check_anchors(rows, [a for a in CFG["anchors"] if a["id"].endswith("facility")])
    assert res[0].status == "fail"
    for r in rows:  # a newer file may drift within tolerance
        r["source_sha256"] = "b" * 64
    res = gates.check_anchors(rows, [a for a in CFG["anchors"] if a["id"].endswith("facility")])
    assert res[0].status == "pass"


def test_row_count_drop_fails_and_zero_payer_rates_fails():
    cur = {
        "brigham_mrf": {"rate_rows": 70, "payer_rate_rows": 60},
        "bidmc_mrf": {"rate_rows": 5, "payer_rate_rows": 0},
    }
    prev = {"brigham_mrf": {"rate_rows": 100}, "bidmc_mrf": {"rate_rows": 5}}
    st = _status(gates.check_row_counts(cur, prev, CFG["row_count"]), "row_count")
    assert st == {"brigham_mrf": "fail", "bidmc_mrf": "fail"}
    st = _status(gates.check_row_counts(cur, None, CFG["row_count"]), "row_count")
    assert st["brigham_mrf"] == "pass" and st["bidmc_mrf"] == "fail"


def test_staleness_warn_and_fail():
    dates = {"a": date(2026, 7, 23), "b": date(2026, 3, 27), "c": date(2025, 9, 1), "d": None}
    st = _status(gates.check_staleness(dates, date(2026, 10, 24), CFG["staleness"]), "staleness")
    assert st == {"a": "pass", "b": "warn", "c": "fail", "d": "fail"}


def test_missing_sources_fail():
    res = gates.check_sources_present(["a", "b"], {"a"})
    assert _status(res, "source_present") == {"a": "pass", "b": "fail"}
