"""sources.yaml registry + NPI check (bug E6) against real file headers."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.etl import stage
from app.etl.config import load_sources
from app.registries import all_hospitals

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mrf" / "meta"
SOURCES = load_sources()


def _meta_fixture(source_id: str) -> Path:
    for ext in (".csv", ".json"):
        p = FIX / f"{source_id}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(source_id)


def test_every_registry_hospital_has_exactly_one_mrf_source():
    mrf = [s.entity_id for s in SOURCES.sources if s.kind == "hospital_mrf"]
    assert sorted(mrf) == sorted(all_hospitals())


@pytest.mark.parametrize(
    "spec", [s for s in SOURCES.sources if s.kind == "hospital_mrf"], ids=lambda s: s.source_id
)
def test_registry_npis_match_the_file_type_2_npi(spec):
    """E6: 5 of 12 hospitals.yaml NPIs did not match the file. Both registries must agree."""
    meta = stage.read_meta(
        spec.model_copy(update={"container": "plain"}), _meta_fixture(spec.source_id)
    )
    assert meta.type_2_npis == spec.npis
    h = all_hospitals()[spec.entity_id]
    assert h.npi in meta.type_2_npis
    assert set(h.alternate_npis) <= set(meta.type_2_npis)


@pytest.mark.parametrize("spec", [s for s in SOURCES.sources if s.url], ids=lambda s: s.source_id)
def test_urls_are_https_and_on_the_allowlist(spec):
    from app.etl.fetch import host_allowed

    u = urlparse(spec.url)
    assert u.scheme == "https"
    assert host_allowed(u.hostname or "", SOURCES.fetch.allowed_domains)
