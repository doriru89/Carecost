"""sources.d/tic.yaml + tic_networks.yaml + tic_visit_codes.yaml + tic_provider_targets.csv."""

from __future__ import annotations

import csv

from app.etl import fetch
from app.etl.config import CONFIG_DIR, load_sources
from app.etl.tic.discover import month_url, pick, toc_urls
from app.etl.tic.networks import get_network, load_networks, target_codes
from app.etl.tic.targets import load_targets


def test_every_network_resolves_and_is_allowlisted():
    nets = load_networks()
    allowed = load_sources().fetch.allowed_domains
    assert len(nets) >= 30
    for n in nets:
        assert fetch.url_allowed(n.url, allowed), n.source_id
        assert n.payer_id and n.toc and n.match and n.why
    payers = {n.payer_id for n in nets}
    assert {"BCBS_MA", "HARVARD_PILGRIM", "MGB_HP", "AETNA", "UHC", "TUFTS_HP"} <= payers


def test_registered_networks_match_sources_and_zip_ones_are_not_registered():
    sources = load_sources()
    ids = {s.source_id for s in sources.sources}
    for n in load_networks():
        assert (n.source_id in ids) == n.registered
        if not n.registered:
            assert n.container == "zip"  # config.py's tic_in_network rules allow gzip / plain only
    tic_sources = [s for s in sources.sources if s.format == "tic_in_network"]
    assert {s.source_id for s in tic_sources} == {
        n.source_id for n in load_networks() if n.registered
    }


def test_payer_ids_exist_in_alias_table():
    import yaml

    payers = yaml.safe_load((CONFIG_DIR / "payer_aliases.yaml").read_text())["payers"]
    for n in load_networks():
        assert n.payer_id in payers


def test_target_codes_include_codes_yaml_and_visit_codes():
    codes = target_codes()
    for c in ("00811", "00812", "00813", "99051", "S9083", "S9088", "99213", "73030"):
        assert c in codes


def test_provider_targets_have_afc_franchisees_and_census_npis():
    t = load_targets()
    for tin in ("272343207", "460903626", "454148303", "472237031", "460782127", "934880533",
                "454478857", "463251869", "813416211"):  # fmt: skip
        assert tin in t.tins
    rows = list(csv.DictReader((CONFIG_DIR / "tic_provider_targets.csv").open()))
    assert any(r["kind"] == "npi" for r in rows) and len(t.npis) > 400
    assert all(len(v) in (9, 10) for v in t.tins)  # EIN or npi-type TIN


def test_discovery_month_rewrite_and_third_party_rewrite():
    u = "https://transparency-in-coverage.bluecrossma.com/2026-10-01_Blue-Cross-and-Blue-Shield-of-Massachusetts-Inc_index.json"
    assert "/2026-11-01_Blue" in month_url(u, "2026-11")
    f = "https://fallon.sapphiremrfhub.com/tocs/202610/2026-10-01_fallon-health_index.json"
    assert (
        month_url(f, "2026-11")
        == "https://fallon.sapphiremrfhub.com/tocs/202611/2026-11-01_fallon-health_index.json"
    )
    net = get_network("tic_bcbs_ma_hmo_blue_si")
    toc = {"reporting_structure": [{"in_network_files": [{"location":
        "https://transparency-in-coverage.bluecrossma.com/2026-11-01_Blue-Cross-and-Blue-Shield-of-Massachusetts-Inc_HMO-Blue-Self-Insured_Third-Party-in-network-rates.json.gz"}]}]}  # fmt: skip
    d = pick(net, toc_urls(toc, u), load_sources().fetch.allowed_domains)
    assert d.status == "ok" and d.url and "_Third-Party" not in d.url and "2026-11-01" in d.url


def test_discovery_reads_aetna_and_uhc_listings():
    aetna = {
        "files": [
            {
                "fileSchema": "IN_NETWORK_RATES",
                "filePath": "2026-11-05/inNetworkRates/2026-11-05_pl-3j4-hr23_Aetna-Life-Insurance-Company.json.gz",
            }
        ]
    }
    base = "https://mrf.healthsparq.com/aetnacvs-egress.nophi.kyruushsq.com/prd/mrf/AETNACVS_I/ALICFI/latest_metadata.json"
    d = pick(
        get_network("tic_aetna_ppo_pl_3j4"),
        toc_urls(aetna, base),
        load_sources().fetch.allowed_domains,
    )
    assert d.status == "ok" and d.url.endswith(
        "2026-11-05_pl-3j4-hr23_Aetna-Life-Insurance-Company.json.gz"
    )
    uhc = {
        "blobs": [
            {
                "name": "2026-11-01_UnitedHealthcare-of-New-England--Inc-_Insurer_Choice-HMO_560_in-network-rates.json.gz",
                "downloadUrl": "https://transparency-in-coverage.uhc.com/api/v1/uhc/blobs/download/2026-11-01/2026-11-01_UnitedHealthcare-of-New-England--Inc-_Insurer_Choice-HMO_560_in-network-rates.json.gz",
            }
        ]
    }
    d = pick(
        get_network("tic_uhc_choice_hmo_560"),
        toc_urls(uhc, ""),
        load_sources().fetch.allowed_domains,
    )
    assert d.status == "ok" and "2026-11-01" in d.url
