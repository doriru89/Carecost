"""Every source format the wave-2 streams register validates as a sources.d fragment, and the
hospital-MRF rate_row pipeline ignores the ones it does not read."""

from __future__ import annotations

import typing
from pathlib import Path

import pytest
import yaml

from app.etl.config import (
    CONFIG_DIR,
    MRF_FORMATS,
    NPPES_MEMBERS,
    ReferenceKind,
    SourceFormat,
    SourceSpec,
    load_sources,
)
from app.etl.contracts import SourceKind

BASE = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())

# One minimal, realistic fragment entry per new format (the MRF formats are covered by sources.yaml).
NEW_FORMATS: dict[str, dict] = {
    "tic_table_of_contents": {
        "source_id": "bcbs_ma_tic_toc",
        "kind": "insurer_tic",
        "format": "tic_table_of_contents",
        "payer_id": "BCBS_MA",
        "url": "https://transparency-in-coverage.bluecrossma.com/index.json",
    },
    "tic_in_network": {
        "source_id": "bcbs_ma_tic_hmo",
        "kind": "insurer_tic",
        "format": "tic_in_network",
        "payer_id": "BCBS_MA",
        "container": "gzip",
        "access": "http_range",
        "release": "2026-11",
        "url": "https://transparency-in-coverage.bluecrossma.com/hmo_in-network-rates.json.gz",
        "discovery": "https://transparency-in-coverage.bluecrossma.com/index.json",
    },
    "nppes_monthly": {
        "source_id": "nppes_monthly",
        "kind": "provider_registry",
        "format": "nppes_monthly",
        "container": "zip",
        "url": "https://download.cms.gov/nppes/NPPES_Data_Dissemination_October_2026.zip",
        "members": {
            "main": "npidata_pfile_*.csv",
            "pl_pfile": "pl_pfile_*.csv",
            "othername_pfile": "othername_pfile_*.csv",
            "endpoint_pfile": "endpoint_pfile_*.csv",
        },
    },
    "dph_xlsx": {
        "source_id": "ma_dph_clinics",
        "kind": "facility_registry",
        "format": "dph_xlsx",
        "url": "https://www.mass.gov/doc/licensed-clinics/download",
    },
    "fhir_provider_directory": {
        "source_id": "bcbs_ma_fhir_directory",
        "kind": "provider_directory",
        "format": "fhir_provider_directory",
        "payer_id": "BCBS_MA",
        "access": "paged_api",
        "filters": {"address-state": "MA"},
        "url": "https://fhir.example-payer.com/providerdirectory/Practitioner",
    },
    "cms_dataset_csv": {
        "source_id": "cms_reassignment",
        "kind": "billing_relationship",
        "format": "cms_dataset_csv",
        "url": "https://data.cms.gov/provider-characteristics/reassignment.csv",
    },
    "cms_dataset_api": {
        "source_id": "cms_doctors_clinicians",
        "kind": "clinician_directory",
        "format": "cms_dataset_api",
        "access": "paged_api",
        "filters": {"state": "MA"},
        "url": "https://data.cms.gov/provider-data/api/1/datastore/query/mj5m-pzi6/0",
    },
    "cms_pfs_rvu": {
        "source_id": "cms_pfs_rvu26a",
        "kind": "medicare_pfs",
        "format": "cms_pfs_rvu",
        "container": "zip",
        "release": "RVU26A",
        "url": "https://www.cms.gov/files/zip/rvu26a.zip",
    },
    "cms_pfs_anes": {
        "source_id": "cms_pfs_anes2026",
        "kind": "medicare_pfs",
        "format": "cms_pfs_anes",
        "media": "xlsx",
        "url": "https://www.cms.gov/files/document/anes2026.xlsx",
    },
    "cms_opps_addendum": {
        "source_id": "cms_opps_addendum_b",
        "kind": "medicare_opps",
        "format": "cms_opps_addendum",
        "container": "zip",
        "release": "2026-10",
        "url": "https://www.cms.gov/files/zip/addendum-b.zip",
    },
    "cms_asc_addendum": {
        "source_id": "cms_asc_addendum_aa",
        "kind": "medicare_asc",
        "format": "cms_asc_addendum",
        "media": "xlsx",
        "url": "https://www.cms.gov/files/document/asc-addendum-aa.xlsx",
    },
    "masshealth_fee_schedule": {
        "source_id": "masshealth_101cmr317",
        "kind": "masshealth_fs",
        "format": "masshealth_fee_schedule",
        "media": "pdf",
        "url": "https://www.mass.gov/doc/101-cmr-317-medicine/download",
    },
    "html_price_page": {
        "source_id": "afc_watertown_self_pay",
        "kind": "clinic_posted",
        "format": "html_price_page",
        "entity_id": "afc_watertown",
        "url": "https://www.afcurgentcare.com/watertown/resources/self-pay",
    },
}


def _cfg(tmp_path: Path, sources: list[dict], domains: list[str] | None = None) -> Path:
    cfg = tmp_path / "etl"
    (cfg / "sources.d").mkdir(parents=True)
    (cfg / "sources.yaml").write_text(yaml.safe_dump(BASE))
    frag = {"version": 1, "allowed_domains": domains or [], "sources": sources}
    (cfg / "sources.d" / "stream.yaml").write_text(yaml.safe_dump(frag))
    return cfg


def test_every_format_has_a_fragment_test():
    assert set(typing.get_args(SourceFormat)) - MRF_FORMATS == set(NEW_FORMATS)


@pytest.mark.parametrize("fmt", sorted(NEW_FORMATS))
def test_minimal_fragment_validates(tmp_path, fmt):
    entry = NEW_FORMATS[fmt]
    got = load_sources(_cfg(tmp_path, [entry], ["cms.gov", "mass.gov"])).get(entry["source_id"])
    assert got.format == fmt
    assert got.npis == []
    assert got.media is not None  # defaulted from the format when omitted
    assert not got.is_rate_row_source


def test_new_sources_are_invisible_to_the_rate_row_pipeline(tmp_path):
    got = load_sources(_cfg(tmp_path, list(NEW_FORMATS.values())))
    assert len(got.sources) == len(BASE["sources"]) + len(NEW_FORMATS)
    assert [s.source_id for s in got.rate_row_sources] == [s["source_id"] for s in BASE["sources"]]


def test_reference_kinds_are_not_price_kinds():
    assert not {k.value for k in ReferenceKind} & {k.value for k in SourceKind}


def _bad(**kw) -> dict:
    return {**NEW_FORMATS["dph_xlsx"], **kw}


@pytest.mark.parametrize(
    "entry, msg",
    [
        (_bad(kind="medicare_pfs"), "needs kind"),
        (_bad(media="pdf"), "is"),
        (_bad(container="zip"), "container"),
        (_bad(access="paged_api"), "access"),
        (_bad(npis=["1023049236"]), "only checked for hospital_mrf"),
        (_bad(payer_id="BCBS_MA"), "payer_id only applies"),
        (_bad(filters={"state": "MA"}), "filters only apply"),
        (_bad(url="http://www.mass.gov/doc/x"), "https"),
        ({**NEW_FORMATS["tic_in_network"], "payer_id": None}, "needs payer_id"),
        ({**NEW_FORMATS["tic_in_network"], "payer_id": "bcbs"}, "needs payer_id"),
        ({**NEW_FORMATS["html_price_page"], "entity_id": None}, "needs entity_id"),
        ({**NEW_FORMATS["nppes_monthly"], "members": {"main": "npidata_pfile_*.csv"}}, "members"),
        (
            {
                "source_id": "x_mrf",
                "kind": "hospital_mrf",
                "format": "cms_v3_json",
                "url": None,
                "entity_id": "x",
            },
            "needs entity_id and npis",
        ),
    ],
)
def test_format_rules_reject_mismatches(entry, msg):
    with pytest.raises(ValueError, match=msg):
        SourceSpec.model_validate(entry)


def test_nppes_member_roles_are_the_four_monthly_files():
    assert NPPES_MEMBERS == {"main", "pl_pfile", "othername_pfile", "endpoint_pfile"}


def test_cli_stage_skips_non_mrf_sources(tmp_path, capsys):
    from app.etl import cli

    cfg = _cfg(tmp_path, [NEW_FORMATS["cms_pfs_rvu"]])
    data = tmp_path / "data"
    rc = cli.main(
        ["--data-dir", str(data), "--config-dir", str(cfg), "stage", "--source", "cms_pfs_rvu26a"]
    )
    out = capsys.readouterr().out
    assert "SKIP   cms_pfs_rvu26a: format cms_pfs_rvu is not a hospital MRF" in out
    assert rc == 0
