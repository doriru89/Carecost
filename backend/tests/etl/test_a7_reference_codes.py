"""A7: ED visit levels 99281-99285 as a non-path reference code set; AFC's posted visit price."""

from __future__ import annotations

import yaml

from app.etl import path_codes
from app.etl.config import CONFIG_DIR, load_codes
from app.etl.tic.networks import target_codes
from app.quote.registry import Registry

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
