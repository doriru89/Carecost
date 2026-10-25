"""Every source format with a reader validates as a sources.d fragment, and the hospital-MRF
rate_row pipeline ignores the ones it does not read. P3: only MRF + TiC formats are registered;
a stream adds its format together with its reader."""

from __future__ import annotations

import typing
from pathlib import Path

import pytest
import yaml

from app.etl.config import CONFIG_DIR, MRF_FORMATS, SourceFormat, SourceSpec, load_sources

BASE = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())

# One minimal, realistic fragment entry per non-MRF format (MRF formats are covered by sources.yaml).
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
    got = load_sources(_cfg(tmp_path, [entry])).get(entry["source_id"])
    assert got.format == fmt
    assert got.npis == []
    assert got.media is not None  # defaulted from the format when omitted
    assert not got.is_rate_row_source


def test_new_sources_are_invisible_to_the_rate_row_pipeline(tmp_path):
    got = load_sources(_cfg(tmp_path, list(NEW_FORMATS.values())))
    assert len(got.sources) == len(BASE["sources"]) + len(NEW_FORMATS)
    assert [s.source_id for s in got.rate_row_sources] == [s["source_id"] for s in BASE["sources"]]


def test_tic_in_network_accepts_zip():
    """D30: Harvard Pilgrim and Tufts publish their in-network files as .zip."""
    spec = SourceSpec.model_validate({**NEW_FORMATS["tic_in_network"], "container": "zip"})
    assert spec.container == "zip"


@pytest.mark.parametrize(
    "fmt",
    [
        "nppes_monthly",
        "dph_xlsx",
        "fhir_provider_directory",
        "cms_dataset_csv",
        "cms_pfs_rvu",
        "cms_opps_addendum",
        "masshealth_fee_schedule",
        "html_price_page",
    ],
)
def test_formats_without_a_reader_are_not_registered(fmt):
    """P3: no pre-registered guesses. A stream adds the format with its reader."""
    with pytest.raises(ValueError):
        SourceSpec.model_validate({**NEW_FORMATS["tic_in_network"], "format": fmt})


def _bad(**kw) -> dict:
    return {**NEW_FORMATS["tic_table_of_contents"], **kw}


@pytest.mark.parametrize(
    "entry, msg",
    [
        (_bad(kind="medicare_pfs"), "needs kind"),
        (_bad(media="csv"), "is"),
        (_bad(container="zip"), "container"),
        (_bad(access="http_range"), "access"),
        (_bad(npis=["1023049236"]), "only checked for hospital_mrf"),
        (_bad(url="http://transparency-in-coverage.bluecrossma.com/x"), "https"),
        ({**NEW_FORMATS["tic_in_network"], "payer_id": None}, "needs payer_id"),
        ({**NEW_FORMATS["tic_in_network"], "payer_id": "bcbs"}, "needs payer_id"),
        (
            {
                "source_id": "x_mrf",
                "kind": "hospital_mrf",
                "format": "cms_v3_json",
                "url": None,
                "entity_id": "x",
                "payer_id": "BCBS_MA",
                "npis": ["1023049236"],
            },
            "payer_id only applies",
        ),
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


def test_cli_stage_skips_non_mrf_sources(tmp_path, capsys):
    from app.etl import cli

    cfg = _cfg(tmp_path, [NEW_FORMATS["tic_table_of_contents"]])
    data = tmp_path / "data"
    rc = cli.main(
        ["--data-dir", str(data), "--config-dir", str(cfg), "stage", "--source", "bcbs_ma_tic_toc"]
    )
    out = capsys.readouterr().out
    assert "SKIP   bcbs_ma_tic_toc: format tic_table_of_contents is not a hospital MRF" in out
    assert rc == 0
