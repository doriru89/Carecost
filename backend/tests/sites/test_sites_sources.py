"""DPH lists, the posted-price reader, radiology groups and the census address key (A3)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import openpyxl
import yaml

from app.etl.config import Paths
from app.sites import dph, posted_prices
from app.sites.address import akey, in_scope, z5
from app.sites.build import SITES_DIR


def test_akey_matches_the_census_site_key():
    assert akey("376 Arsenal St.", "02472") == "376 ARSENAL ST|02472"
    assert akey("75 KNEELAND ST FL 1", "02111") == "75 KNEELAND ST|02111"
    assert akey("1000 Broadway, Suite 2", "02150") == "1000 BROADWAY|02150"
    assert (
        z5("02172") == "02472" and in_scope("02472") and in_scope("01801") and not in_scope("01752")
    )


def _facility_xlsx(p: Path, rows: list[tuple]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in [("The Commonwealth of Massachusetts",), (datetime(2026, 9, 8),),
              ("Type of", "DPH Facility"), ("Facility", "ID Number", "Name of Facility", "Street", "City/Town", "Zip Code", "Telephone"),
              *rows]:  # fmt: skip
        ws.append(list(r))
    wb.save(p)
    return p


def test_dph_check_counts_anchor_and_diff(tmp_path, monkeypatch):
    raw = tmp_path / "data" / "raw" / "manual" / "dph"
    raw.mkdir(parents=True)
    sat = [
        ("Hospital Satellite", f"S{i:03d}", f"SAT {i}", f"{i} MAIN ST", "BOSTON", "02115", "")
        for i in range(169)
    ]
    _facility_xlsx(raw / "facilities-2026-09.xlsx",
                   [("Hospital Satellite", "2ED8", "MEDICAL CARE CENTER NORTH", "1000 BROADWAY", "CHELSEA", "02150", ""), *sat[:-1],
                    ("Clinic", "X1", "FAR AWAY", "1 ELM ST", "PITTSFIELD", "01201", "")])  # fmt: skip
    paths = Paths.resolve(tmp_path / "data")
    rep, _svc = dph.check(paths, date(2026, 10, 24), None)
    assert rep["facilities"]["in_scope_by_type"]["Hospital Satellite"] == 169
    assert rep["facilities"]["file_date"] == "2026-09-08"
    assert rep["files"]["facilities"]["method"] == "manual"
    probs = [p for p in rep["problems"] if not p.startswith(("clinic_services", "uc_retail"))]
    assert [p for p in probs if "Hospital Satellite" in p or "2ED8" in p] == []
    # a month later: the anchor and a third of the satellites are gone -> loud
    _facility_xlsx(raw / "facilities-2026-10.xlsx", sat[:100])
    rep2, _ = dph.check(paths, date(2026, 11, 24), rep)
    assert any("2ED8" in p for p in rep2["problems"])
    assert any("Hospital Satellite: 100 in scope vs 169" in p for p in rep2["problems"])
    assert "S150" in rep2["diff"]["gone"] and "2ED8" in rep2["diff"]["gone"]


def test_committed_dph_check_matches_the_census_baseline():
    rep = __import__("json").loads((SITES_DIR / "dph_check.json").read_text())
    assert rep["problems"] == []
    got = rep["facilities"]["in_scope_by_type"]
    assert {k: got[k] for k in dph.BASELINE_IN_SCOPE} == dph.BASELINE_IN_SCOPE
    assert {f["method"] for f in rep["files"].values()} == {"browser"}


AFC = """
<div class="section-header">Most Common Services</div><table><tbody>
<tr><td class="sub-header label-cell" colspan="2">Evaluation Consultation (provider)</td><td class="sub-header price">$179</td></tr>
<tr><td>X-Ray 1 View / 2 views / 3 views</td><td class="price">$80 / $150 / $225</td></tr>
<tr><td>DOT Physical</td><td class="price">$130 / ($45-$75-$85)</td></tr>
</tbody></table>
<div class="section-header">DME</div><table><tbody><tr><td>Arm Sling</td><td class="price">$32</td></tr></tbody></table>
"""


def test_afc_reader_splits_multi_price_rows_and_keeps_unpriced():
    items = posted_prices.parse_afc(AFC)
    got = {i["label"]: i["amount"] for i in items}
    assert got == {"Evaluation Consultation (provider)": 179.0, "X-Ray 1 View": 80.0, "X-Ray 2 views": 150.0,
                   "X-Ray 3 views": 225.0, "DOT Physical": None, "Arm Sling": 32.0}  # fmt: skip
    cur = [{"item_id": "xray_2_views", "label": "X-ray, 2 views", "amount": 150.0},
           {"item_id": "sling", "label": "Sling", "amount": 30.0},
           {"item_id": "mri", "label": "MRI", "amount": 900.0}]  # fmt: skip
    d = {x["item_id"]: x["change"] for x in posted_prices.diff(items, cur)}
    assert d == {"sling": "amount", "mri": "not_on_page"}


def test_committed_afc_read_agrees_with_curated_prices():
    out = __import__("json").loads((SITES_DIR / "posted" / "afc_watertown.json").read_text())
    assert out["robots"] == "allowed" and out["priced_rows"] > 50 and out["diff_vs_curated"] == []


def test_radiology_groups_cover_the_p1_hospitals():
    rg = yaml.safe_load((SITES_DIR / "radiology_groups.yaml").read_text())
    h = rg["hospitals"]
    assert {"tufts", "mtauburn", "mgh", "brigham", "bidmc"} <= set(h)
    tins = {t["tin"] for g in h["mtauburn"] for t in g["tins"]}
    assert "042482067" in tins  # Schatzki Associates reads Mount Auburn's images
    for groups in h.values():
        for g in groups:
            assert all(len(t["tin"]) == 9 and t["share"] >= 0.25 for t in g["tins"])
