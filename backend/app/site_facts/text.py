"""Visible text of an HTML page, and the one quote-matching rule.

The cache keeps what a person sees on the page (no scripts, styles, hidden templates), one block
per line. A quote "is found verbatim" when it is a substring of that text after both sides have
every run of whitespace collapsed to one space. Nothing else is normalized: case, punctuation,
digits and words must match exactly.
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "head", "object"}
BLOCK = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
    "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "ul", "option", "button", "label", "summary", "details",
}  # fmt: skip
VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source",
        "track", "wbr", "param"}  # fmt: skip
_WS = re.compile(r"\s+")


class _Visible(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag in SKIP or ("hidden" in a and tag not in VOID):
            if tag not in VOID:
                self._skip += 1
            return
        if self._skip and tag not in VOID:
            self._skip += 1
            return
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if self._skip:
            if tag not in VOID:
                self._skip -= 1
            return
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title.append(data)
            return
        if not self._skip:
            self.parts.append(data)


def visible_text(html: str) -> str:
    """Title on the first line (``TITLE: ...``), then the visible text, one block per line."""
    p = _Visible()
    p.feed(html)
    p.close()
    lines = [_WS.sub(" ", ln).strip() for ln in "".join(p.parts).split("\n")]
    body = "\n".join(ln for ln in lines if ln)
    title = _WS.sub(" ", "".join(p.title)).strip()
    return (f"TITLE: {title}\n" if title else "") + body + "\n"


def jsonld_blocks(html: str) -> list[str]:
    """``<script type="application/ld+json">`` bodies (schema.org hours often live only here).
    Not part of the visible text, so never quotable; recorded only as a manifest flag."""
    return re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I
    )


def collapse(s: str) -> str:
    return _WS.sub(" ", s).strip()


def quote_found(quote: str, page_text: str) -> bool:
    q = collapse(quote)
    return bool(q) and q in collapse(page_text)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href, self._buf = dict(attrs).get("href"), []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, collapse("".join(self._buf))))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._buf.append(data)


SERVICE_LINK = re.compile(
    r"\b(services?|what we treat|conditions|treatments?|hours|x-?ray|imaging|our care|"
    r"specialt(y|ies)|procedures?)\b",
    re.I,
)


LEGAL_LINK = re.compile(r"(?i)terms|privacy|policy|cookie|legal|careers?|jobs")


def related_links(html: str, base_url: str, limit: int = 6) -> list[str]:
    """Same-host links whose anchor text or path names services or hours (follow-up pages)."""
    from urllib.parse import urljoin, urlparse

    p = _Links()
    p.feed(html)
    host = urlparse(base_url).hostname
    out: list[str] = []
    for href, text in p.links:
        u = urljoin(base_url, href).split("#")[0]
        pu = urlparse(u)
        if pu.scheme != "https" or pu.hostname != host or u.rstrip("/") == base_url.rstrip("/"):
            continue
        if LEGAL_LINK.search(text) or LEGAL_LINK.search(pu.path):
            continue
        if SERVICE_LINK.search(text) or SERVICE_LINK.search(pu.path.replace("-", " ")):
            if u not in out:
                out.append(u)
    base = urlparse(base_url).path.rstrip("/")
    out.sort(key=lambda u: not urlparse(u).path.startswith(base + "/"))  # own sub-pages first
    return out[:limit]
