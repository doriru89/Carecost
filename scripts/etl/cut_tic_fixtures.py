"""Cut the TiC golden fixtures (backend/tests/fixtures/tic/) from real October 2026 files.

Nothing is hand-written: each fixture is a byte-for-byte JSON re-serialisation of real items,
rate groups and provider references, chosen by the rule recorded in MANIFEST.yaml (with the
source basename and sha256). Numbers keep their source text ("1243.2000").

Selection per fixture: a few target items, the rate groups (at most --max-rgs per item) whose
provider_references hit the chosen TINs / NPIs, every provider reference those rate groups
name, plus the file's first in_network item (a non-target item the scanner must skip).

Usage (from backend/, after `python -m app.etl tic run --local-dir ...` built the indexes):
    uv run python ../scripts/etl/cut_tic_fixtures.py --raw-dir ../data/raw/tic
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import yaml

from app.etl.config import Paths
from app.etl.tic.index import load_index
from app.etl.tic.networks import get_network
from app.etl.tic.run import current_dir
from app.etl.tic.zran import file_fetcher, read_raw_range

OUT = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "tic"


class Raw(str):
    """A number kept as its source text."""


def loads(b: bytes) -> Any:
    return json.loads(b, parse_float=Raw, parse_int=Raw)


def dump(o: Any, indent: int | None = None, lvl: int = 0) -> str:
    nl = "" if indent is None else "\n" + " " * (indent * (lvl + 1))
    end = "" if indent is None else "\n" + " " * (indent * lvl)
    sep = ":" if indent is None else ": "
    if isinstance(o, Raw):
        return str(o)
    if isinstance(o, dict):
        if not o:
            return "{}"
        return (
            "{"
            + ",".join(nl + json.dumps(k) + sep + dump(v, indent, lvl + 1) for k, v in o.items())
            + end
            + "}"
        )
    if isinstance(o, list):
        if not o:
            return "[]"
        return "[" + ",".join(nl + dump(v, indent, lvl + 1) for v in o) + end + "]"
    return json.dumps(o)


def digits(v: Any) -> str:
    return "".join(c for c in str(v) if c.isdigit())


def cut(
    sid: str,
    raw_dir: Path,
    codes: list[str],
    tins: set[str],
    npis: set[str],
    max_rgs: int,
    want_pct: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    net = get_network(sid)
    d = current_dir(Paths.resolve(), sid)
    assert d is not None, f"run `tic run` for {sid} first"
    idx = load_index(d)
    path = next(raw_dir.rglob(net.basename))
    f = file_fetcher(str(path))
    m = idx.meta
    rd = lambda a, b: read_raw_range(idx.checkpoints, a, b, f, m.container, m.comp_bytes)  # noqa: E731
    head_raw = rd(0, idx.items[0].raw_start)
    a, b = m.provider_references_span
    refs = loads(rd(a, b))
    hit = set()
    for r in refs:
        for g in r.get("provider_groups") or []:
            if (
                digits((g.get("tin") or {}).get("value")) in tins
                or {str(n) for n in g.get("npi") or []} & npis
            ):
                hit.add(int(r["provider_group_id"]))
    header = loads(head_raw[: head_raw.find(b'"provider_references"')].rstrip().rstrip(b",") + b"}")
    items = [loads(rd(idx.items[0].raw_start, idx.items[0].raw_end))]  # first item: not a target
    items[0]["negotiated_rates"] = items[0]["negotiated_rates"][:1]
    pct_done = not want_pct
    for code in codes:
        for ref in idx.items_for({code}):
            it = loads(rd(ref.raw_start, ref.raw_end))
            keep = [
                rg
                for rg in it["negotiated_rates"]
                if {int(x) for x in rg.get("provider_references") or []} & hit
            ][:max_rgs]
            if not pct_done:
                pct = [
                    rg
                    for rg in it["negotiated_rates"]
                    if any(
                        p.get("negotiated_type") == "percentage" for p in rg["negotiated_prices"]
                    )
                ][:1]
                if pct:
                    keep += [rg for rg in pct if rg not in keep]
                    pct_done = True
            it["negotiated_rates"] = keep
            if keep:
                items.append(it)
    used = {
        int(x)
        for it in items
        for rg in it["negotiated_rates"]
        for x in rg.get("provider_references") or []
    }
    doc = dict(header)
    doc["provider_references"] = [r for r in refs if int(r["provider_group_id"]) in used]
    doc["in_network"] = items
    rule = (
        f"items {codes} (+ the file's first item, 1 rate group); rate groups hitting TINs "
        f"{sorted(tins)} / NPIs {sorted(npis)} (max {max_rgs} per item)"
        + ("; plus one rate group with a percentage price" if want_pct else "")
        + "; every provider reference those rate groups name"
    )
    return doc, {
        "source_id": sid,
        "source_file": net.basename,
        "source_sha256": m.source_sha256,
        "selection": rule,
    }


def write_gzip_two_members(doc: dict[str, Any], p: Path) -> None:
    """Member 1 = header + provider_references, member 2 = in_network (UHC's layout)."""
    text = dump(doc)
    cut_at = text.index('"in_network"')
    with p.open("wb") as f:
        for part in (text[:cut_at], text[cut_at:]):
            f.write(gzip.compress(part.encode(), mtime=0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True, type=Path)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    afc = {"272343207"}
    man: dict[str, Any] = {}
    jobs = [
        (
            "bcbs_hmo_blue_slice.json.gz",
            "tic_bcbs_ma_hmo_blue_fi",
            ["99203", "73030", "99213"],
            afc | {"042807148"},
            {"1548202641"},
            4,
            True,
            "gzip2",
        ),
        (
            "hphc_a008_slice.zip",
            "tic_hphc_a008_p1",
            ["99203", "99213", "99051"],
            afc,
            set(),
            4,
            False,
            "zip",
        ),
        (
            "mgb_hmo_slice.json.gz",
            "tic_mgb_hp_commercial_hmo",
            ["99203", "99213"],
            afc,
            set(),
            4,
            False,
            "gzip",
        ),
        (
            "aetna_ppo_slice.json.gz",
            "tic_aetna_ppo_pl_3j4",
            ["S9083"],
            afc | {"455391610", "352533673"},
            set(),
            4,
            False,
            "gzip",
        ),
        (
            "uhc_choice_hmo_slice.json.gz",
            "tic_uhc_choice_hmo_560",
            ["99203", "99213", "S9083"],
            afc,
            set(),
            3,
            False,
            "gzip2",
        ),
    ]
    for name, sid, codes, tins, npis, mx, pct, kind in jobs:
        doc, meta = cut(sid, a.raw_dir, codes, tins, npis, mx, pct)
        p = OUT / name
        if kind == "zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(name.replace(".zip", ".json"), dump(doc, indent=1))
            p.write_bytes(buf.getvalue())
        elif kind == "gzip2":
            write_gzip_two_members(doc, p)
        else:
            p.write_bytes(gzip.compress(dump(doc).encode(), mtime=0))
        meta["fixture_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        meta["container"] = "zip" if kind == "zip" else "gzip"
        meta["format"] = {
            "gzip2": "compact JSON, 2 gzip members",
            "zip": "pretty-printed JSON in a zip",
            "gzip": "compact JSON",
        }[kind]
        meta["provider_references"] = len(doc["provider_references"])
        meta["in_network_items"] = len(doc["in_network"])
        man[name] = meta
        print(name, p.stat().st_size, meta["provider_references"], meta["in_network_items"])
    (OUT / "MANIFEST.yaml").write_text(
        "# Generated by scripts/etl/cut_tic_fixtures.py. Do not edit by hand.\n"
        + yaml.safe_dump({"fixtures": man}, sort_keys=True, width=100)
    )


if __name__ == "__main__":
    main()
