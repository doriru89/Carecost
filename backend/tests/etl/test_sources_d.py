"""sources.yaml + sources.d/*.yaml fragments: merged, duplicate ids fail, domains are unioned."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.etl.config import CONFIG_DIR, load_sources

BASE = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())


def _spec(source_id: str, **kw) -> dict:
    spec = {
        "source_id": source_id,
        "kind": "hospital_mrf",
        "entity_id": source_id,
        "format": "cms_v3_csv_tall",
        "container": "plain",
        "encoding": "utf-8",
        "npis": ["1234567893"],
        "url": None,
    }
    spec.update(kw)
    return spec


def _cfg(tmp_path: Path, fragments: dict[str, dict] | None = None) -> Path:
    cfg = tmp_path / "etl"
    cfg.mkdir()
    (cfg / "sources.yaml").write_text(yaml.safe_dump(BASE))
    if fragments is not None:
        d = cfg / "sources.d"
        d.mkdir()
        for name, doc in fragments.items():
            (d / name).write_text(yaml.safe_dump(doc))
    return cfg


def test_no_sources_d_dir_is_the_same_as_sources_yaml(tmp_path):
    got = load_sources(_cfg(tmp_path))
    assert [s.source_id for s in got.sources] == [s["source_id"] for s in BASE["sources"]]


def test_fragments_are_appended_in_name_order(tmp_path):
    cfg = _cfg(
        tmp_path,
        {
            "b_gov.yaml": {"version": 1, "sources": [_spec("gov_b")]},
            "a_tic.yaml": {"version": 1, "sources": [_spec("tic_a1"), _spec("tic_a2")]},
        },
    )
    ids = [s.source_id for s in load_sources(cfg).sources]
    assert ids[-3:] == ["tic_a1", "tic_a2", "gov_b"]
    assert len(ids) == len(BASE["sources"]) + 3


def test_non_yaml_files_in_sources_d_are_ignored(tmp_path):
    cfg = _cfg(tmp_path, {"a.yaml": {"sources": [_spec("x1")]}})
    (cfg / "sources.d" / "notes.txt").write_text("not a fragment")
    assert load_sources(cfg).get("x1").source_id == "x1"


def test_fragment_domains_are_unioned_into_fetch_allowlist(tmp_path):
    cfg = _cfg(
        tmp_path,
        {
            "a.yaml": {"allowed_domains": ["bluecrossma.com", "bidmc.org"], "sources": []},
            "b.yaml": {"allowed_domains": ["cms.gov"]},
        },
    )
    allowed = load_sources(cfg).fetch.allowed_domains
    assert allowed[: len(BASE["fetch"]["allowed_domains"])] == BASE["fetch"]["allowed_domains"]
    assert allowed.count("bidmc.org") == 1
    assert allowed[-2:] == ["bluecrossma.com", "cms.gov"]


def test_duplicate_id_between_sources_yaml_and_fragment_fails(tmp_path):
    existing = BASE["sources"][0]["source_id"]
    cfg = _cfg(tmp_path, {"tic.yaml": {"sources": [_spec(existing)]}})
    with pytest.raises(
        ValueError, match=rf"duplicate source_id '{existing}'.*sources.yaml.*tic.yaml"
    ):
        load_sources(cfg)


def test_duplicate_id_between_two_fragments_fails(tmp_path):
    cfg = _cfg(
        tmp_path,
        {"a.yaml": {"sources": [_spec("same")]}, "b.yaml": {"sources": [_spec("same")]}},
    )
    with pytest.raises(ValueError, match=r"duplicate source_id 'same'.*a.yaml.*b.yaml"):
        load_sources(cfg)


def test_duplicate_id_inside_one_fragment_fails(tmp_path):
    cfg = _cfg(tmp_path, {"a.yaml": {"sources": [_spec("dup"), _spec("dup")]}})
    with pytest.raises(ValueError, match="duplicate source_id 'dup'"):
        load_sources(cfg)


def test_fragment_may_not_override_fetch_settings(tmp_path):
    cfg = _cfg(tmp_path, {"a.yaml": {"fetch": {"timeout_s": 1}, "sources": []}})
    with pytest.raises(ValueError):
        load_sources(cfg)


def test_fragment_sources_are_validated_like_sources_yaml(tmp_path):
    cfg = _cfg(tmp_path, {"a.yaml": {"sources": [_spec("bad", npis=["123"])]}})
    with pytest.raises(ValueError):
        load_sources(cfg)


def test_committed_config_loads_with_its_fragments():
    """The real data/etl tree (sources.yaml + whatever sources.d holds) loads cleanly."""
    load_sources.cache_clear()
    got = load_sources()
    assert len({s.source_id for s in got.sources}) == len(got.sources)
