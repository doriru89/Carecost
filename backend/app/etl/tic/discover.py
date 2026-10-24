"""Monthly discovery: resolve each network's in-network file URL from its table of contents.

TOC shapes handled: the CMS TiC table-of-contents JSON (``reporting_structure[].in_network_files``;
BCBS, HP, Tufts, MGB), Aetna's HealthSparq ``latest_metadata.json`` (``files[].filePath``) and
UHC's blob listing (``blobs[].downloadUrl``). Dated TOC URLs (``YYYY-MM-01_...``) are moved to
the requested month.

Every URL is checked against the fetch allowlist. A URL on a host that is not already allowed
is **reported** (``status: blocked_host``) and never fetched; hosts found in a TOC are never
added to the allowlist automatically.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx

from app.etl import fetch
from app.etl.config import SourcesFile, load_sources
from app.etl.tic.networks import TicNetwork

_DATED = re.compile(r"/(\d{4}-\d{2})-01_")
TOC_CAP = 100_000_000


@dataclass
class Discovery:
    source_id: str
    status: str  # ok | not_found | blocked_host | toc_error
    url: str | None = None  # redacted only for logging; the real URL is kept for the fetch
    toc_url: str = ""
    candidates: int = 0
    blocked: list[str] = field(default_factory=list)
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["url_redacted"] = fetch.redact(self.url) if self.url else None
        d.pop("url")
        d["blocked"] = [fetch.redact(u) for u in self.blocked]
        return d


def month_url(url: str, month: str | None) -> str:
    """Move a dated TOC URL (``.../2026-10-01_X_index.json``) to ``month`` (YYYY-MM)."""
    if not month:
        return url
    return _DATED.sub(f"/{month}-01_", url, count=1)


def toc_urls(doc: Any, toc_url: str) -> list[str]:
    """Every in-network file URL a TOC / listing names."""
    out: list[str] = []
    if isinstance(doc, dict) and "reporting_structure" in doc:
        for rs in doc["reporting_structure"] or []:
            for f in rs.get("in_network_files") or []:
                if f.get("location"):
                    out.append(f["location"])
    elif isinstance(doc, dict) and "files" in doc:  # Aetna / HealthSparq latest_metadata.json
        base = toc_url.rsplit("/", 1)[0] + "/"
        for f in doc["files"]:
            if f.get("fileSchema") == "IN_NETWORK_RATES" and f.get("filePath"):
                out.append(urljoin(base, f["filePath"]))
    elif isinstance(doc, dict) and "blobs" in doc:  # UHC blob listing
        for b in doc["blobs"]:
            if "in-network" in b.get("name", "") and b.get("downloadUrl"):
                out.append(b["downloadUrl"])
    else:
        raise ValueError("unrecognised table-of-contents shape")
    return list(dict.fromkeys(out))


def pick(net: TicNetwork, urls: list[str], allowed: list[str]) -> Discovery:
    d = Discovery(net.source_id, "not_found")
    rx = re.compile(net.match)
    cands = []
    for u in urls:
        v = u.replace(*net.rewrite) if net.rewrite else u
        if rx.search(fetch.redact(v)):
            cands.append(v)
    d.candidates = len(cands)
    d.blocked = fetch.blocked_urls(cands, allowed)
    ok = sorted((u for u in cands if u not in d.blocked), key=fetch.redact, reverse=True)
    if ok:
        d.status, d.url = "ok", ok[0]
    elif d.blocked:
        d.status = "blocked_host"
    return d


def discover(
    nets: list[TicNetwork],
    month: str | None = None,
    sources: SourcesFile | None = None,
    client: httpx.Client | None = None,
) -> list[Discovery]:
    sources = sources or load_sources()
    allowed = sources.fetch.allowed_domains
    cache: dict[str, list[str] | Exception] = {}
    out: list[Discovery] = []
    for net in nets:
        if not net.toc:
            out.append(Discovery(net.source_id, "toc_error", error="no discover.toc"))
            continue
        turl = month_url(sources.get(net.toc).url or "", month)
        if turl not in cache:
            try:
                body, final, _h = fetch.http_get_bytes(turl, allowed, TOC_CAP, client=client)
                cache[turl] = toc_urls(json.loads(body), final)
            except (fetch.FetchError, ValueError) as e:
                cache[turl] = e
        got = cache[turl]
        if isinstance(got, Exception):
            out.append(
                Discovery(net.source_id, "toc_error", toc_url=fetch.redact(turl), error=str(got))
            )
            continue
        d = pick(net, got, allowed)
        d.toc_url = fetch.redact(turl)
        out.append(d)
    return out
