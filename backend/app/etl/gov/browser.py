"""Plain-browser downloads for publishers that refuse scripted HTTP (mass.gov, D28).

What this does, and what it deliberately does not do (Austin, 2026-10-24):

* opens the publisher's own landing page in a normal, headed Chromium (Playwright's bundled
  build) with its own real user agent, and clicks the download link the way a person would;
* the only setting changed is Chrome's ordinary user preference "Download PDF files instead of
  automatically opening them in Chrome" (``plugins.always_open_pdf_externally``), so a PDF lands
  on disk as a file instead of in the built-in viewer;
* never changes the fingerprint, never sets a user agent, never loads stealth plugins, never
  solves or bypasses a captcha;
* a 403 or a captcha / bot-check page stops the run with ``BrowserBlocked``. The source then
  falls back to ``access: manual`` (Austin downloads it, the ETL imports it). No escalation.

The bytes then go through the same content-addressed store as every other fetch.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from app.etl.fetch import url_allowed

CHALLENGE_MARKERS = re.compile(
    r"captcha|are you a robot|verify you are human|access denied|request blocked|"
    r"cf-challenge|challenge-platform|bot detection",
    re.I,
)
CHROME_PREFS = {"plugins": {"always_open_pdf_externally": True}}


class BrowserBlocked(RuntimeError):
    """403 or a challenge page: stop and switch the source to access: manual."""


@dataclass
class BrowserDownload:
    landing_url: str
    link_url: str
    final_url: str
    path: Path
    suggested_filename: str
    user_agent: str
    landing_status: int


def check_landing(status: int, title: str, body: str, url: str) -> None:
    """The stop rule, separated so it is unit-tested without a browser."""
    if status == 403:
        raise BrowserBlocked(f"HTTP 403 on {url}")
    if CHALLENGE_MARKERS.search(title or "") or (
        status != 200 and CHALLENGE_MARKERS.search(body or "")
    ):
        raise BrowserBlocked(f"challenge page on {url}: {title!r}")
    if status != 200:
        raise BrowserBlocked(f"HTTP {status} on {url}")


def download_via_page(
    landing_url: str,
    link_href: str,
    dest_dir: Path,
    allowed: list[str],
    *,
    headless: bool = False,
    timeout_ms: int = 120_000,
) -> BrowserDownload:
    """Open ``landing_url``, click the link whose href contains ``link_href``, save the file.

    The landing page, the link and the final download URL must be https on the allowlist."""
    from playwright.sync_api import sync_playwright  # etl extra only

    for u in (landing_url, urljoin(landing_url, link_href)):
        if not url_allowed(u, allowed):
            raise BrowserBlocked(f"{u} is not https on the domain allowlist")
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="carecost-chrome-") as ud:
        (Path(ud) / "Default").mkdir()
        (Path(ud) / "Default" / "Preferences").write_text(json.dumps(CHROME_PREFS))
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(ud, headless=headless, accept_downloads=True)
            try:
                page = ctx.new_page()
                resp = page.goto(landing_url, wait_until="domcontentloaded", timeout=timeout_ms)
                status = resp.status if resp else 0
                ua = str(page.evaluate("navigator.userAgent"))
                check_landing(status, page.title(), page.inner_text("body")[:5000], landing_url)
                link = page.locator(f'a[href*="{link_href}"]').first
                if link.count() == 0:
                    raise BrowserBlocked(f"no link containing {link_href!r} on {landing_url}")
                href = urljoin(landing_url, link.get_attribute("href") or "")
                with page.expect_download(timeout=timeout_ms) as info:
                    link.click()
                dl = info.value
                fail = dl.failure()
                if fail:
                    raise BrowserBlocked(f"download failed: {fail}")
                if not url_allowed(dl.url, allowed):
                    raise BrowserBlocked(
                        f"download left the allowlist: {urlparse(dl.url).hostname}"
                    )
                out = dest_dir / Path(dl.suggested_filename).name
                dl.save_as(out)
                head = out.read_bytes()[:2048]
                if head.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
                    raise BrowserBlocked(f"{href} returned an HTML page, not a file")
                return BrowserDownload(
                    landing_url=landing_url,
                    link_url=href,
                    final_url=dl.url,
                    path=out,
                    suggested_filename=out.name,
                    user_agent=ua,
                    landing_status=status,
                )
            finally:
                ctx.close()
