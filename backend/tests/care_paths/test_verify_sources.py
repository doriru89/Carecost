"""Offline tests for the V9 live-source sweep (the real sweep needs network)."""

from __future__ import annotations

from app.care_paths import verify_sources


def _page(variant_rows: str) -> bytes:
    return (
        "<html><body><div>Variant: 1</div><div>Chronic shoulder pain. Initial imaging.</div>"
        f"{variant_rows}<div>Variant: 1</div></body></html>"
    ).encode()


def test_unchanged_page_passes(bundle):
    src = bundle.sources["acr_chronic_shoulder_2022"]
    rows = "".join(
        f"<div>{p}</div><div>{dict(UA='Usually Appropriate', MBA='May Be Appropriate', UNA='Usually Not Appropriate')[r]}</div>"
        for p, r in src.acr_variants[1].ratings.items()
    )
    only_v1 = src.model_copy(
        update={
            "excerpts": ["Chronic shoulder pain. Initial imaging."],
            "acr_variants": {1: src.acr_variants[1]},
        }
    )
    assert verify_sources.check_source("x", only_v1, lambda url: _page(rows)) == []


def test_changed_rating_is_reported(bundle):
    src = bundle.sources["acr_chronic_shoulder_2022"]
    only_v1 = src.model_copy(update={"excerpts": [], "acr_variants": {1: src.acr_variants[1]}})
    rows = "<div>Radiography shoulder</div><div>May Be Appropriate</div>"
    problems = verify_sources.check_source("x", only_v1, lambda url: _page(rows))
    assert any("Radiography shoulder" in p for p in problems)


def test_missing_excerpt_is_reported(bundle):
    src = bundle.sources["medlineplus_xrays"]
    problems = verify_sources.check_source("x", src, lambda url: b"<p>totally different page</p>")
    assert len(problems) == len(src.excerpts)
