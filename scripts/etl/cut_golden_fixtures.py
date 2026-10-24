"""Cut the ETL golden fixtures from real hospital / insurer files.

Fixtures are never hand-written: every row below is sliced out of a real source
file, and MANIFEST.yaml records the source basename + sha256 + selection rule so
anyone can re-cut them. Streaming only (csv row by row, ijson for JSON).

Usage (from backend/):
    uv run python ../scripts/etl/cut_golden_fixtures.py --raw-dir <dir with the 12 MRFs> \
        --tic-dir <dir with bcbs_tic.json.gz>
"""

from __future__ import annotations

import argparse
import codecs
import csv
import gzip
import hashlib
import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import ijson
import yaml

csv.field_size_limit(10**9)

OUT = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "mrf"

# (source_id, file, encoding)
CSV_FILES = {
    "mgh_mrf": ("mgh_standardcharges.zip", "latin-1"),
    "brigham_mrf": ("brigham_standardcharges.zip", "latin-1"),
    "faulkner_mrf": ("faulkner_standardcharges.zip", "latin-1"),
    "bmc_mrf": ("bmc_standardcharges.zip", "utf-8"),
    "bmc_brighton_mrf": ("bmc_brighton_standardcharges.zip", "utf-8"),
    "cha_mrf": ("cha_standardcharges.csv", "utf-8"),
    "tufts_mrf": ("tufts_standardcharges.zip", "latin-1"),
    "franciscan_mrf": ("franciscan_standardcharges.csv", "latin-1"),
}
JSON_FILES = {
    "bidmc_mrf": "bidmc_standardcharges.json",
    "childrens_mrf": "childrens_standardcharges.json",
    "dana_farber_mrf": "dana_farber_standardcharges.json",
    "mtauburn_mrf": "mtauburn_standardcharges.json",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def open_csv_bytes(path: Path) -> io.BufferedIOBase:
    if path.suffix == ".zip":
        zf = zipfile.ZipFile(path)
        name = [n for n in zf.namelist() if not n.startswith("__MACOSX") and not n.endswith("/")][0]
        return zf.open(name)  # type: ignore[return-value]
    return path.open("rb")


def csv_rows(path: Path, enc: str):
    fh = io.TextIOWrapper(open_csv_bytes(path), encoding=enc, errors="strict", newline="")
    yield from csv.reader(fh)


def write_csv(dest: Path, rows: list[list[str]], enc: str) -> None:
    with dest.open("w", encoding=enc, newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerows(rows)


def cut_csv(
    sid: str, raw: Path, enc: str, dest: Path, code: str | None, meta_only: bool = False
) -> int:
    it = csv_rows(raw, enc)
    out = [next(it), next(it)]
    if meta_only:
        write_csv(dest, out, enc)
        return 0
    header = next(it)
    out.append(header)
    hl = [h.strip().lower() for h in header]
    code_idx = [i for i, h in enumerate(hl) if h.startswith("code|") and not h.endswith("|type")]
    n = 0
    for row in it:
        if any(i < len(row) and row[i].strip() == code for i in code_idx):
            out.append(row)
            n += 1
    write_csv(dest, out, enc)
    return n


def _jsonable(o: Any) -> Any:
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() and "." not in str(o) else float(o)
    raise TypeError(type(o))


def _open_nobom(path: Path):
    f = path.open("rb")
    if f.read(3) != codecs.BOM_UTF8:
        f.seek(0)
    return f


def json_meta(path: Path) -> dict[str, Any]:
    """Top-level scalar/object fields, i.e. everything except the two big arrays."""
    meta: dict[str, Any] = {}
    with _open_nobom(path) as f:
        for key, value in ijson.kvitems(f, ""):
            if key in ("standard_charge_information", "modifier_information"):
                continue
            meta[key] = value
    return meta


def cut_json(
    sid: str,
    raw: Path,
    dest: Path,
    pred,
    n_modinfo: int = 2,
    meta_only: bool = False,
) -> int:
    has_bom = raw.open("rb").read(3) == codecs.BOM_UTF8
    doc = json_meta(raw)
    items: list[Any] = []
    if not meta_only:
        mods: list[Any] = []
        with _open_nobom(raw) as f:
            for m in ijson.items(f, "modifier_information.item"):
                if len(mods) >= n_modinfo:
                    break
                mods.append(m)
        if mods:
            doc["modifier_information"] = mods
        with _open_nobom(raw) as f:
            for it in ijson.items(f, "standard_charge_information.item"):
                if pred(it):
                    items.append(it)
        doc["standard_charge_information"] = items
    text = json.dumps(doc, default=_jsonable, indent=1)
    data = (codecs.BOM_UTF8 if has_bom else b"") + text.encode("utf-8")
    dest.write_bytes(data)
    return len(items)


def has_code(code: str):
    def pred(it: dict[str, Any]) -> bool:
        return any(str(c.get("code", "")).strip() == code for c in it.get("code_information") or [])

    return pred


def has_charge_key(key: str):
    def pred(it: dict[str, Any]) -> bool:
        return any(key in ch for ch in it.get("standard_charges") or [])

    return pred


def first_n(pred, n: int):
    seen = {"n": 0}

    def p(it: dict[str, Any]) -> bool:
        if seen["n"] >= n or not pred(it):
            return False
        seen["n"] += 1
        return True

    return p


def cut_tic(raw: Path, dest: Path, npi: int, code: str) -> dict[str, Any]:
    """BCBS TiC slice: provider_references that include `npi`, the in_network item
    for `code` restricted to those references, plus the first in_network item that
    carries a `percentage` price (any provider), restricted to its own references."""
    meta: dict[str, Any] = {}
    refs: dict[int, Any] = {}
    with gzip.open(raw, "rb") as f:
        for key, value in ijson.kvitems(f, ""):
            if key in ("provider_references", "in_network"):
                continue
            meta[key] = value
    with gzip.open(raw, "rb") as f:
        for pr in ijson.items(f, "provider_references.item"):
            refs[int(pr["provider_group_id"])] = pr
    bidmc_refs = {
        gid
        for gid, pr in refs.items()
        if any(npi in (g.get("npi") or []) for g in pr["provider_groups"])
    }
    target: Any = None
    pct_item: Any = None
    with gzip.open(raw, "rb") as f:
        for item in ijson.items(f, "in_network.item"):
            if target is None and item.get("billing_code") == code:
                rates = [
                    r
                    for r in item.get("negotiated_rates") or []
                    if set(r.get("provider_references") or []) & bidmc_refs
                ]
                if rates:
                    item = dict(item)
                    item["negotiated_rates"] = rates
                    target = item
            if pct_item is None:
                for r in item.get("negotiated_rates") or []:
                    if any(
                        p.get("negotiated_type") == "percentage"
                        for p in r.get("negotiated_prices") or []
                    ):
                        item = dict(item)
                        item["negotiated_rates"] = [r]
                        pct_item = item
                        break
            if target is not None and pct_item is not None:
                break
    used = set()
    for it in (target, pct_item):
        for r in it["negotiated_rates"]:
            used.update(r.get("provider_references") or [])
    doc = dict(meta)
    doc["provider_references"] = [refs[g] for g in sorted(used) if g in refs]
    doc["in_network"] = [target, pct_item]
    dest.write_text(json.dumps(doc, default=_jsonable, indent=1))
    return {"bidmc_refs": sorted(bidmc_refs & used)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--tic-dir", type=Path, required=True)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "meta").mkdir(exist_ok=True)
    manifest: dict[str, Any] = {"fixtures": {}, "meta": {}}

    def rec(name: str, sid: str, raw: Path, rule: str, n: int, **extra: Any) -> None:
        manifest["fixtures"][name] = {
            "source_id": sid,
            "source_file": raw.name,
            "source_sha256": sha256(raw),
            "selection": rule,
            "items_or_rows_selected": n,
            **extra,
        }
        print(name, n)

    r = a.raw_dir
    raw = r / CSV_FILES["brigham_mrf"][0]
    n = cut_csv("brigham_mrf", raw, "latin-1", OUT / "brigham_11102.csv", "11102")
    rec("brigham_11102.csv", "brigham_mrf", raw, "all rows with any code|N == 11102", n)
    raw = r / CSV_FILES["franciscan_mrf"][0]
    n = cut_csv("franciscan_mrf", raw, "latin-1", OUT / "franciscan_99213.csv", "99213")
    rec(
        "franciscan_99213.csv", "franciscan_mrf", raw, "all rows with any code|N == 99213 (wide)", n
    )
    raw = r / CSV_FILES["cha_mrf"][0]
    n = cut_csv("cha_mrf", raw, "utf-8", OUT / "cha_45378.csv", "45378")
    rec("cha_45378.csv", "cha_mrf", raw, "all rows with any code|N == 45378", n)
    raw = r / JSON_FILES["bidmc_mrf"]
    n = cut_json("bidmc_mrf", raw, OUT / "bidmc_73030.json", has_code("73030"))
    rec(
        "bidmc_73030.json",
        "bidmc_mrf",
        raw,
        "items with code 73030; first 2 modifier_information",
        n,
    )
    n = cut_json("bidmc_mrf", raw, OUT / "bidmc_99213.json", has_code("99213"))
    rec(
        "bidmc_99213.json",
        "bidmc_mrf",
        raw,
        "items with code 99213; first 2 modifier_information",
        n,
    )
    raw = r / JSON_FILES["dana_farber_mrf"]
    n = cut_json(
        "dana_farber_mrf",
        raw,
        OUT / "dana_farber_modifiers.json",
        first_n(has_charge_key("modifiers"), 1),
    )
    rec(
        "dana_farber_modifiers.json",
        "dana_farber_mrf",
        raw,
        "first item with non-standard charge key 'modifiers'",
        n,
    )

    for sid, (fname, enc) in CSV_FILES.items():
        raw = r / fname
        cut_csv(sid, raw, enc, OUT / "meta" / f"{sid}.csv", None, meta_only=True)
        manifest["meta"][sid] = {"source_file": fname, "source_sha256": sha256(raw)}
    for sid, fname in JSON_FILES.items():
        raw = r / fname
        cut_json(sid, raw, OUT / "meta" / f"{sid}.json", None, meta_only=True)
        manifest["meta"][sid] = {"source_file": fname, "source_sha256": sha256(raw)}

    raw = a.tic_dir / "bcbs_tic.json.gz"
    info = cut_tic(raw, OUT / "bcbs_tic_73030_bidmc.json", 1548202641, "73030")
    rec(
        "bcbs_tic_73030_bidmc.json",
        "bcbs_tic",
        raw,
        "in_network 73030 restricted to provider_references containing NPI 1548202641, "
        "plus first in_network item with a percentage price",
        2,
        **info,
    )
    (OUT / "MANIFEST.yaml").write_text(
        "# Generated by scripts/etl/cut_golden_fixtures.py. Do not edit by hand.\n"
        + yaml.safe_dump(manifest, sort_keys=True)
    )


if __name__ == "__main__":
    main()
