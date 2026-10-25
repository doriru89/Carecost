"""Find each site's own pages (brief S0.1) -> ``data/sites/site_facts/pages.yaml``.

Sources, in order (the first that gives a page wins; all are recorded):

1. ``found.yaml`` overrides: hand-checked or web-search-found URLs (``source`` says which), and
   explicit "no own page" decisions. Always wins.
2. the census CSV ``website`` column when it is a location-specific page (not a chain homepage or
   a generic care-options page, see ``GENERIC``).
3. the operator's own location finder: its sitemap (``finders.yaml``), matched to the site by
   town + distinctive name words. Ambiguous matches are not taken; they are listed as candidates.

Booking links (Solv, MyChart, Patient Gateway) are never a site's own page.
"""

from __future__ import annotations

import csv
import gzip
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from app.etl.fetch import FetchError
from app.site_facts.fetch import Fetcher
from app.site_facts.paths import CENSUS_CSV, DATA, PAGES, SITES_YAML

FINDERS = DATA / "finders.yaml"
FOUND = DATA / "found.yaml"
BOOKING_HOSTS = ("solvhealth.com", "patientgateway.", "mychart.", "zocdoc.com", "clockwisemd.com")
# a census "website" that is the same page for many sites is not that site's own page
GENERIC = re.compile(
    r"^https://bilh\.org/care-options/urgent-care/?$|^https://www\.southshorehealth\.org/healthexpress/find-us/?$"
)
STOP = {
    "inc", "llc", "pc", "pllc", "the", "of", "and", "at", "in", "for", "ma", "a", "assoc", "associates",
    "health", "center", "centre", "clinic", "care", "medical", "corporation", "corp", "group", "llp",
    "boston", "mass", "general", "brigham", "mgb", "gb", "formerly", "fka", "ste", "st", "street",
    "physicians", "organization", "services", "professional", "community", "dba",
}  # fmt: skip


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOP and not t.isdigit()]


def _slug_tokens(url: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", urlparse(url).path.lower()))


def load_sites(path: Path = SITES_YAML) -> list[dict[str, Any]]:
    return list(yaml.safe_load(path.read_text())["sites"])


def load_census(path: Path = CENSUS_CSV) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["site_id"]: r for r in csv.DictReader(fh)}


@dataclass
class Finder:
    id: str
    sitemaps: list[str]
    url_pattern: str  # regex a location URL must match
    operators: list[str]  # regexes on site operator/name/system_id choosing which sites use it
    town_required: bool = True
    min_score: int = 3  # town match counts 2, each distinctive name word 1

    def applies(self, site: dict[str, Any]) -> bool:
        hay = " ".join(str(site.get(k) or "") for k in ("operator", "name", "system_id", "id"))
        return any(re.search(p, hay, re.I) for p in self.operators)


def load_finders(path: Path = FINDERS) -> list[Finder]:
    if not path.is_file():
        return []
    return [Finder(**f) for f in (yaml.safe_load(path.read_text()) or {}).get("finders", [])]


def sitemap_urls(fetcher: Fetcher, url: str, depth: int = 0) -> list[str]:
    body = fetcher.get_raw(url)
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    text = body.decode("utf-8", "replace")
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
    if "<sitemapindex" in text and depth < 2:
        out: list[str] = []
        for sub in locs:
            out += sitemap_urls(fetcher, sub, depth + 1)
        return out
    return locs


def score(site: dict[str, Any], url: str) -> tuple[int, bool]:
    """(distinctive name words found in the URL path, town found in the URL path)."""
    slug = _slug_tokens(url)
    town = re.findall(
        r"[a-z0-9]+", site["address"]["city"].lower()
    )  # no stopwords: "boston" is a town
    town_hit = bool(town) and all(t in slug for t in town)
    name = [t for t in _tokens(site["name"]) if t not in town]
    return sum(1 for t in set(name) if t in slug), town_hit


def match(site: dict[str, Any], urls: list[str], finder: Finder) -> tuple[str | None, list[str]]:
    """Best URL, or None with the tied candidates when the match is not clear."""
    scored = []
    for u in urls:
        if not re.search(finder.url_pattern, u):
            continue
        n, town = score(site, u)
        if finder.town_required and not town:
            continue
        if n == 0 and finder.town_required is False:
            continue
        scored.append((n + (2 if town else 0), u))
    if not scored:
        return None, []
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    top = [u for s, u in scored if s == scored[0][0]]
    if len(top) == 1 and scored[0][0] >= finder.min_score:
        return top[0], []
    return None, top[:5]


def _own_census_page(row: dict[str, str] | None) -> str | None:
    w = (row or {}).get("website", "").strip()
    if not w or GENERIC.match(w) or any(h in w for h in BOOKING_HOSTS):
        return None
    return w


def discover(fetcher: Fetcher | None, sites: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sites = sites or load_sites()
    census = load_census()
    found = (yaml.safe_load(FOUND.read_text()) or {}).get("sites", {}) if FOUND.is_file() else {}
    finders = load_finders()
    sitemap_cache: dict[str, list[str]] = {}
    errors: dict[str, str] = {}

    def finder_urls(f: Finder) -> list[str]:
        if f.id not in sitemap_cache:
            urls: list[str] = []
            for sm in f.sitemaps:
                try:
                    urls += sitemap_urls(fetcher, sm) if fetcher else []
                except FetchError as e:
                    errors[sm] = str(e)
            sitemap_cache[f.id] = urls
        return sitemap_cache[f.id]

    out: dict[str, Any] = {}
    for s in sites:
        sid = s["id"]
        entry: dict[str, Any] = {"site_type": s["site_type"], "pages": []}
        if sid in found:
            f = found[sid]
            if f.get("no_own_page"):
                entry["no_own_page"] = f["no_own_page"]
            if f.get("scope"):
                entry["scope"] = f["scope"]
            for p in f.get("pages", []):
                entry["pages"].append({**p, "source": f.get("source", "hand_checked")})
        if not entry["pages"] and not entry.get("no_own_page"):
            w = _own_census_page(census.get(s.get("census_id") or ""))
            if w:
                entry["pages"].append({"url": w, "role": "location", "source": "census_website"})
        if not entry["pages"] and not entry.get("no_own_page"):
            for f in finders:
                if not f.applies(s):
                    continue
                best, cands = match(s, finder_urls(f), f)
                if best:
                    entry["pages"].append(
                        {"url": best, "role": "location", "source": f"finder:{f.id}"}
                    )
                    break
                if cands:
                    entry.setdefault("candidates", []).extend(cands)
        if not entry["pages"] and not entry.get("no_own_page"):
            entry["no_own_page"] = "not found yet (census, finders, found.yaml)"
        out[sid] = entry
    return {"sites": out, "finder_errors": errors}


def write_pages(result: dict[str, Any], path: Path = PAGES) -> None:
    path.write_text(
        "# GENERATED by `python -m app.site_facts discover` from the census website column,\n"
        "# finders.yaml (operators' own sitemaps) and found.yaml (hand/search-found). Edit found.yaml.\n"
        + yaml.safe_dump({"version": 1, **result}, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


def load_pages(path: Path = PAGES) -> dict[str, Any]:
    return dict((yaml.safe_load(path.read_text()) or {}).get("sites", {})) if path.is_file() else {}
