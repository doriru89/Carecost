"""'Learn more' links: MedlinePlus Connect only where the code was seen to resolve."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.care_paths.models import CONNECT_CPT_OID


def test_connect_links_only_for_resolving_codes(bundle):
    resolving = bundle.connect.resolves
    for path in bundle.paths.values():
        for step in path.steps:
            codes = {c.code for c in step.cpts}
            for lm in step.learn_more:
                if lm.kind != "medlineplus_connect":
                    continue
                assert lm.code in codes, f"{path.id}.{step.id}: link code {lm.code} not on step"
                assert lm.code in resolving, f"{path.id}.{step.id}: {lm.code} not seen to resolve"
                q = parse_qs(urlparse(lm.url).query)
                assert q["mainSearchCriteria.v.cs"] == [CONNECT_CPT_OID]
                assert q["mainSearchCriteria.v.c"] == [lm.code]


def test_codes_known_not_to_resolve_have_no_connect_link(bundle):
    dead = set(bundle.connect.no_result)
    for path in bundle.paths.values():
        for step in path.steps:
            for lm in step.learn_more:
                if lm.kind == "medlineplus_connect":
                    assert lm.code not in dead


def test_core_imaging_steps_have_learn_more(bundle):
    p = bundle.paths["shoulder_chronic_clicking_v1"]
    for sid in ("xray", "tendon_scan_mri", "tendon_scan_ultrasound"):
        step = next(s for s in p.steps if s.id == sid)
        assert any(lm.kind == "medlineplus_connect" for lm in step.learn_more), sid
