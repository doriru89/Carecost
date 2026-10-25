"""Verifier for one extraction run (brief S0.4).

A claim is rejected when any of its evidence fails:

* ``url_not_cached``: the URL has no ``ok`` page in the cache (the run read something we cannot
  check, or the page was never fetched);
* ``sha_mismatch``: ``page_sha256`` / ``fetched_at`` differ from the cached page (a different
  version of the page), or the cached text no longer hashes to its recorded sha;
* ``quote_not_found``: the quote is not in the cached text (whitespace-collapsed substring, see
  ``text.quote_found``);
* ``phone_not_in_quote``: the phone digits do not appear in the quote;
* ``unknown_capability`` / ``unknown_site``: ids outside capabilities.yaml / sites.yaml;
* ``no_evidence``: ``offered`` / ``not_offered`` without evidence.

A claim with one bad quote is rejected whole: a person must be able to trust every quote shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.site_facts.fetch import Fetcher
from app.site_facts.models import CapabilityFile, Evidence, RunFile, RunSite, norm_phone
from app.site_facts.paths import CACHE_DIR, CAPABILITIES, SITES_YAML
from app.site_facts.text import quote_found, sha256_text


@dataclass
class Rejection:
    site_id: str
    field: str  # official_name | phone | hours | capabilities.<id> | site
    reason: str
    detail: str = ""


@dataclass
class VerifyResult:
    run: RunFile
    accepted: dict[str, RunSite]
    rejections: list[Rejection] = field(default_factory=list)
    claims: int = 0

    @property
    def accepted_claims(self) -> int:
        return self.claims - len([r for r in self.rejections if r.field != "site"])


def load_run(path: Path) -> RunFile:
    return RunFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_capabilities(path: Path = CAPABILITIES) -> CapabilityFile:
    return CapabilityFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class _Pages:
    def __init__(self, cache_dir: Path) -> None:
        self.f = Fetcher(cache_dir, http=lambda u, a: (599, u, b""))  # read-only use
        self.cache_dir = cache_dir
        self._text: dict[str, str | None] = {}

    def check(self, ev: Evidence) -> str | None:
        meta = self.f.load_meta(ev.url)
        if meta is None or meta.status != "ok":
            return "url_not_cached"
        if ev.url not in self._text:
            from app.site_facts.fetch import cached_text

            t = cached_text(ev.url, self.cache_dir)
            self._text[ev.url] = t if t is not None and sha256_text(t) == meta.page_sha256 else None
        text = self._text[ev.url]
        if text is None or meta.page_sha256 != ev.page_sha256 or meta.fetched_at != ev.fetched_at:
            return "sha_mismatch"
        if not quote_found(ev.quote, text):
            return "quote_not_found"
        return None


def verify(
    run: RunFile,
    *,
    cache_dir: Path = CACHE_DIR,
    capabilities: CapabilityFile | None = None,
    site_ids: set[str] | None = None,
) -> VerifyResult:
    caps = set((capabilities or load_capabilities()).capabilities)
    if site_ids is None:
        site_ids = {s["id"] for s in yaml.safe_load(SITES_YAML.read_text())["sites"]}
    pages = _Pages(cache_dir)
    res = VerifyResult(run=run, accepted={})

    def bad_evidence(evs: list[Evidence]) -> tuple[str, str] | None:
        for ev in evs:
            why = pages.check(ev)
            if why:
                return why, f"{ev.url} :: {ev.quote[:80]!r}"
        return None

    for sid, site in run.sites.items():
        if sid not in site_ids:
            res.rejections.append(Rejection(sid, "site", "unknown_site"))
            continue
        keep: dict[str, Any] = {"pages_read": site.pages_read, "note": site.note}
        for name in ("official_name", "phone", "hours"):
            claim = getattr(site, name)
            if claim is None:
                continue
            res.claims += 1
            bad = bad_evidence(claim.evidence)
            if bad is None and name == "phone":
                digits = norm_phone(claim.value)
                if not any(digits in re.sub(r"\D", "", e.quote) for e in claim.evidence):
                    bad = ("phone_not_in_quote", claim.value)
            if bad:
                res.rejections.append(Rejection(sid, name, *bad))
            else:
                keep[name] = claim
        keep_caps = {}
        for cid, c in site.capabilities.items():
            if c.value == "unknown":
                continue
            res.claims += 1
            if cid not in caps:
                res.rejections.append(Rejection(sid, f"capabilities.{cid}", "unknown_capability"))
                continue
            if not c.evidence:
                res.rejections.append(Rejection(sid, f"capabilities.{cid}", "no_evidence"))
                continue
            bad = bad_evidence(c.evidence)
            if bad:
                res.rejections.append(Rejection(sid, f"capabilities.{cid}", *bad))
            else:
                keep_caps[cid] = c
        keep["capabilities"] = keep_caps
        res.accepted[sid] = RunSite(**keep)
    return res


def report(res: VerifyResult) -> str:
    lines = [
        f"run {res.run.run_id}: {res.claims} claims, {res.accepted_claims} accepted, "
        f"{len(res.rejections)} rejected"
    ]
    for r in res.rejections:
        lines.append(f"  REJECT {r.site_id} {r.field}: {r.reason} {r.detail}")
    return "\n".join(lines)
