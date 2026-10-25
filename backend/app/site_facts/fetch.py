"""Polite fetch of a site's own pages into the evidence cache.

Rules (brief S0.2, Common): plain HTTP through the ETL's one entry point (``app.etl.fetch``:
https only, host allowlist on every redirect hop, size cap) with its one honest user agent; the
host's robots.txt is read first and obeyed; at most one request per second per host; plain
headless Chromium (no stealth, same user agent) only for a page marked ``needs_js`` or whose plain
text is nearly empty. A page that answers 403/429, a challenge page, or a robots disallow is
recorded and left for a person (``status: manual``); it is never retried another way.

Cache (gitignored): ``data/sites/site_facts/cache/<key>.txt`` = visible text exactly as the
verifier reads it, ``<key>.json`` = metadata. ``page_sha256`` is the sha256 of the ``.txt``.
Manifest (committed): ``data/sites/site_facts/manifest.yaml`` = one row per URL.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yaml

from app.etl.fetch import USER_AGENT, FetchError, capped_chunks, http_open
from app.site_facts.paths import CACHE_DIR, MANIFEST
from app.site_facts.text import jsonld_blocks, related_links, sha256_text, visible_text

ROBOTS_TOKEN = "CareCost-ETL"  # the product token of USER_AGENT, as robots.txt groups match it
MIN_INTERVAL_S = 1.0
PAGE_CAP = 8_000_000
THIN_TEXT_CHARS = 400  # below this the plain fetch "could not read" the page -> try JS once
CHALLENGE_MARKS = (
    "Just a moment...", "Attention Required! | Cloudflare", "cf-chl-", "captcha",
    "Access Denied", "Request unsuccessful. Incapsula", "Pardon Our Interruption",
)  # fmt: skip


def cache_key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:20]


@dataclass
class PageRecord:
    url: str
    status: str  # ok | manual | error
    method: str = "http"  # http | playwright
    final_url: str | None = None
    http_status: int | None = None
    fetched_at: str | None = None
    page_sha256: str | None = None
    text_chars: int = 0
    jsonld_hours: bool = False  # schema.org openingHours present (not quotable, flag only)
    reason: str | None = None  # why manual / error
    site_ids: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)  # same-host services / hours links


class Fetcher:
    """One per run. ``http`` and ``browser`` are injectable for tests."""

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        *,
        http: Callable[[str, list[str]], tuple[int, str, bytes]] | None = None,
        browser: Callable[[str], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        allow_js: bool = True,
    ) -> None:
        self.cache_dir = cache_dir
        self._http = http or _http_get
        self._browser = browser
        self._sleep, self._clock = sleep, clock
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.allow_js = allow_js
        self.requests = 0

    # ------------------------------------------------------------------ politeness
    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = self._clock() - last
            if gap < MIN_INTERVAL_S:
                self._sleep(MIN_INTERVAL_S - gap)
        self._last[host] = self._clock()

    def robots_allows(self, url: str) -> tuple[bool, str | None]:
        u = urlparse(url)
        host = u.hostname or ""
        if host not in self._robots:
            self._wait(host)
            self.requests += 1
            try:
                code, _final, body = self._http(
                    f"https://{host}/robots.txt", [host, *_www_twin(host)]
                )
            except FetchError as e:
                self._robots[host] = None
                return False, f"robots.txt unreadable: {e}"
            rp = urllib.robotparser.RobotFileParser()
            if code in (401, 403) or code >= 500:
                rp.parse(["User-agent: *", "Disallow: /"])  # RFC 9309: unreachable = disallow all
            elif code >= 400:
                rp.parse([])  # no robots.txt: everything allowed
            else:
                rp.parse(body.decode("utf-8", "replace").splitlines())
            self._robots[host] = rp
        parser = self._robots[host]
        if parser is None:
            return False, "robots.txt unreadable"
        if parser.can_fetch(ROBOTS_TOKEN, url):
            return True, None
        return False, "robots.txt disallows"

    def get_raw(self, url: str) -> bytes:
        """A sitemap or location-finder document for discovery: robots + rate limit, no cache."""
        ok, why = self.robots_allows(url)
        if not ok:
            raise FetchError(f"{why}: {url}")
        host = urlparse(url).hostname or ""
        self._wait(host)
        self.requests += 1
        code, _final, body = self._http(url, [host, *_www_twin(host)])
        if code != 200:
            raise FetchError(f"HTTP {code} for {url}")
        return body

    # ------------------------------------------------------------------ fetch
    def fetch(self, url: str, *, needs_js: bool = False, refresh: bool = False) -> PageRecord:
        host = urlparse(url).hostname or ""
        cached = self.load_meta(url)
        if cached and not refresh and cached.status == "ok":
            return cached
        ok, why = self.robots_allows(url)
        if not ok:
            return self._save(PageRecord(url=url, status="manual", reason=why))
        html_text, code, final, method = "", None, None, "http"
        if not needs_js:
            self._wait(host)
            self.requests += 1
            try:
                code, final, body = self._http(url, [host, *_www_twin(host)])
            except FetchError as e:
                return self._save(PageRecord(url=url, status="error", reason=str(e)))
            if code in (401, 403, 429, 503):
                return self._save(PageRecord(url=url, status="manual", http_status=code,
                                             reason=f"HTTP {code}: blocked or rate-limited"))  # fmt: skip
            if code != 200:
                return self._save(PageRecord(url=url, status="error", http_status=code,
                                             reason=f"HTTP {code}"))  # fmt: skip
            html_text = body.decode("utf-8", "replace")
        text = visible_text(html_text) if html_text else ""
        if _challenge(html_text, text):
            return self._save(PageRecord(url=url, status="manual", http_status=code,
                                         reason="challenge / bot-check page"))  # fmt: skip
        if (needs_js or len(text) < THIN_TEXT_CHARS) and self.allow_js:
            self._wait(host)
            self.requests += 1
            try:
                html_text = (self._browser or _browser_get)(url)
            except Exception as e:  # noqa: BLE001 - any browser failure is "manual"
                return self._save(PageRecord(url=url, status="manual", http_status=code,
                                             reason=f"plain fetch thin ({len(text)} chars); "
                                             f"browser failed: {type(e).__name__}"))  # fmt: skip
            text, method = visible_text(html_text), "playwright"
            if _challenge(html_text, text):
                return self._save(PageRecord(url=url, status="manual", method=method,
                                             reason="challenge / bot-check page"))  # fmt: skip
        if len(text) < THIN_TEXT_CHARS:
            return self._save(PageRecord(url=url, status="manual", method=method, http_status=code,
                                         reason=f"page text too thin ({len(text)} chars)"))  # fmt: skip
        rec = PageRecord(
            url=url, status="ok", method=method, final_url=final or url, http_status=code,
            fetched_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            page_sha256=sha256_text(text), text_chars=len(text),
            jsonld_hours=any("openingHours" in b for b in jsonld_blocks(html_text)),
            related=related_links(html_text, final or url),
        )  # fmt: skip
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{cache_key(url)}.txt").write_text(text, encoding="utf-8")
        return self._save(rec)

    # ------------------------------------------------------------------ cache io
    def _save(self, rec: PageRecord) -> PageRecord:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{cache_key(rec.url)}.json").write_text(
            json.dumps(asdict(rec), indent=1), encoding="utf-8"
        )
        return rec

    def load_meta(self, url: str) -> PageRecord | None:
        return self.load_meta_path(self.cache_dir / f"{cache_key(url)}.json")

    @staticmethod
    def load_meta_path(p: Path) -> PageRecord | None:
        if not p.is_file():
            return None
        return PageRecord(**json.loads(p.read_text(encoding="utf-8")))


def cached_text(url: str, cache_dir: Path = CACHE_DIR) -> str | None:
    p = cache_dir / f"{cache_key(url)}.txt"
    return p.read_text(encoding="utf-8") if p.is_file() else None


def _www_twin(host: str) -> list[str]:
    return [host[4:]] if host.startswith("www.") else [f"www.{host}"]


def _challenge(html_text: str, text: str) -> bool:
    head = (html_text[:20000] + text[:2000]).lower()
    return len(text) < 3000 and any(m.lower() in head for m in CHALLENGE_MARKS)


def _http_get(url: str, allowed: list[str]) -> tuple[int, str, bytes]:
    with http_open(url, allowed, timeout_s=30) as (resp, final):
        if resp.status_code != 200:
            return resp.status_code, final, b""
        return 200, final, b"".join(capped_chunks(resp, PAGE_CAP, url))


def _browser_get(url: str) -> str:
    """Plain headless Chromium: no stealth plugins, no fingerprint changes, the same honest
    user agent as the HTTP fetch. Waits for network idle, returns the rendered HTML."""
    from playwright.sync_api import sync_playwright  # etl extra only

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            page = b.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=45000)
            return page.content()
        finally:
            b.close()


# ---------------------------------------------------------------------- manifest


def write_manifest(records: list[PageRecord], path: Path = MANIFEST) -> None:
    rows: list[dict[str, Any]] = []
    for r in sorted(records, key=lambda r: r.url):
        d = {k: v for k, v in asdict(r).items() if v not in (None, [], False, 0) or k == "status"}
        rows.append(d)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# GENERATED by `python -m app.site_facts fetch`. One row per fetched URL; the page text\n"
        "# itself is in the gitignored cache (data/sites/site_facts/cache/), keyed by URL.\n"
        + yaml.safe_dump({"version": 1, "pages": rows}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_manifest(path: Path = MANIFEST) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return {r["url"]: r for r in (yaml.safe_load(path.read_text()) or {}).get("pages", [])}
