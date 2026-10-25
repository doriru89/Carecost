"""Stream C2: A3's fee schedules + 208-site registry wired into the engine.

Site choice (near / max_sites / children_only), fee-schedule numbers (no payer, place of
service, locality), the I7 `missing` definition, offered evidence, data-quality notices and the
catalog's per-path names. Runs on the committed extract and data/sites/sites.yaml."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.etl.contracts import Method, Money, PriceBasis, Provenance, SourceKind
from app.quote.catalog import build_catalog, path_service_names, path_services
from app.quote.contracts import QuoteRequest, QuoteResponse
from app.quote.engine import Engine, _km
from app.quote.fixtures_gen import KEY_SITES, NEAR
from tests.quote.conftest import AS_OF, fixture_doc

SHOULDER = "shoulder_chronic_clicking_v1"
BCBS_HMO = {"kind": "insurance", "payer_id": "BCBS_MA", "product": "HMO", "network": None}


def _req(**kw) -> QuoteRequest:
    body = {"payment": BCBS_HMO, "care_path_id": SHOULDER, "answers": {}, "service_codes": [],
            "picked_by": "person", "site_ids": None}  # fmt: skip
    body.update(kw)
    return QuoteRequest.model_validate(body)


# --------------------------------------------------------------------------- site choice


def test_near_quotes_the_closest_max_sites(engine, registry):
    r = engine.quote(_req(near=NEAR, max_sites=5), AS_OF)
    assert len(r.sites) == 5
    got = {sq.site.site_id for sq in r.sites}
    areas = registry.path_areas(registry.paths[SHOULDER])
    eligible = [s for s in registry.sites.values() if s.listing_status != "registry_only"
                and not s.children_only and registry.area_ok(s, areas)]  # fmt: skip

    class P:
        lat, lon = NEAR["lat"], NEAR["lon"]

    want = {s.id for s in sorted(eligible, key=lambda s: (_km(P, s), s.id))[:5]}
    assert got == want


def test_default_max_sites_is_12_and_50_is_the_ceiling():
    assert _req().max_sites == 12 and _req().near is None
    with pytest.raises(ValidationError):
        _req(max_sites=51)
    with pytest.raises(ValidationError):
        _req(max_sites=0)


def test_no_point_returns_the_best_ranked_sites(engine):
    """Without `near`, every eligible site is priced and the best max_sites (I7) come back,
    ranked again inside that set."""
    small = engine.quote(_req(site_ids=KEY_SITES, max_sites=3), AS_OF)
    full = engine.quote(_req(site_ids=KEY_SITES, max_sites=6), AS_OF)
    assert len(small.sites) == 3
    assert [s.site.site_id for s in small.sites] == [s.site.site_id for s in full.sites[:3]]


def test_children_only_sites_only_when_named(engine, registry):
    """D27: a children-only site is never ranked for an adult path unless the request names it."""
    kids = sorted(s.id for s in registry.sites.values() if s.children_only)
    assert len(kids) == 10
    r = engine.quote(_req(near={"lat": 42.3376, "lon": -71.1062}, max_sites=50), AS_OF)  # Longwood
    assert not {sq.site.site_id for sq in r.sites} & set(kids)
    named = engine.quote(_req(site_ids=["franciscan_childrens"]), AS_OF)
    assert [sq.site.site_id for sq in named.sites] == ["franciscan_childrens"]
    assert named.sites[0].site.children_only is True


# --------------------------------------------------------------------------- fee schedules


def _fs_prov(**kw) -> Provenance:
    base = dict(source_id="cms_pfs_rvu26d", source_kind=SourceKind.medicare_pfs,
                source_file="PPRRVU2026_Oct_nonQPP.csv", source_sha256="5" * 64,
                source_date=None, method=Method.computed_fee_schedule,
                row_ref="cms_pfs_rvu26d:555555555555:13015:non_facility:01")  # fmt: skip
    base.update(kw)
    return Provenance(**base)


def test_a_fee_schedule_number_carries_no_payer():
    """Mutation target 1: Money rejects a fee-schedule number with a payer."""
    Money.point(106.10, basis=PriceBasis.fee_schedule, prov=_fs_prov())
    with pytest.raises(ValidationError, match="carries no payer"):
        Money.point(106.10, basis=PriceBasis.fee_schedule, prov=_fs_prov(payer_id="MEDICARE"))
    with pytest.raises(ValidationError, match="is basis fee_schedule"):
        Money.point(106.10, basis=PriceBasis.negotiated, prov=_fs_prov())


def test_every_fee_schedule_number_in_the_fixtures_has_no_payer():
    for name in ("quote_medicare_shoulder", "quote_masshealth_manual", "quote_bcbs_hmo_shoulder"):
        r = QuoteResponse.model_validate(fixture_doc(name))
        seen = 0
        for sq in r.sites:
            for ln in sq.receipt.lines:
                c = ln.cell
                if isinstance(c, Money) and c.prov.source_kind.value in (
                    "medicare_pfs", "medicare_opps", "medicare_asc", "masshealth_fs"
                ):  # fmt: skip
                    seen += 1
                    assert c.basis.value in ("fee_schedule", "estimate")
                    assert all(p.payer_id is None for p in c.provs())
        assert seen, name


def test_gov_reader_rows_carry_place_of_service():
    from app.etl.contracts import RateRow, SourceKind
    from app.etl.gov.common import finish, make_row

    common = dict(source_id="cms_pfs_rvu26d", kind=SourceKind.medicare_pfs, sha="5" * 64,
                  source_file="PPRRVU2026_Oct_nonQPP.csv", source_date=AS_OF,
                  entity_id="medicare_ma_01", payer_id="MEDICARE", payer_raw="Medicare PFS",
                  line=13015, code="99213", modifiers="", description="office visit",
                  amount=106.10)  # fmt: skip
    rows = finish([make_row(variant="non_facility", **common),
                   make_row(variant="global", **{**common, "line": 1})])  # fmt: skip
    assert [r["place_of_service"] for r in rows] == ["non_facility", None]
    cell = RateRow(**rows[0]).to_cell()
    assert cell.basis == PriceBasis.fee_schedule and cell.prov.payer_id is None
    assert cell.prov.method == Method.computed_fee_schedule


def test_pfs_locality_follows_the_site_county(engine, registry):
    """26LOCCO.csv: 01 = Middlesex / Norfolk / Suffolk; Lynn, Saugus, Brockton are 99."""
    lynn = next(s for s in registry.sites.values() if s.address.city == "Lynn")
    cam = next(s for s in registry.sites.values() if s.address.city == "Cambridge")
    assert registry.medicare_locality(lynn) == "99" and registry.medicare_locality(cam) == "01"
    assert "medicare_ma_99" in engine._areas(lynn) and "medicare_ma_01" not in engine._areas(lynn)


# --------------------------------------------------------------------------- I7 missing


def test_missing_counts_expected_lines_without_a_number_that_counts(engine):
    """`missing` = certain/likely, non-AI lines whose number does not count in the total (a gap,
    a conflict, a repeating unit, or a rung-7 reference) + steps another site lists. A rung-7
    reference line therefore counts as missing; a rung-4 MassHealth reading does not."""
    from app.quote.contracts import missing_for

    r = engine.quote(_req(payment={"kind": "masshealth"}, care_path_id=None,
                          service_codes=["73030", "73221"], site_ids=KEY_SITES), AS_OF)  # fmt: skip
    tufts = next(s for s in r.sites if s.site.site_id == "tufts_medical_center")
    gaps = [ln.line_id for ln in tufts.receipt.lines if not ln.in_total]
    assert gaps == ["svc_73030_facility", "svc_73221_facility"]
    assert tufts.receipt.totals.missing == 2 and missing_for(tufts, set()) == 2
    # make one reading a number that does not count (a repeating unit): missing goes up by one
    doc = copy.deepcopy(r.model_dump(mode="json"))
    sq = next(s for s in doc["sites"] if s["site"]["site_id"] == "tufts_medical_center")
    ln = next(x for x in sq["receipt"]["lines"] if x["line_id"] == "svc_73030_reading")
    ln["in_total"] = False
    ln["unit"] = "per_15_minutes"
    t = sq["receipt"]["totals"]
    t["excluded"].append({"line_id": ln["line_id"], "reason": "repeats"})
    t["likely"]["line_ids"].remove(ln["line_id"])
    t["likely"]["low"] = round(t["likely"]["low"] - ln["cell"]["low"], 2)
    t["likely"]["high"] = round(t["likely"]["high"] - ln["cell"]["high"], 2)
    with pytest.raises(ValidationError, match="totals.missing must be 3"):
        QuoteResponse.model_validate(doc)


# --------------------------------------------------------------------------- offered + notices


def test_availability_needs_positive_evidence(engine):
    r = engine.quote(_req(site_ids=KEY_SITES), AS_OF)
    afc = next(s for s in r.sites if s.site.site_id == "afc_watertown")
    by = {ln.line_id: ln.availability for ln in afc.receipt.lines}
    assert by["xray"] == "offered"  # posted self-pay price + TiC rows
    assert by["mr_arthrogram_23350"] == "unknown"  # no row, no offered entry
    assert "not_offered" not in by.values()  # absence of evidence is never "not offered"


def test_data_quality_notice_on_the_site_priced_by_that_file(engine, registry):
    site = registry.sites["beth_israel_deaconess_medical_center"] if (
        "beth_israel_deaconess_medical_center" in registry.sites
    ) else next(s for s in registry.sites.values() if s.hospital_entity_id == "bidmc")  # fmt: skip
    summary = engine._summary(site, "bidmc_mrf", "price_file")
    assert [n["id"] for n in summary["data_notices"]] == ["bidmc_content_changed_date_unchanged"]
    assert engine._summary(site, "tufts_mrf", "price_file")["data_notices"] == []


def test_census_linked_tins_count_only_rows_that_name_the_site(engine, registry, store):
    site = next(s for s in registry.sites.values() if s.census_id
                and store.census_tins.get(s.census_id, frozenset()) - set(registry.site_tins(s)))  # fmt: skip
    own, linked = engine._site_tins(site)
    assert linked and not set(linked) & set(own)
    for r in engine._site_tic(engine._context(_req(), AS_OF), site, sorted(store.codes), "",
                              frozenset({"11", "22", "19", "20"}), "professional", any_pos=True):  # fmt: skip
        assert r.tin in own or r.names_site(site.census_id)


# --------------------------------------------------------------------------- catalog names


def test_a_service_under_a_path_uses_that_paths_step_name(registry):
    """D2: svc_97161 is in the ankle and the shoulder paths; under the shoulder path it must not
    read 'Guided exercise program for the ankle'; the global list uses a neutral name."""
    cat = build_catalog(registry)
    names = path_service_names(registry)
    pt = next(s for s in cat.services if s.service_id == "svc_97161")
    assert len(pt.care_paths) > 1
    for pid in pt.care_paths:
        mine = next(s for s in path_services(cat, names, pid) if s["service_id"] == "svc_97161")
        step = next(st for st in registry.paths[pid].steps
                    if any(c.role == "primary" and c.code == "97161" for c in st.cpts))  # fmt: skip
        assert mine["plain_name"] == step.plain.name
    shoulder = [s for s in path_services(cat, names, SHOULDER) if s["service_id"] == "svc_97161"]
    assert "ankle" not in shoulder[0]["plain_name"].lower()
    assert pt.plain_name == registry.describe("97161")  # neutral in the global list


def test_engine_does_not_mutate_the_store(store, registry):
    before = len(store.rows)
    Engine(replace(store), registry).quote(_req(near=NEAR), AS_OF)
    assert len(store.rows) == before
