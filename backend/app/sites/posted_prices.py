"""P1 problem 9: read a clinic's own posted self-pay price page (plan §2.6 price checker).

    python -m app.sites.posted_prices [--site afc_watertown] [--as-of D]

Only the operator's own page (never Solv / MyChart / Zocdoc), only when its robots.txt allows the
path, through the ETL's one HTTP entry point (https, exact-host allowlist, size cap). Output per
site: ``data/sites/posted/<site_id>.json`` with every priced row as published, the normalized
table's sha256, and a diff against the cash prices in ``data/sites/curated.yaml``. Nothing is
written into the site registry automatically: a person approves the diff (Site.PostedCashPrice).

Readers by page format (from the real pages, 2026-10-24):

* ``afc_self_pay``: AFC Urgent Care ``/<town>/resources/self-pay/``: HTML tables of
  ``<td>label</td><td class="price">$N</td>`` under ``section-header`` divs. "A / B / C" labels
  with as many "/"-separated prices are split into one item each.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.robotparser
from datetime import date
from typing import Any
from urllib.parse import urlparse

import yaml

from app.etl.fetch import http_get_bytes
from app.sites.build import SITES_DIR

PAGES = {
    "afc_watertown": {
        "url": "https://www.afcurgentcare.com/watertown/resources/self-pay/",
        "format": "afc_self_pay",
    },
}
ALLOWED = ["www.afcurgentcare.com"]
UA = "CareCost-ETL"
PRICE = re.compile(r"^\$(\d[\d,]*(?:\.\d{2})?)$")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_afc(page: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    section = ""
    for m in re.finditer(
        r'<div class="section-header[^"]*">(.*?)</div>|<tr[^>]*>(.*?)</tr>', page, re.S
    ):
        if m.group(1) is not None:
            section = _text(m.group(1))
            continue
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", m.group(2), re.S)
        if len(cells) < 2 or "price" not in cells[-1][0]:
            continue
        label, raw = _text(cells[0][1]), _text(cells[-1][1])
        labels = [x.strip() for x in label.split(" / ")]
        prices = [x.strip() for x in raw.split(" / ")]
        if len(labels) > 1 and len(labels) == len(prices) and all(PRICE.match(p) for p in prices):
            stem = re.sub(r"\s*\d+\s*views?$", "", labels[0], flags=re.I)
            for k, (lab, p) in enumerate(zip(labels, prices, strict=True)):
                full = f"{stem} {lab}" if k and lab[:1].isdigit() else lab
                amt = float(PRICE.match(p).group(1).replace(",", ""))  # type: ignore[union-attr]
                items.append({"section": section, "label": full, "raw": raw, "amount": amt})
            continue
        pm = PRICE.match(raw)
        items.append({"section": section, "label": label, "raw": raw,
                      "amount": float(pm.group(1).replace(",", "")) if pm else None})  # fmt: skip
    return items


def robots_allows(url: str) -> bool:
    u = urlparse(url)
    body, _f, _h = http_get_bytes(f"{u.scheme}://{u.netloc}/robots.txt", ALLOWED, 1_000_000)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines())
    return rp.can_fetch(UA, url)


def _tokens(s: str) -> set[str]:
    return set(
        re.findall(r"[a-z0-9]+", s.lower().replace("x-ray", "xray").replace("x ray", "xray"))
    )


def diff(items: list[dict[str, Any]], curated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each curated cash price vs the page: the page row whose words contain all of the curated
    label's words (shortest such label). -> only the differences."""
    out = []
    for c in curated:
        want = _tokens(c["label"])
        cands = sorted(
            (i for i in items if want <= _tokens(i["label"])), key=lambda i: len(i["label"])
        )
        if not cands:
            out.append({"item_id": c["item_id"], "label": c["label"], "change": "not_on_page"})
        elif cands[0]["amount"] != c["amount"]:
            out.append({"item_id": c["item_id"], "label": c["label"], "change": "amount",
                        "curated": c["amount"], "page": cands[0]["amount"], "page_label": cands[0]["label"]})  # fmt: skip
    return out


def run(site_id: str, as_of: date) -> dict[str, Any]:
    cfg = PAGES[site_id]
    if not robots_allows(cfg["url"]):
        raise RuntimeError(f"{site_id}: robots.txt disallows {cfg['url']}")
    body, final, _h = http_get_bytes(cfg["url"], ALLOWED, 5_000_000)
    if final.rstrip("/") != cfg["url"].rstrip("/"):
        raise RuntimeError(f"{site_id}: redirected to {final} (checker rejects a redirect)")
    items = parse_afc(body.decode("utf-8", "replace"))
    priced = [i for i in items if i["amount"] is not None]
    if not priced:
        raise RuntimeError(f"{site_id}: 0 priced rows (layout changed?)")
    norm = json.dumps([[i["section"], i["label"], i["raw"]] for i in items], sort_keys=True)
    curated = yaml.safe_load((SITES_DIR / "curated.yaml").read_text())
    cur = next((s for s in curated["sites"] if s["id"] == site_id), {})
    return {
        "site_id": site_id, "format": cfg["format"], "source_url": cfg["url"], "final_url": final,
        "robots": "allowed", "checked_at": as_of.isoformat(),
        "page_sha256": hashlib.sha256(norm.encode()).hexdigest(),
        "rows": len(items), "priced_rows": len(priced), "items": items,
        "diff_vs_curated": diff(items, cur.get("cash_prices") or []),
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.sites.posted_prices")
    p.add_argument("--site", default="all")
    p.add_argument("--as-of", default=None)
    a = p.parse_args(argv)
    as_of = date.fromisoformat(a.as_of) if a.as_of else date.today()
    rc = 0
    for sid in PAGES if a.site == "all" else [a.site]:
        try:
            out = run(sid, as_of)
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"FAIL   {sid}: {e}")
            rc = 1
            continue
        d = SITES_DIR / "posted"
        d.mkdir(exist_ok=True)
        (d / f"{sid}.json").write_text(json.dumps(out, indent=1) + "\n")
        print(f"POSTED {sid}: {out['priced_rows']} priced of {out['rows']} rows, sha {out['page_sha256'][:12]}, "
              f"{len(out['diff_vs_curated'])} differences vs curated.yaml")  # fmt: skip
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
