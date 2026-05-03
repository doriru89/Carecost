"""Tests for CMS PFS RVU parser — written BEFORE implementation (TDD)."""

from pathlib import Path

import pytest

from app.etl.rvu_parser import parse_rvu_file

RVU_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "raw"
    / "government"
    / "cms_pfs"
    / "PPRRVU2026_Jan_nonQPP.csv"
)

skip_if_no_rvu = pytest.mark.skipif(
    not RVU_PATH.exists(),
    reason="CMS RVU file not downloaded",
)


@skip_if_no_rvu
class TestRvuParser:
    def test_cpt_45378_extracted(self):
        recs = parse_rvu_file(RVU_PATH, {"45378"})
        assert len(recs) >= 1
        global_rec = next(r for r in recs if r.modifier == "")
        assert global_rec.cpt == "45378"
        assert global_rec.description == "Diagnostic colonoscopy"

    def test_cpt_45378_rvu_values(self):
        recs = parse_rvu_file(RVU_PATH, {"45378"})
        rec = next(r for r in recs if r.modifier == "")
        assert rec.work_rvu is not None
        assert rec.facility_pe_rvu is not None
        assert rec.malpractice_rvu is not None
        assert rec.facility_total_rvu == pytest.approx(4.93, abs=0.1)

    def test_cpt_45378_conversion_factor(self):
        recs = parse_rvu_file(RVU_PATH, {"45378"})
        rec = next(r for r in recs if r.modifier == "")
        assert rec.conversion_factor == pytest.approx(33.4009, abs=0.01)

    def test_modifier_53_separate_record(self):
        recs = parse_rvu_file(RVU_PATH, {"45378"})
        mods = {r.modifier for r in recs}
        assert "" in mods
        assert "53" in mods
        mod53 = next(r for r in recs if r.modifier == "53")
        assert mod53.facility_total_rvu < 4.93

    def test_filter_to_target_cpts_only(self):
        recs = parse_rvu_file(RVU_PATH, {"45378", "43239"})
        cpts = {r.cpt for r in recs}
        assert cpts == {"45378", "43239"}

    def test_all_gi_cpts_present(self):
        gi_cpts = {
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
        recs = parse_rvu_file(RVU_PATH, gi_cpts)
        found_cpts = {r.cpt for r in recs}
        missing = gi_cpts - found_cpts
        assert not missing, f"GI CPTs missing from RVU file: {missing}"

    def test_pfs_year_and_source_file_populated(self):
        recs = parse_rvu_file(RVU_PATH, {"45378"}, pfs_year=2026)
        for r in recs:
            assert r.pfs_year == 2026
            assert r.source_file == "PPRRVU2026_Jan_nonQPP.csv"

    def test_empty_cpt_set_returns_empty(self):
        recs = parse_rvu_file(RVU_PATH, set())
        assert recs == []

    def test_nonexistent_cpt_returns_empty(self):
        recs = parse_rvu_file(RVU_PATH, {"99999"})
        assert recs == []
