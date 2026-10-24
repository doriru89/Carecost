"""V9 sweep (network): re-fetch every source and confirm its stored excerpts and ACR ratings still hold.

    python -m app.care_paths.verify_sources            # all sources
    python -m app.care_paths.verify_sources acr_chronic_shoulder_2022

Run it on a schedule (or before a review), not in unit CI. A missing excerpt means the page changed:
re-read it, update sources.yaml, and re-review the dependent paths (validator.dependents_of).
PDF sources need `pdftotext` on PATH.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path

from app.care_paths.loader import load_bundle
from app.care_paths.models import Source
from app.care_paths.text import normalize

_BLOCK = {"p", "li", "br", "div", "tr", "h1", "h2", "h3", "h4", "td", "th"}
_RATING = {
    "Usually Appropriate": "UA",
    "May Be Appropriate": "MBA",
    "May Be Appropriate (Disagreement)": "MBA",
    "Usually Not Appropriate": "UNA",
}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in _BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript"):
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if self.skip <= 0:
            self.out.append(data)


def to_text(raw: bytes) -> str:
    if raw[:5] == b"%PDF-":
        exe = shutil.which("pdftotext")
        if exe is None:
            raise RuntimeError("pdftotext is needed for PDF sources")
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "s.pdf"
            pdf.write_bytes(raw)
            subprocess.run([exe, str(pdf), str(Path(d) / "s.txt")], check=True)
            return (Path(d) / "s.txt").read_text(errors="replace")
    p = _Text()
    p.feed(raw.decode("utf-8", errors="replace"))
    return "".join(p.out)


def acr_ratings(text: str) -> dict[int, dict[str, str]]:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    out: dict[int, dict[str, str]] = {}
    cur: int | None = None
    for i, ln in enumerate(lines):
        m = re.fullmatch(r"Variant: (\d+)", ln)
        if m:
            n = int(m.group(1))
            if n in out:
                break
            out[n] = {}
            cur = n
            continue
        if cur is not None and ln in _RATING and i > 0:
            out[cur][normalize(lines[i - 1])] = _RATING[ln]
    return out


def check_source(sid: str, src: Source, fetch: Callable[[str], bytes]) -> list[str]:
    problems: list[str] = []
    raw_text = "\n".join(to_text(fetch(u)) for u in (src.pages or [src.url]))
    text = normalize(raw_text)
    for e in src.excerpts:
        if normalize(e) not in text:
            problems.append(f"{sid}: excerpt no longer on page: {e!r}")
    if src.acr_variants:
        live = acr_ratings(raw_text)
        for n, variant in src.acr_variants.items():
            for proc, rating in variant.ratings.items():
                got = live.get(n, {}).get(proc)
                if got != rating:
                    problems.append(f"{sid}: V{n} {proc!r} stored {rating}, page says {got}")
    return problems


def _httpx_fetch(url: str) -> bytes:
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (CareCost source check)"}
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=60)
    r.raise_for_status()
    return r.content


def main(argv: list[str]) -> int:
    bundle = load_bundle()
    ids = argv or [s for s, src in bundle.sources.items() if src.excerpts]
    bad = 0
    for sid in ids:
        try:
            problems = check_source(sid, bundle.sources[sid], _httpx_fetch)
        except Exception as exc:  # noqa: BLE001 - report and continue the sweep
            problems = [f"{sid}: fetch failed: {exc}"]
        for p in problems:
            print(p)
        bad += bool(problems)
        if not problems:
            print(f"{sid}: ok")
    print(f"{bad} source(s) need attention")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
