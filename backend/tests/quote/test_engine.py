"""The quote engine end to end on the committed extract (real rows; written by
``python -m app.quote.fixtures_gen`` from hospital build 20261025-336340ed, the 2026-10 TiC files
and A3's fee schedules: Medicare PFS RVU26D + anesthesia, OPPS and ASC October 2026, MassHealth
101 CMR 316/317/318). Registry: data/sites/sites.yaml (208 sites); the tests quote the six P1
sites by name (fixtures_gen.KEY_SITES). One end-to-end test per payment kind, plus the doctor-fee
ladder, the imaging-read ruling, D20 conflicts, freshness and the P1 problems C / C2 fixed."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from app.quote.contracts import QuoteRequest, QuoteResponse
from app.quote.engine import Engine
from app.quote.fixtures_gen import GOLDEN, KEY_SITES, fixture_text, request
from app.quote.store import EXTRACT_CSV, load_pack
from tests.quote.conftest import AS_OF, FIX, fixture_doc

BCBS_HMO = {"kind": "insurance", "payer_id": "BCBS_MA", "product": "HMO", "network": None}
MA, TUFTS, AFC, BWH = (
    "mount_auburn_hospital",
    "tufts_medical_center",
    "afc_watertown",
    "brigham_and_womens_hospital",
)


def _quote(engine, payment, path="shoulder_chronic_clicking_v1", answers=None, codes=(),
           sites=KEY_SITES, as_of=AS_OF, **more) -> QuoteResponse:  # fmt: skip
    req = QuoteRequest.model_validate({
        "payment": payment, "care_path_id": path, "answers": answers or {},
        "service_codes": list(codes), "picked_by": "person", "site_ids": sites, **more,
    })  # fmt: skip
    return engine.quote(req, as_of)


def _line(resp: QuoteResponse, site: str, line_id: str):
    sq = next(s for s in resp.sites if s.site.site_id == site)
    return next(ln for ln in sq.receipt.lines if ln.line_id == line_id)


# --------------------------------------------------------------------------- startup


def test_runtime_pack_loads_into_in_memory_indexes(store):
    """P1 #11: one runtime format (SQLite pack, stdlib), loaded once into dicts."""
    assert len(store.rows) == sum(1 for _ in EXTRACT_CSV.open()) - 1
    assert store.version.build_id == "20261025-336340ed"
    assert store.version.tic_release == "tic-2026-10"
    kinds = {m.source_kind for m in store.sources.values()}
    assert kinds == {"hospital_mrf", "insurer_tic", "medicare_pfs", "medicare_opps",
                     "medicare_asc", "masshealth_fs"}  # fmt: skip
    assert any(k[0] == "tic_bcbs_ma_hmo_blue_fi" for k in store.tic)
    assert any(k[0] == "tufts_mrf" for k in store.cash)
    assert store.npi_sets, "D6 needs the NPIs of small TiC provider groups"
    pfs = [r for r in store.rows if r.source_kind == "medicare_pfs"]
    assert {r.place_of_service for r in pfs} >= {"facility", "non_facility"}  # not plan_raw
    assert {r.entity_id for r in pfs} >= {"medicare_ma_01"}


def test_runtime_needs_no_pyarrow():
    """The server path (store + engine + server) imports no pyarrow; only app.quote.pack does."""
    import subprocess
    import sys

    code = (
        "import sys, app.server; "
        "assert 'pyarrow' not in sys.modules, 'pyarrow imported by the runtime'"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=Path(__file__).resolve().parents[2])  # fmt: skip
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not os.environ.get("CARECOST_QUOTE_PACK"), reason="real pack not built here")
def test_real_pack_loads(registry):
    store = load_pack(Path(os.environ["CARECOST_QUOTE_PACK"]), tins=registry.tins,
                      census_ids=registry.census_ids)  # fmt: skip
    assert len(store.rows) > 10_000
    _quote(Engine(store, registry), BCBS_HMO)


# --------------------------------------------------------------------------- golden fixtures


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_engine_reproduces_the_golden_fixture(engine, name):
    text = fixture_text(engine.quote(request(name), AS_OF).model_dump(mode="json"))
    assert text == (FIX / f"{GOLDEN[name]}.json").read_text()


# --------------------------------------------------------------------------- one e2e per payment


def test_e2e_insurance_bcbs_hmo(engine):
    r = _quote(engine, BCBS_HMO, answers={"Q14": ["hmo_referral_required"]})
    from app.quote.contracts import rank_key

    assert [rank_key(s) for s in r.sites] == sorted(rank_key(s) for s in r.sites)  # I7
    # Austin 2026-10-24 (P1 #6): readings use the group's POS-11 TiC rate at the hospital. With
    # A5's radiology TINs (wave2/a5-etl) Mount Auburn's radiologists (Schatzki Associates,
    # radiology_groups.yaml) now have rows, so their rate prices the reading first.
    x = _line(r, MA, "xray_reading")
    assert (x.cell.low, x.cell.high) == (17.33, 17.33)
    assert x.doctor_fee.group_name == "SCHATZKI ASSOCIATES INC"
    assert _line(r, MA, "tendon_scan_ultrasound_reading").cell.low == 82.07
    mri = _line(r, MA, "tendon_scan_mri_reading")
    assert (mri.cell.low, mri.cell.high) == (120.81, 120.81)
    assert r.copy_keys == ["copy.not_a_diagnosis", "copy.when_to_see_a_doctor"]  # P1 #13
    assert _line(r, MA, "referral").at == "your_primary_care"  # P1 #15


def test_hospital_reading_prefers_the_radiology_group(engine, registry):
    """C2 (P1 #6): Tufts' readings come from the TINs radiology_groups.yaml lists for Tufts
    (042704683 ... ) before Tufts' own billing TIN 043400617."""
    r = _quote(engine, BCBS_HMO)
    ln = _line(r, TUFTS, "xray_reading")
    rad = set(registry.radiology_tins["tufts"])
    cited = {(p.source_id, p.row_id) for p in ln.cell.provs()}  # row_ref is shared (P1 #1)
    rows = [x for x in engine.store.rows if (x.source_id, x.row_id) in cited]
    assert rows and {x.tin for x in rows} <= rad
    assert (ln.cell.low, ln.cell.high) == (9.74, 18.79)


def test_e2e_cash(engine):
    r = _quote(engine, {"kind": "cash"})
    afc = _line(r, AFC, "xray")  # AFC's own posted self-pay page (sites.json cash_prices)
    assert afc.cell.kind == "money" and afc.cell.low == 150.0
    assert afc.cell.basis.value == "posted_self_pay"
    doctor = _line(r, TUFTS, "visit_doctor")
    assert doctor.cell.kind == "no_source" and doctor.doctor_fee.rung is None
    bilh = next(s for s in r.sites if s.site.site_id == "bilh_urgent_care_watertown")
    assert bilh.site.price_source_id is None  # P1 #9: shown, no line has a number
    # P9: its billing type is unknown, so it is priced as a hospital clinic: the facility side is
    # not loaded and the doctor's own self-pay fee has no public source
    assert bilh.site.billing_type == "unknown"
    assert {ln.cell.kind for ln in bilh.receipt.lines if ln.at == "this_site" and ln.cell} <= {
        "not_loaded", "no_source"}  # fmt: skip


def test_e2e_medicare(engine):
    r = _quote(engine, {"kind": "medicare"}, sites=[BWH])
    v = _line(r, BWH, "visit_doctor")
    assert (v.cell.low, v.doctor_fee.rung) == (75.54, 5)  # PFS RVU26D 99203, locality 01, facility
    assert v.cell.prov.row_ref == "cms_pfs_rvu26d:521ff0f4ecbf:13010:facility:01"
    assert v.cell.prov.method.value == "computed_fee_schedule" and v.cell.prov.payer_id is None
    assert _line(r, BWH, "xray_reading").cell.low == 9.75  # PFS 73030-26
    # the hospital's own Medicare row wins (Brigham 20610), else OPPS national unadjusted
    assert _line(r, BWH, "steroid_injection_facility").cell.low == 350.52
    x = _line(r, BWH, "xray_facility")
    assert (x.cell.low, x.cell.prov.source_id) == (88.91, "cms_opps_addb_2026q4")
    assert x.price_notes == ["price.national_unadjusted"]
    assert "medicare_advantage_is_insurance" in r.notices


def test_e2e_medicare_line_with_an_opps_facility_fee(engine):
    """C2: a hospital clinic visit's facility fee is OPPS G0463 ($136.02, APC 5012, national
    unadjusted), cited to its Addendum B row; the line names G0463 and says it is unadjusted."""
    r = _quote(engine, {"kind": "medicare"}, sites=[BWH])
    ln = _line(r, BWH, "visit_facility")
    assert ln.cell.kind == "money" and (ln.cell.low, ln.cell.high) == (136.02, 136.02)
    assert ln.cell.prov.row_ref == "cms_opps_addb_2026q4:2fc507a1fa67:14751:opps"
    assert ln.cell.basis.value == "fee_schedule" and ln.cell.prov.payer_id is None
    assert ln.codes == ["99203", "G0463"] and ln.price_notes == ["price.national_unadjusted"]
    assert ln.in_total
    sq = r.sites[0]
    assert "visit_facility" in sq.receipt.totals.likely.line_ids


def test_e2e_masshealth(engine):
    """C2: MassHealth 101 CMR 318 prices the reading (rung 4) and an office's global fee; the
    hospital facility fee (APAD) is not loaded. Tufts' only MassHealth rows for these codes are
    its 'MEDICAID LIMITED CMSP 100%' plan (MassHealth Limited / CMSP at 100% of charges), which
    is not the standard plan (engine.yaml masshealth_plan_exclude)."""
    r = _quote(engine, {"kind": "masshealth"}, path=None, codes=["73030", "73221"])
    assert r.care_path is None and r.copy_keys == []
    x = _line(r, TUFTS, "svc_73030_facility")
    assert x.cell.kind == "not_loaded" and "APAD" in x.cell.what
    ref = _line(r, TUFTS, "svc_73030_reading")
    assert (ref.doctor_fee.rung, ref.cell.low, ref.in_total) == (4, 6.75, True)
    assert ref.cell.prov.row_ref == "masshealth_318_20261001:25dae5fffe70:567:professional"
    office = _line(r, AFC, "svc_73030")
    assert (office.cell.low, office.doctor_fee.rung) == (27.31, 4)  # 318.00 global column
    tufts = next(s for s in r.sites if s.site.site_id == TUFTS)
    assert tufts.receipt.totals.missing == 2  # the two facility fees, nothing else
    assert "masshealth_aco_may_differ" in r.notices


# --------------------------------------------------------------------------- ladder (§2.4, D5, D6)


def test_afc_physical_therapy_is_not_summed_without_evidence(engine):
    """C3 R1 / R2 (was: the rung-6 multiple put AFC's PT evaluation in the total). AFC's registry
    entry says visit + imaging + lab; an insurer row for 97161 is not evidence AFC does PT, so
    the line is 'unknown' with the P6 reason and stays out of the total."""
    r = _quote(engine, BCBS_HMO)
    pt = _line(r, AFC, "physical_therapy")
    assert pt.availability == "unknown" and pt.availability_reason == "insurer_lists_rate"
    assert not pt.in_total and pt.estimate is None
    afc = next(s for s in r.sites if s.site.site_id == AFC)
    assert "physical_therapy" not in afc.receipt.totals.likely.line_ids
    reasons = {e.line_id: e.reason for e in afc.receipt.totals.excluded}
    assert reasons["physical_therapy"] == "availability_unknown"


def test_by_npi_when_prices_differ_else_range(engine):
    r = _quote(engine, BCBS_HMO)
    read = _line(r, TUFTS, "steroid_injection_doctor")
    prices = {(p.money.low, p.money.high) for p in read.doctor_fee.by_npi}
    assert len(prices) >= 2  # D6
    assert read.cell.low == min(p[0] for p in prices) and read.cell.high == max(
        p[1] for p in prices
    )


def test_range_cites_both_ends(engine):
    """P1 #2: a range's high end is cited too, and its file is in sources."""
    r = _quote(engine, BCBS_HMO)
    v = _line(r, TUFTS, "visit_doctor")
    assert v.cell.low < v.cell.high and v.cell.prov_high is not None
    assert v.cell.prov_high.source_id in r.sources
    assert v.cell.prov.row_id and v.cell.prov_high.row_id  # P1 #1: TiC rows carry row_id


def test_d20_conflict_when_hospital_file_and_tic_disagree(engine):
    """P1 #10 + D20: Tufts' 20610 facility rate is $283.01 in its own file and $60-71.09 in BCBS's
    TiC file: both shown, neither summed."""
    r = _quote(engine, BCBS_HMO)
    ln = _line(r, TUFTS, "steroid_injection_facility")
    assert ln.cell.kind == "conflict"
    assert (ln.cell.a.prov.source_kind.value, ln.cell.b.prov.source_kind.value) == (
        "hospital_mrf",
        "insurer_tic",
    )
    assert ln.cell.a.low == 283.01 and not ln.in_total


def test_tic_facility_rows_fill_a_hospital_file_gap(engine):
    """P1 #10: Tufts' file has no BCBS 99203 row; BCBS's TiC lists Tufts' facility rates."""
    r = _quote(engine, BCBS_HMO)
    ln = _line(r, TUFTS, "visit_facility")
    assert ln.cell.kind == "money" and ln.cell.prov.source_kind.value == "insurer_tic"
    assert (ln.cell.low, ln.cell.high) == (107.41, 315.61)


def test_cash_price_carries_no_payer(engine, store):
    """P1 #8: Tufts' tall CSV repeats its cash price on payer rows. The visit facility line's cash
    price and list price are read from an Aetna payer row, and still carry no payer."""
    r = _quote(engine, {"kind": "cash"})
    ln = _line(r, TUFTS, "visit_facility")
    for m in (ln.cell, ln.list_price):
        assert m.basis.value in ("discounted_cash", "gross") and m.prov.payer_id is None
        cited = [x for x in store.rows if store.sources[x.source_id].row_ref(x) == m.prov.row_ref]
        assert cited and all(x.row_kind == "payer_rate" and x.payer_id == "AETNA" for x in cited)


def test_network_registry_reads_both_hmo_blue_files(engine, registry):
    """P1 #3: payer/product -> every network file; a named network narrows it."""
    assert registry.networks_for("BCBS_MA", "HMO", None) == [
        "tic_bcbs_ma_hmo_blue_fi", "tic_bcbs_ma_hmo_blue_si", "tic_bcbs_ma_nemc_fi",
        "tic_bcbs_ma_nemc_si",
    ]  # fmt: skip
    assert registry.networks_for("BCBS_MA", "HMO", "hmo_blue") == [
        "tic_bcbs_ma_hmo_blue_fi",
        "tic_bcbs_ma_hmo_blue_si",
    ]
    narrow = dict(BCBS_HMO, network="hmo_blue")
    assert _quote(engine, narrow).sites


def test_tier_modifier_changes_the_line(engine):
    """P1 #19: the shown tier follows the path's tier_modifiers for the answers."""
    from app.care_paths.loader import load_paths

    path = load_paths()["shoulder_chronic_clicking_v1"]
    mod = path.tier_modifiers[0]
    r = _quote(engine, BCBS_HMO, answers=mod.when)
    lines = [ln for s in r.sites for ln in s.receipt.lines if ln.step_id == mod.step]
    assert lines and {ln.likelihood for ln in lines} == {mod.tier}


def test_codes_outside_the_etl_list_are_not_loaded(engine, store, registry):
    """A code the ETL does not extract is not_loaded, never "not published". (A5 now derives the
    ETL list from the care paths, R9, so every path code is loaded; drop one to check.)"""
    from dataclasses import replace as dc_replace

    bare = Engine(dc_replace(store, codes=store.codes - {"23350"}), registry)
    ln = _line(_quote(bare, BCBS_HMO), MA, "mr_arthrogram_23350_doctor")
    assert ln.cell.kind == "not_loaded"


def test_visit_facility_fee_g0463_is_not_loaded_without_opps(engine, store, registry):
    """P9: without an OPPS file, G0463 is not_loaded, never a silent 0."""
    from dataclasses import replace as dc_replace

    bare = dc_replace(store, rows=[r for r in store.rows if r.source_kind != "medicare_opps"],
                      sources={k: m for k, m in store.sources.items()
                               if m.source_kind != "medicare_opps"})  # fmt: skip
    r = _quote(Engine(bare, registry), {"kind": "medicare"}, sites=[BWH])
    ln = _line(r, BWH, "visit_facility")
    # C4c (Austin: no "facility fee" words on the surface): the gap's text is plain; the code
    # the number was looked up under stays on the line
    assert ln.cell.kind == "not_loaded" and "hospital" in ln.cell.what
    assert "facility fee" not in ln.cell.what and "G0463" not in ln.cell.what


def test_freshness_is_computed_per_request(engine):
    later = date(2026, 12, 1)
    r = _quote(engine, BCBS_HMO, as_of=later)
    monthly = [
        s for s in r.sources.values() if s.source_kind.value in ("hospital_mrf", "insurer_tic")
    ]
    assert monthly and all(s.freshness.stale_on_our_side for s in monthly)
    assert "stale_on_our_side_sources" in r.notices
    assert any(
        sq.receipt.totals.likely.includes_stale_source for sq in r.sites if sq.receipt.totals.likely
    )
    again = _quote(engine, BCBS_HMO)
    assert "stale_on_our_side_sources" not in again.notices


def test_unknown_payer_site_or_path_is_a_value_error(engine):
    with pytest.raises(ValueError, match="unknown payer"):
        _quote(engine, {**BCBS_HMO, "payer_id": "NOPE"})
    with pytest.raises(ValueError, match="unknown or unquotable site"):
        _quote(engine, BCBS_HMO, sites=["nowhere"])


def test_manual_pick_and_assistant_pick(engine):
    r = _quote(engine, BCBS_HMO, path=None, codes=["73030"])
    assert all(ln.tier_basis == "picked" for s in r.sites for ln in s.receipt.lines)
    assert all(st.step_id is None and st.key == "73030" for s in r.sites for st in s.steps)
    req = QuoteRequest.model_validate({
        "payment": BCBS_HMO, "care_path_id": None, "answers": {}, "service_codes": ["73030"],
        "picked_by": "assistant", "site_ids": None,
    })  # fmt: skip
    a = engine.quote(req, AS_OF)
    assert all(ln.ai_suggested and not ln.in_total for s in a.sites if s.receipt
               for ln in s.receipt.lines)  # fmt: skip
    assert any(s.receipt for s in a.sites)


def test_elsewhere_suggests_cheaper_sites_for_a_gap(engine):
    r = _quote(engine, BCBS_HMO)
    ln = _line(r, "franciscan_childrens", "xray_facility")  # no BCBS row in its own file
    assert ln.cell.kind == "not_published"
    assert ln.elsewhere and ln.elsewhere[0].cell.kind == "money"
    lows = [e.cell.low for e in ln.elsewhere]
    assert lows == sorted(lows)


def test_sites_yaml_path_from_env(tmp_path, monkeypatch):
    """P1 #12 / brief C7: the registry path comes from env, validated with the Site contract."""
    from app.quote.registry import load_sites

    doc = fixture_doc("sites")
    doc["sites"] = doc["sites"][:1]
    import yaml

    p = tmp_path / "sites.yaml"
    p.write_text(yaml.safe_dump(doc))
    monkeypatch.setenv("CARECOST_SITES_PATH", str(p))
    version, sites = load_sites()
    assert list(sites) == ["afc_watertown"]
    doc["sites"][0]["tins"] = ["04-3026897"]
    p.write_text(yaml.safe_dump(doc))
    with pytest.raises(Exception, match="9 digits"):
        load_sites()
