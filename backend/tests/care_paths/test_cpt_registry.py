"""CPT existence: every code in every path exists in the CMS 2026 PFS (PPRRVU2026_Jan_nonQPP.csv).

The committed registry (data/care_paths/cpt_registry_2026.json) is always checked. When the raw PFS
file is available (repo data/raw/... or env CARECOST_PFS_CSV), the registry itself is re-derived from it
so the snapshot can't drift from the government file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.care_paths import cpt_registry
from app.care_paths.loader import REPO_ROOT


def _pfs_path() -> Path | None:
    env = os.environ.get("CARECOST_PFS_CSV")
    candidates = [Path(env)] if env else []
    candidates.append(REPO_ROOT / cpt_registry.DEFAULT_PFS_RELPATH)
    for p in candidates:
        if p.is_file():
            return p
    return None


def test_every_path_code_is_in_registry(bundle):
    missing = []
    for path in bundle.paths.values():
        for step in path.steps:
            for ref in step.all_codes():
                if ref not in bundle.cpt_registry.codes:
                    missing.append(f"{path.id}.{step.id}: {ref}")
    assert not missing, missing


def test_registry_codes_are_used(bundle):
    used = {c for p in bundle.paths.values() for s in p.steps for c in s.all_codes()}
    unused = set(bundle.cpt_registry.codes) - used
    assert not unused, f"registry has codes no path uses (regenerate): {sorted(unused)}"


def test_registry_has_no_ama_descriptors(bundle):
    for code, entry in bundle.cpt_registry.codes.items():
        assert set(entry.model_dump()) <= {"status", "has_professional_technical_split"}, code


def test_registry_matches_pfs_file(bundle):
    pfs = _pfs_path()
    if pfs is None:
        pytest.skip("PFS CSV not present; set CARECOST_PFS_CSV to run the existence check")
    assert cpt_registry.sha256_file(pfs) == bundle.cpt_registry.source_sha256, (
        "PFS file changed since the registry was built; rebuild with "
        "python -m app.care_paths.cpt_registry --pfs <csv>"
    )
    live = cpt_registry.read_pfs(pfs, set(bundle.cpt_registry.codes))
    for code, entry in bundle.cpt_registry.codes.items():
        assert code in live, f"{code} not found in {pfs.name}"
        assert live[code] == entry, f"{code}: registry {entry} != PFS {live[code]}"


def test_pfs_parser_reads_status_and_split(tmp_path):
    csv = tmp_path / "pfs.csv"
    csv.write_text(
        "junk header\n"
        "HCPCS,MOD,DESCRIPTION,CODE,PAYMENT\n"
        "73030,,Xray,A,\n73030,26,Xray,A,\n73030,TC,Xray,A,\n"
        "00812,,Anes,J,\n"
    )
    got = cpt_registry.read_pfs(csv, {"73030", "00812", "11111"})
    assert got["73030"].status == "A" and got["73030"].has_professional_technical_split
    assert got["00812"].status == "J" and not got["00812"].has_professional_technical_split
    assert "11111" not in got


def test_research_flagged_codes_stay_marked(bundle):
    """Codes the research marked [断言] exist in PFS, but their mapping to the step is unconfirmed."""
    flagged = {
        c.code
        for p in bundle.paths.values()
        for s in p.steps
        for c in s.cpts
        if c.mapping == "asserted"
    }
    for code in ("97110", "73222", "23350", "77002", "20611", "99213"):
        assert code in flagged, f"{code} should stay asserted until a coder confirms it"
