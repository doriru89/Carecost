"""CLI: ``python -m app.site_facts <discover|fetch|verify|merge|coverage>`` (see package doc)."""

from __future__ import annotations

import argparse
import collections
import re
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from app.site_facts import discover as disc
from app.site_facts.fetch import Fetcher, PageRecord, cached_text, load_manifest, write_manifest
from app.site_facts.merge import load_reviews, merge, write_facts, write_review
from app.site_facts.text import LEGAL_LINK
from app.site_facts.paths import CACHE_DIR, MANIFEST, PAGES, RUNS_DIR, SITES_YAML
from app.site_facts.verify import load_run, report, verify

HOURS_TEXT = re.compile(
    r"(?i)\b(mon(day)?|tue(s(day)?)?|wed(nesday)?|thu(rs(day)?)?|fri(day)?|sat(urday)?|sun(day)?|"
    r"weekdays?|weekends?|daily|7 days)\b[^\n]{0,60}?\b\d{1,2}(:\d{2})?\s*([ap]\.?m\.?)"
)


# MGB location pages print hours as a 24h table: "Monday\n08:00\n20:00"
HOURS_24 = re.compile(r"\n(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\n\d\d:\d\d\n\d\d:\d\d")


def _has_hours(text: str) -> bool:
    """Heuristic: the page prints opening hours as text (a day word near a time)."""
    return bool(HOURS_TEXT.search(text) or HOURS_24.search(text))


def cmd_discover(a: argparse.Namespace) -> int:
    res = disc.discover(Fetcher(allow_js=False))
    disc.write_pages(res)
    print(f"wrote {PAGES}; finder errors: {res['finder_errors'] or 'none'}")
    return 0


def prune_site_ids(records: list[PageRecord], pages: dict[str, Any]) -> list[PageRecord]:
    """Drop a site id from a cached page that is no longer one of that site's pages in pages.yaml
    (neither listed nor followed from a listed page), e.g. a finder match rejected by hand, so
    ``show`` never hands an extraction run a wrong place's page. Returns the changed records."""
    by_url = {r.url: r for r in records}
    own: dict[str, set[str]] = {}
    for sid, e in pages.items():
        urls = {p["url"] for p in e.get("pages", [])}
        for u in list(urls):
            rec = by_url.get(u)
            urls |= set(rec.related) if rec else set()
        own[sid] = urls
    changed = []
    for r in records:
        keep = [s for s in r.site_ids if r.url in own.get(s, set())]
        if keep != r.site_ids:
            r.site_ids = keep
            changed.append(r)
    return changed


def _all_records() -> list[PageRecord]:
    f = Fetcher()
    out = []
    for p in sorted(CACHE_DIR.glob("*.json")):
        rec = f.load_meta_path(p)
        if rec:
            out.append(rec)
    return out


def cmd_fetch(a: argparse.Namespace) -> int:
    pages = disc.load_pages()
    want = set(a.sites.split(",")) if a.sites else None
    f = Fetcher(allow_js=not a.no_js)
    t0 = time.monotonic()
    per_site: dict[str, list[PageRecord]] = {}
    for sid, e in pages.items():
        if want and sid not in want:
            continue
        todo = [
            (p["url"], p.get("role", "location"), bool(p.get("needs_js")))
            for p in e.get("pages", [])
        ]
        seen: set[str] = set()
        st = time.monotonic()
        while todo:
            url, role, js = todo.pop(0)
            if url in seen:
                continue
            seen.add(url)
            prev = f.load_meta(url)  # a URL shared by several sites keeps every site id
            rec = f.fetch(url, needs_js=js, refresh=a.refresh)
            rec.site_ids = sorted(set(rec.site_ids) | set(prev.site_ids if prev else []) | {sid})
            rec.roles = sorted(set(rec.roles) | set(prev.roles if prev else []) | {role})
            f._save(rec)
            per_site.setdefault(sid, []).append(rec)
            if a.follow and role == "location" and rec.status == "ok":
                todo += [
                    (u, "related", False)
                    for u in [x for x in rec.related if not LEGAL_LINK.search(x)][: a.follow]
                ]
        if want:
            n_ok = sum(r.status == "ok" for r in per_site.get(sid, []))
            print(
                f"{sid}: {len(per_site.get(sid, []))} pages ({n_ok} ok) in {time.monotonic() - st:.1f}s"
            )
            for r in per_site.get(sid, []):
                print(f"   {r.status:6} {r.method:10} {r.text_chars:6}ch {r.url} {r.reason or ''}")
    recs = _all_records()
    for r in prune_site_ids(recs, pages):
        f._save(r)
        print(f"   pruned site ids on {r.url} -> {r.site_ids}")
    write_manifest(recs)
    print(f"{f.requests} requests in {time.monotonic() - t0:.1f}s; manifest {MANIFEST}")
    return 0


def _names() -> dict[str, str]:
    return {s["id"]: s["name"] for s in yaml.safe_load(SITES_YAML.read_text())["sites"]}


def _run_path(x: str) -> Path:
    p = Path(x)
    return p if p.suffix == ".yaml" and p.exists() else RUNS_DIR / f"{x}.yaml"


def cmd_verify(a: argparse.Namespace) -> int:
    res = verify(load_run(_run_path(a.run)))
    print(report(res))
    return 1 if res.rejections and a.strict else 0


def cmd_merge(a: argparse.Namespace) -> int:
    ra, rb = load_run(_run_path(a.a)), load_run(_run_path(a.b))
    if ra.run_id == rb.run_id:
        print("merge needs two different runs", file=sys.stderr)
        return 2
    va, vb = verify(ra), verify(rb)
    print(report(va))
    print(report(vb))
    m = merge(va, vb, load_reviews())
    write_facts(m, ra.run_id, rb.run_id)
    page = write_review(m, ra.run_id, rb.run_id, _names())
    print(
        f"agreed {m.agreed}, austin_reviewed {m.reviewed}, disputed {len(m.disputes)}; review page {page}"
    )
    return 0


def coverage() -> dict[str, Any]:
    sites = yaml.safe_load(SITES_YAML.read_text())["sites"]
    pages = disc.load_pages()
    man = load_manifest()
    kinds: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for s in sites:
        e = pages.get(s["id"], {})
        k = kinds[s["site_type"]]
        k["sites"] += 1
        urls = [p["url"] for p in e.get("pages", [])]
        if urls:
            k["own_page_found"] += 1
        rows = [man[u] for u in man if s["id"] in man[u].get("site_ids", [])]
        ok = [r for r in rows if r["status"] == "ok"]
        if rows:
            k["fetched"] += 1
        if ok:
            k["fetched_ok"] += 1
        if any(r["status"] == "manual" for r in rows) and not ok:
            k["manual"] += 1
        if any(_has_hours(cached_text(r["url"]) or "") for r in ok):
            k["hours_in_text"] += 1
        if any(r.get("jsonld_hours") for r in ok):
            k["hours_jsonld"] += 1
    total: collections.Counter[str] = collections.Counter()
    for c in kinds.values():
        total.update(c)
    return {"by_kind": {k: dict(v) for k, v in sorted(kinds.items())}, "total": dict(total)}


def cmd_coverage(a: argparse.Namespace) -> int:
    print(yaml.safe_dump(coverage(), sort_keys=False))
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    """Everything an extraction run may read for a site: each cached page with the exact
    ``url`` / ``fetched_at`` / ``page_sha256`` to copy into evidence, then its text."""
    man = load_manifest()
    pages = disc.load_pages()
    for sid in a.sites.split(","):
        rows = [r for r in man.values() if sid in r.get("site_ids", [])]
        print(f"##### SITE {sid}: {len(rows)} pages")
        if pages.get(sid, {}).get("scope") == "hospital_page":
            print(
                "    scope: hospital_page  (these pages are a hospital's, not this site's own: add\n"
                "    `scope: hospital_page` to every EV for this site; see docs/etl/site_facts.md)"
            )
        for r in rows:
            print(f"=== url: {r['url']}\n    status: {r['status']} {r.get('reason') or ''}")
            if r["status"] != "ok":
                continue
            print(f"    fetched_at: '{r['fetched_at']}'\n    page_sha256: {r['page_sha256']}\n---")
            print(cached_text(r["url"]) or "(missing from cache)")
    return 0


def targets() -> list[dict[str, Any]]:
    """The sites an extraction run covers: every site with at least one ``ok`` cached page."""
    man = load_manifest()
    pages = disc.load_pages()
    out = []
    for sid, e in pages.items():
        ok = sorted(
            u for u, r in man.items() if sid in r.get("site_ids", []) and r["status"] == "ok"
        )
        if ok:
            out.append({"site_id": sid, "site_type": e.get("site_type"), "ok_pages": len(ok),
                        **({"scope": e["scope"]} if e.get("scope") else {})})  # fmt: skip
    return out


def cmd_targets(a: argparse.Namespace) -> int:
    rows = targets()
    if a.ids:
        print(",".join(r["site_id"] for r in rows))
        return 0
    for r in rows:
        print(f"{r['site_id']}\t{r['site_type']}\t{r['ok_pages']} pages\t{r.get('scope', '')}")
    print(
        f"# {len(rows)} sites; {sum(1 for r in rows if r.get('scope'))} with scope: hospital_page"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.site_facts")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover").set_defaults(fn=cmd_discover)
    f = sub.add_parser("fetch")
    f.add_argument("--sites", help="comma-separated site ids (default: all in pages.yaml)")
    f.add_argument(
        "--follow", type=int, default=3, help="follow up to N services/hours links (0=off)"
    )
    f.add_argument("--refresh", action="store_true")
    f.add_argument("--no-js", action="store_true", help="never use the browser")
    f.set_defaults(fn=cmd_fetch)
    v = sub.add_parser("verify")
    v.add_argument("run")
    v.add_argument("--strict", action="store_true", help="exit 1 when any claim is rejected")
    v.set_defaults(fn=cmd_verify)
    m = sub.add_parser("merge")
    m.add_argument("a")
    m.add_argument("b")
    m.set_defaults(fn=cmd_merge)
    sub.add_parser("coverage").set_defaults(fn=cmd_coverage)
    t = sub.add_parser("targets")
    t.add_argument("--ids", action="store_true", help="comma-separated ids only")
    t.set_defaults(fn=cmd_targets)
    sh = sub.add_parser("show")
    sh.add_argument("sites", help="comma-separated site ids")
    sh.set_defaults(fn=cmd_show)
    a = p.parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    sys.exit(main())
