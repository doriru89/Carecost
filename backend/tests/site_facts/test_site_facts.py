"""Site facts pipeline (stream S0): vocabulary, cache, fetch politeness, verifier, merge."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.care_paths.loader import load_paths
from app.site_facts import discover as disc
from app.site_facts.fetch import Fetcher, cache_key, cached_text, load_manifest
from app.site_facts.merge import merge, write_review
from app.site_facts.models import FactsFile, RunFile, norm_hours, HoursSpan
from app.site_facts.paths import FACTS, MANIFEST, RUNS_DIR, SITES_YAML
from app.site_facts.text import quote_found, related_links, sha256_text, visible_text
from app.site_facts.verify import load_capabilities, load_run, verify

HTML = (
    """<html><head><title>Demo Urgent Care | Town</title><script>var x='Call 999';</script>
<style>.a{}</style></head><body><nav><a href="/town/services/">Our Services</a>
<a href="https://other.example/x">Services elsewhere</a></nav>
<h1>Demo Urgent Care Town</h1><div hidden>Secret 555-0000</div>
<p>Call   (617) 555-0100</p><p>Monday - Friday: 8:00 AM -
8:00 PM</p><ul><li>On-site X-ray</li><li>Physical therapy</li></ul>
<template><p>template text</p></template>"""
    + "<p>filler text for length</p>" * 30
    + "</body></html>"
)
URL = "https://demo.example/town/"


# ---------------------------------------------------------------- vocabulary (X1 capabilities)


def test_every_care_path_step_is_covered_by_exactly_one_capability() -> None:
    caps = load_capabilities()
    seen: dict[tuple[str, str], list[str]] = {}
    for cid, c in caps.capabilities.items():
        for cov in c.covers:
            seen.setdefault((cov.path, cov.step), []).append(cid)
    steps = {(pid, s.id) for pid, p in load_paths().items() for s in p.steps}
    assert steps - set(seen) == set(), "steps with no capability"
    assert set(seen) - steps == set(), "capability covers a step that does not exist"
    assert {k: v for k, v in seen.items() if len(v) > 1} == {}, "step covered twice"


def test_capability_labels_have_both_languages() -> None:
    for cid, c in load_capabilities().capabilities.items():
        assert c.label.en.strip() and c.label.zh.strip(), cid


# ---------------------------------------------------------------- visible text + quote rule


def test_visible_text_drops_scripts_hidden_and_templates() -> None:
    t = visible_text(HTML)
    assert t.startswith("TITLE: Demo Urgent Care | Town\n")
    assert "Call 999" not in t and "Secret" not in t and "template text" not in t
    assert "Demo Urgent Care Town" in t and "Call (617) 555-0100" in t


def test_quote_found_collapses_whitespace_only() -> None:
    t = visible_text(HTML)
    assert quote_found("Monday - Friday: 8:00 AM - 8:00 PM", t)
    assert quote_found("Call (617)\n555-0100", t)
    assert not quote_found("call (617) 555-0100", t)  # case matters
    assert not quote_found("Call 617-555-0100", t)  # punctuation matters
    assert not quote_found("   ", t)


def test_related_links_same_host_only() -> None:
    assert related_links(HTML, URL) == ["https://demo.example/town/services/"]


# ---------------------------------------------------------------- polite fetch


class FakeNet:
    def __init__(self, pages: dict[str, tuple[int, str]]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str, allowed: list[str]) -> tuple[int, str, bytes]:
        self.calls.append(url)
        code, body = self.pages.get(url, (404, ""))
        return code, url, body.encode()


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def _fetcher(
    tmp_path: Path, pages: dict[str, tuple[int, str]], browser=None
) -> tuple[Fetcher, FakeNet, Clock]:
    net, clk = FakeNet(pages), Clock()
    f = Fetcher(tmp_path, http=net, browser=browser, sleep=clk.sleep, clock=clk.now)
    return f, net, clk


def test_fetch_caches_visible_text_with_sha(tmp_path: Path) -> None:
    f, net, clk = _fetcher(
        tmp_path, {"https://demo.example/robots.txt": (404, ""), URL: (200, HTML)}
    )
    rec = f.fetch(URL)
    assert rec.status == "ok" and rec.method == "http"
    text = cached_text(URL, tmp_path)
    assert text and rec.page_sha256 == sha256_text(text)
    assert net.calls == ["https://demo.example/robots.txt", URL]
    assert clk.slept == [1.0]  # robots then page on the same host: one second apart
    f.fetch(URL)  # cached: no new request
    assert len(net.calls) == 2


def test_robots_disallow_is_manual_and_page_never_requested(tmp_path: Path) -> None:
    robots = "User-agent: *\nDisallow: /town/\n"
    f, net, _ = _fetcher(
        tmp_path, {"https://demo.example/robots.txt": (200, robots), URL: (200, HTML)}
    )
    rec = f.fetch(URL)
    assert rec.status == "manual" and "robots" in (rec.reason or "")
    assert URL not in net.calls


def test_robots_403_means_disallow_all(tmp_path: Path) -> None:
    f, net, _ = _fetcher(tmp_path, {"https://demo.example/robots.txt": (403, ""), URL: (200, HTML)})
    assert f.fetch(URL).status == "manual" and URL not in net.calls


@pytest.mark.parametrize("code", [403, 429])
def test_blocked_page_is_manual_not_retried_another_way(tmp_path: Path, code: int) -> None:
    used_browser = []
    f, net, _ = _fetcher(tmp_path, {"https://demo.example/robots.txt": (404, ""), URL: (code, "")},
                         browser=lambda u: used_browser.append(u) or HTML)  # fmt: skip
    rec = f.fetch(URL)
    assert rec.status == "manual" and rec.http_status == code
    assert used_browser == []


def test_challenge_page_is_manual(tmp_path: Path) -> None:
    page = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"
    f, _, _ = _fetcher(tmp_path, {"https://demo.example/robots.txt": (404, ""), URL: (200, page)},
                       browser=lambda u: page)  # fmt: skip
    assert f.fetch(URL).status == "manual"


def test_thin_page_tries_plain_browser_once(tmp_path: Path) -> None:
    thin = "<html><body><div id=app></div></body></html>"
    f, _, _ = _fetcher(tmp_path, {"https://demo.example/robots.txt": (404, ""), URL: (200, thin)},
                       browser=lambda u: HTML)  # fmt: skip
    rec = f.fetch(URL)
    assert rec.status == "ok" and rec.method == "playwright"


# ---------------------------------------------------------------- verifier + merge


def _cache_page(tmp_path: Path) -> tuple[Fetcher, dict]:
    f, _, _ = _fetcher(tmp_path, {"https://demo.example/robots.txt": (404, ""), URL: (200, HTML)})
    rec = f.fetch(URL)
    return f, {"url": URL, "fetched_at": rec.fetched_at, "page_sha256": rec.page_sha256}


def _run(run_id: str, base: dict, **site: object) -> RunFile:
    return RunFile.model_validate({"version": 1, "run_id": run_id, "extracted_by": "test",
                                   "extracted_at": "2026-10-25", "sites": {"demo": site}})  # fmt: skip


def _ev(base: dict, quote: str) -> dict:
    return {**base, "quote": quote}


def _verify(run: RunFile, tmp_path: Path):
    return verify(run, cache_dir=tmp_path, site_ids={"demo"})


def test_verifier_accepts_verbatim_and_rejects_the_rest(tmp_path: Path) -> None:
    _, b = _cache_page(tmp_path)
    run = _run("a", b,
               official_name={"value": "Demo Urgent Care Town", "evidence": [_ev(b, "Demo Urgent Care Town")]},
               phone={"value": "617-555-0199", "evidence": [_ev(b, "Call (617) 555-0100")]},
               hours={"value": [{"days": ["mon"], "open": "08:00", "close": "20:00"}],
                      "evidence": [_ev(b, "Monday to Friday 8-8")]},
               capabilities={"xray": {"value": "offered", "evidence": [_ev(b, "On-site X-ray")]},
                             "teleportation": {"value": "offered", "evidence": [_ev(b, "On-site X-ray")]},
                             "mri": {"value": "offered"}})  # fmt: skip
    res = _verify(run, tmp_path)
    got = {(r.field, r.reason) for r in res.rejections}
    assert got == {("phone", "phone_not_in_quote"), ("hours", "quote_not_found"),
                   ("capabilities.teleportation", "unknown_capability"), ("capabilities.mri", "no_evidence")}  # fmt: skip
    assert set(res.accepted["demo"].capabilities) == {"xray"}
    assert res.accepted["demo"].official_name is not None


def test_verifier_rejects_other_page_version_and_tampered_cache(tmp_path: Path) -> None:
    _, b = _cache_page(tmp_path)
    stale = {**b, "page_sha256": "0" * 64}
    run = _run(
        "a", b, official_name={"value": "Demo", "evidence": [_ev(stale, "Demo Urgent Care Town")]}
    )
    assert _verify(run, tmp_path).rejections[0].reason == "sha_mismatch"
    (tmp_path / f"{cache_key(URL)}.txt").write_text("Demo Urgent Care Town edited")
    run = _run(
        "a", b, official_name={"value": "Demo", "evidence": [_ev(b, "Demo Urgent Care Town")]}
    )
    assert _verify(run, tmp_path).rejections[0].reason == "sha_mismatch"


def test_verifier_rejects_uncached_url(tmp_path: Path) -> None:
    _, b = _cache_page(tmp_path)
    other = {**b, "url": "https://demo.example/other/"}
    run = _run(
        "a", b, official_name={"value": "Demo", "evidence": [_ev(other, "Demo Urgent Care Town")]}
    )
    assert _verify(run, tmp_path).rejections[0].reason == "url_not_cached"


def test_merge_agreed_disputed_and_review(tmp_path: Path) -> None:
    _, b = _cache_page(tmp_path)
    name = {"value": "Demo Urgent Care Town", "evidence": [_ev(b, "Demo Urgent Care Town")]}
    a = _run("a", b, official_name=name,
             phone={"value": "(617) 555-0100", "evidence": [_ev(b, "Call (617) 555-0100")]},
             hours={"value": [{"days": ["mon", "tue"], "open": "08:00", "close": "20:00"}],
                    "evidence": [_ev(b, "Monday - Friday: 8:00 AM - 8:00 PM")]},
             capabilities={"xray": {"value": "offered", "evidence": [_ev(b, "On-site X-ray")]}})  # fmt: skip
    bb = _run("b", b, official_name={**name, "value": "DEMO urgent-care town"},
              phone={"value": "617.555.0100", "evidence": [_ev(b, "(617) 555-0100")]},
              hours={"value": [{"days": ["tue"], "open": "08:00", "close": "20:00"},
                               {"days": ["mon"], "open": "08:00", "close": "20:00"}],
                     "evidence": [_ev(b, "Monday - Friday")]},
              capabilities={"physical_therapy": {"value": "offered", "evidence": [_ev(b, "Physical therapy")]},
                            "xray": {"value": "offered", "evidence": [_ev(b, "not on the page")]}})  # fmt: skip
    va, vb = _verify(a, tmp_path), _verify(bb, tmp_path)
    m = merge(va, vb)
    s = m.facts["sites"]["demo"]
    assert s["official_name"]["status"] == "agreed"  # case / punctuation ignored
    assert s["phone"]["status"] == "agreed"  # digits
    assert s["hours"]["status"] == "agreed"  # per-day comparison
    assert s["capabilities"]["xray"]["status"] == "disputed"  # b's quote failed the verifier
    assert s["capabilities"]["physical_therapy"]["status"] == "disputed"  # only one run
    assert {d.field for d in m.disputes} == {"capabilities.xray", "capabilities.physical_therapy"}
    FactsFile.model_validate(m.facts)
    page = write_review(m, "a", "b", {"demo": "Demo"}, tmp_path / "review")
    html = page.read_text()
    assert "quote_not_found" in html and "Physical therapy" in html

    reviews = [{"site_id": "demo", "field": "capabilities.physical_therapy", "value": "offered"},
               {"site_id": "demo", "field": "capabilities.mri", "value": "offered"}]  # fmt: skip
    m2 = merge(va, vb, reviews)
    assert (
        m2.facts["sites"]["demo"]["capabilities"]["physical_therapy"]["status"] == "austin_reviewed"
    )
    assert m2.facts["sites"]["demo"]["capabilities"]["physical_therapy"]["evidence"]
    assert [r["field"] for r in m2.stale_reviews] == [
        "capabilities.mri"
    ]  # matches no verified claim


def test_norm_hours_is_order_free() -> None:
    a = [HoursSpan(days=["mon", "tue"], open="08:00", close="20:00")]
    b = [
        HoursSpan(days=["tue"], open="08:00", close="20:00"),
        HoursSpan(days=["mon"], open="08:00", close="20:00"),
    ]
    assert norm_hours(a) == norm_hours(b)


# ---------------------------------------------------------------- discovery


def test_discovery_match_needs_town_and_a_name_word() -> None:
    site = {"name": "Mass General Brigham Endoscopy Clinic", "address": {"city": "Braintree"}}
    f = disc.Finder(id="t", sitemaps=[], url_pattern=r"/locations/", operators=["x"])
    urls = ["https://x.org/locations/braintree-ma/mass-general-brigham-endoscopy-clinic-loc1",
            "https://x.org/locations/braintree-ma/mass-general-brigham-imaging-loc2",
            "https://x.org/locations/quincy-ma/mass-general-brigham-endoscopy-clinic-loc3"]  # fmt: skip
    best, _ = disc.match(site, urls, f)
    assert best == urls[0]
    best, cands = disc.match({**site, "name": "Mass General Brigham Clinic"}, urls, f)
    assert best is None and len(cands) == 2  # town only: ambiguous, not taken


def test_booking_and_generic_pages_are_not_own_pages() -> None:
    assert disc._own_census_page({"website": "https://www.solvhealth.com/book-online/x"}) is None
    assert disc._own_census_page({"website": "https://bilh.org/care-options/urgent-care"}) is None
    assert disc._own_census_page({"website": "https://www.afcurgentcare.com/watertown/"})


# ---------------------------------------------------------------- committed files


def _site_ids() -> set[str]:
    return {s["id"] for s in yaml.safe_load(SITES_YAML.read_text())["sites"]}


def test_committed_runs_and_facts_are_valid_x1() -> None:
    ids = _site_ids()
    for p in sorted(RUNS_DIR.glob("*.yaml")):
        run = load_run(p)
        assert set(run.sites) <= ids, p
    if FACTS.is_file():
        facts = FactsFile.model_validate(yaml.safe_load(FACTS.read_text()))
        assert set(facts.sites) <= ids
        caps = set(load_capabilities().capabilities)
        for s in facts.sites.values():
            assert set(s.capabilities) <= caps


def test_pages_and_manifest_refer_to_real_sites() -> None:
    ids = _site_ids()
    pages = disc.load_pages()
    if pages:
        assert set(pages) == ids  # every site has an entry: pages or a no_own_page reason
        for sid, e in pages.items():
            assert e.get("pages") or e.get("no_own_page"), sid
    if MANIFEST.is_file():
        for url, row in load_manifest().items():
            assert set(row.get("site_ids", [])) <= ids, url
            if row["status"] == "ok":
                assert len(row["page_sha256"]) == 64
