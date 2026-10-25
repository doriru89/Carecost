"""A7: ED visit levels 99281-99285 as a non-path reference code set; AFC's posted visit price."""

from __future__ import annotations

import yaml

from app.etl import path_codes
from app.etl.config import CONFIG_DIR, load_codes
from app.etl.tic.networks import target_codes
from app.quote.registry import Registry
from tests.quote.conftest import engine, registry, store  # noqa: F401 (pytest fixtures)

ED = {"99281", "99282", "99283", "99284", "99285"}


def test_ed_codes_are_extracted_but_in_no_domain() -> None:
    codes = load_codes()
    assert ED <= codes.codes  # hospital normalize + pack
    assert ED <= target_codes()  # TiC filter (tic extend)
    for c in ED:
        assert codes.domains_for(c) == []  # no site area admits them: never ranked
        assert codes.group_for(c) == "reference"
        assert codes.description(c).startswith("Emergency department visit, level")
    assert codes.group_for("99213").startswith("ortho")


def test_reference_codes_keep_codes_check_green_and_are_not_path_codes() -> None:
    assert path_codes.check() == []
    gen = yaml.safe_load((CONFIG_DIR / "path_codes.yaml").read_text())["codes"]
    assert not ED & set(gen)


def test_no_site_area_admits_a_reference_code() -> None:
    reg = Registry.load()
    for c in ED:
        assert reg.code_areas(c) == set()
    assert reg.code_areas("99213")  # a domain code still maps to areas


def test_afc_self_pay_visit_has_the_visit_codes() -> None:
    reg = Registry.load()
    afc = reg.sites["afc_watertown"]
    p = next(x for x in afc.cash_prices if x.item_id == "evaluation_consultation")
    assert p.amount == 179.0 and p.includes_provider_fee is True
    assert set(p.codes) == {"99202", "99203", "99204", "99205", "99212", "99213", "99214", "99215"}
    assert "afcurgentcare.com/watertown/resources/self-pay" in p.source_url


def _afc_prices() -> dict[str, object]:
    return {p.item_id: p for p in Registry.load().sites["afc_watertown"].cash_prices}


def test_afc_lab_and_xray_cash_prices_map_only_clear_codes() -> None:
    p = _afc_prices()
    assert (p["pregnancy_test_rapid"].amount, p["pregnancy_test_rapid"].codes) == (30.0, ["81025"])
    assert (p["cbc_diff_plt"].amount, p["cbc_diff_plt"].codes) == (60.0, ["85025"])
    assert (p["cmp"].amount, p["cmp"].codes) == (60.0, ["80053"])
    # urinalysis: 81002 vs 81003 (rapid) / 81001 vs 81003 (send-out) is not on the page
    assert p["urinalysis_rapid"].codes == [] and p["urinalysis_send_out"].codes == []
    # X-rays by view count; a code whose descriptor spans two of the page's prices stays out
    assert [(k, p[k].amount) for k in ("xray_1_view", "xray_2_views", "xray_3_views")] == [
        ("xray_1_view", 80.0), ("xray_2_views", 150.0), ("xray_3_views", 225.0)]  # fmt: skip
    assert set(p["xray_2_views"].codes) == {"73030", "73600"}
    assert set(p["xray_3_views"].codes) == {"73562", "73610"}
    mapped = {c for x in p.values() for c in x.codes}
    assert not mapped & {"73560", "72100", "73564", "81003"}
    for x in p.values():
        assert "afcurgentcare.com/watertown/resources/self-pay" in x.source_url


def test_afc_curated_prices_agree_with_the_page_snapshot() -> None:
    """Every curated AFC cash price is a row of data/sites/posted/afc_watertown.json."""
    import json

    from app.sites.posted_prices import diff

    snap = json.loads((CONFIG_DIR.parent / "sites" / "posted" / "afc_watertown.json").read_text())
    cur = [x.model_dump() for x in _afc_prices().values()]
    assert diff(snap["items"], cur) == []


def test_afc_self_pay_stomach_quote_prices_the_posted_labs(engine) -> None:  # noqa: F811
    from app.quote.contracts import QuoteRequest
    from tests.quote.conftest import AS_OF

    body = {"payment": {"kind": "cash"}, "care_path_id": "stomach_ache_v1", "answers": {},
            "service_codes": [], "picked_by": "person", "site_ids": ["afc_watertown"]}  # fmt: skip
    r = engine.quote(QuoteRequest.model_validate(body), AS_OF)
    s = next(x for x in r.sites if x.site.site_id == "afc_watertown")
    lines = {ln.line_id: ln.cell for ln in s.receipt.lines}
    got = {k: (lines[k].kind, getattr(lines[k], "low", None))
           for k in ("pregnancy_test", "blood_tests", "urine_test")}  # fmt: skip
    assert got == {"pregnancy_test": ("money", 30.0), "blood_tests": ("money", 60.0),
                   "urine_test": ("not_published", None)}  # fmt: skip
