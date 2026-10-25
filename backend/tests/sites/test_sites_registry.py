"""data/sites/sites.yaml + to_verify.yaml (A3; D14, D27, P12, P1 problems 4 / 14)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from app.etl.config import load_sources
from app.registries import all_hospitals
from app.sites import build
from app.sites.contracts import SitesFile, ToVerifyFile, normalize_tin

SITES = build.SITES_DIR


def _load(name: str) -> SitesFile:
    return SitesFile.model_validate(yaml.safe_load((SITES / name).read_text()))


@pytest.fixture(scope="module")
def sites() -> SitesFile:
    return _load("sites.yaml")


@pytest.fixture(scope="module")
def todo() -> SitesFile:
    return ToVerifyFile.model_validate(yaml.safe_load((SITES / "to_verify.yaml").read_text()))


@pytest.fixture(scope="module")
def census() -> dict[str, dict[str, str]]:
    return {r["site_id"]: r for r in csv.DictReader(build.DEFAULT_CENSUS.open())}


def test_committed_files_are_what_the_builder_writes():
    assert build.main(["--check"]) == 0


def test_every_entry_is_a_valid_site(sites, todo):
    assert len(sites.sites) > 150 and len(todo.sites) > 50
    ids = [s.id for s in sites.sites] + [s.id for s in todo.sites]
    assert len(ids) == len(set(ids))


def test_registry_only_never_lands_in_sites_yaml(sites, todo):
    assert all(s.listing_status != "registry_only" for s in sites.sites)
    assert all(s.listing_status == "registry_only" for s in todo.sites)


def test_restricted_and_closed_rows_are_left_out(sites, todo, census):
    for s in sites.sites + todo.sites:
        if s.census_id:
            flags = census[s.census_id]["flags"]
            assert "restricted_" not in flags
            assert not any(x in flags for x in ("closed", "terminated", "remove"))


def test_active_multi_source_rows_are_all_quotable(sites, census):
    """Seeded from the census's active rows: every active, unrestricted row with >=2 registries
    or a web check and coordinates is in sites.yaml."""
    have = {s.census_id for s in sites.sites}
    want = {
        cid for cid, r in census.items()
        if build.is_active(r) and "restricted_" not in r["flags"] and r["lat"]
        and (r["src_web"] == "1" or build.n_sources(r) >= 2)
    }  # fmt: skip
    assert want == have - {None}


def test_every_hospital_price_file_has_a_site(sites):
    by_entity = {s.hospital_entity_id for s in sites.sites if s.census_id is None}
    assert by_entity == {s.entity_id for s in load_sources().rate_row_sources}
    hospitals = all_hospitals()
    for s in sites.sites:
        if s.hospital_entity_id:
            assert s.hospital_entity_id in hospitals


def test_p1_slice_sites_keep_their_ids(sites):
    ids = {s.id for s in sites.sites}
    assert {"afc_watertown", "bilh_urgent_care_watertown", "mount_auburn_hospital",
            "brigham_and_womens_hospital", "franciscan_childrens", "tufts_medical_center"} <= ids  # fmt: skip
    afc = next(s for s in sites.sites if s.id == "afc_watertown")
    assert afc.census_id == "GB0378" and afc.tins == ["460903626"] and afc.ownership == "franchise"
    assert any(o.service == "xray" and o.evidence == "posted_price" for o in afc.offered)


def test_tins_are_digits_and_sourced(sites):
    n = 0
    for s in sites.sites:
        if s.tins or s.tin_npis:
            assert s.tins_source
            n += 1
    assert n > 150
    mta = next(s for s in sites.sites if s.id == "mount_auburn_hospital")
    assert "043026897" in mta.tins  # P1 problem 4: TiC prints it as 04-3026897


@pytest.mark.parametrize("raw", ["04-3026897", "043026897", " 04 3026897 "])
def test_normalize_tin(raw):
    assert normalize_tin(raw) == "043026897"


@pytest.mark.parametrize("raw", ["4-3026897", "1234567890", "04-302689A", ""])
def test_normalize_tin_rejects(raw):
    with pytest.raises(ValueError):
        normalize_tin(raw)


def test_ownership_values_d27(sites):
    own = {s.ownership for s in sites.sites}
    assert {"payer_owned", "community_health_center", "franchise"} <= own
    atrius = [s for s in sites.sites if s.ownership_detail and "Atrius" in s.ownership_detail]
    assert atrius and all(s.ownership == "payer_owned" for s in atrius)


def test_pediatric_sites_are_children_only(sites):
    kids = [s for s in sites.sites if s.children_only]
    assert any("PM PEDIATRICS" in s.name.upper() for s in kids)
    assert all(not s.name.upper().startswith("ADULT") for s in kids)
    assert next(
        s for s in sites.sites if s.hospital_entity_id == "childrens" and s.census_id is None
    ).children_only


def test_asc_and_hospital_billing_rules(sites):
    for s in sites.sites:
        if s.site_type == "hospital_outpatient":
            assert s.billing_type != "office_visit"
        if s.billing_type == "asc":
            assert s.site_type == "ambulatory_surgery_center"


def test_census_snapshot_is_the_research_file():
    rows = list(csv.DictReader(build.DEFAULT_CENSUS.open()))
    assert len(rows) == 398
    assert sum(build.is_active(r) for r in rows) == 271


def test_hospital_addresses_cover_every_source():
    addrs = yaml.safe_load((SITES / "hospital_addresses.yaml").read_text())["hospitals"]
    assert set(addrs) == {s.entity_id for s in load_sources().rate_row_sources}
    assert Path(build.DEFAULT_CENSUS).name.startswith("clinic-census-")
