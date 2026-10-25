"""Write the runtime quote pack (``quote_pack.sqlite``) from real ETL outputs.

    cd backend
    uv run --frozen --extra etl python -m app.quote.pack \\
        --hospital-build /path/to/data/build/20261024-10d8a893 \\
        --tic-root /path/to/data/intermediate/tic \\
        [--gov-rows medicare_pfs.parquet --gov-sources gov_sources.yaml ...] \\
        --out ../data/runtime/quote_pack.sqlite

    # or the committed extract (what CI and the default Docker image use)
    uv run --frozen python -m app.quote.pack --from-extract --out ../data/runtime/quote_pack.sqlite

Reads with pyarrow (ETL side). The server reads the pack with stdlib sqlite3 (P1 problem 11).

Kept: rows of the codes we price (codes.yaml + visit codes + every care-path code), modifiers
none / 26 / TC, not ``excluded``. TiC NPIs only for provider groups with at most
``MAX_GROUP_NPIS`` NPIs (D6). Government fee-schedule rows come in the RateRow contract (A3's
readers) with a sources YAML in the extract's format (freshness inputs per source, D18).
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app.care_paths.loader import load_paths
from app.etl.config import load_sources
from app.etl.tic.networks import load_networks, target_codes
from app.quote.store import (
    MAX_GROUP_NPIS,
    PACKED_MODIFIERS,
    DataVersionInfo,
    Row,
    SourceMeta,
    make_row,
    pack_from_extract,
    standard_ref,
    tin_digits,
    write_pack,
)
from app.registries import all_hospitals

_HOSPITAL_COLS = [
    "row_ref", "row_id", "source_id", "source_kind", "row_kind", "code", "modifiers", "component",
    "billing_class", "setting", "rev_code", "payer_id", "product", "line_of_business", "plan_raw",
    "amount", "amount_method", "negotiated_pct", "discounted_cash", "gross", "stage_row",
]  # fmt: skip
_TIC_COLS = [
    *_HOSPITAL_COLS, "excluded", "tic_tin_value", "tic_tin_type", "tic_service_codes",
    "tic_business_name", "tic_negotiated_type", "tic_provider_group_id", "tic_group_ordinal",
]  # fmt: skip


def _date(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).date().isoformat()


def priced_codes() -> set[str]:
    """Every code a quote can look up: ETL code list, visit codes, every care-path code."""
    out = set(target_codes())
    for p in load_paths().values():
        for st in p.steps:
            out |= st.all_codes()
    return out | {"G0463"}


def hospital_rows(build: Path, codes: set[str]) -> tuple[list[Row], dict[str, SourceMeta]]:
    import sqlite3

    manifest = json.loads((build / "manifest.json").read_text())
    specs = {s.source_id: s for s in load_sources().sources}
    names = {k: v.name for k, v in all_hospitals().items()}
    sources: dict[str, SourceMeta] = {}
    for sid, m in manifest["sources"].items():
        if not m.get("sha256") or not m.get("raw_file"):
            continue  # failed fetch (no file in this build)
        spec = specs.get(sid)
        ent = spec.entity_id if spec else None
        sources[sid] = SourceMeta(
            source_id=sid, source_kind="hospital_mrf", publisher=names.get(ent or "", sid),
            source_file=m["raw_file"], source_sha256=m["sha256"],
            source_date=m.get("last_updated_on"), last_updated=m.get("last_updated_on"),
            fetched_at=_date(m["fetched_at"]), source_rule="hospital_mrf_365_days",
            our_rule="hospital_monthly",
        )  # fmt: skip
    db = sqlite3.connect(f"file:{build / 'rate_row.sqlite'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    q_code = ",".join("?" * len(codes))
    sql = (
        f"select {', '.join(_HOSPITAL_COLS)} from rate_row where excluded = 0 "
        f"and code in ({q_code})"
    )
    rows = []
    for rec in db.execute(sql, sorted(codes)):
        d = dict(rec)
        if d["source_id"] not in sources or d["modifiers"] not in PACKED_MODIFIERS:
            continue
        meta = sources[d["source_id"]]
        d["ref"] = standard_ref(meta, d["row_ref"], d["stage_row"])
        rows.append(make_row(d))
    db.close()
    return rows, sources


def tic_rows(
    tic_root: Path, codes: set[str]
) -> tuple[Iterator[Row], dict[str, SourceMeta], dict, str | None]:
    import pyarrow.parquet as pq

    nets = {n.source_id: n for n in load_networks()}
    aliases = yaml.safe_load((Path(__file__).resolve().parents[3] / "data" / "etl" /
                              "payer_aliases.yaml").read_text())["payers"]  # fmt: skip
    sources: dict[str, SourceMeta] = {}
    dirs: list[tuple[str, Path]] = []
    release: str | None = None
    for d in sorted(tic_root.glob("tic_*")):
        cur = d / "CURRENT"
        if not cur.exists() or d.name not in nets:
            continue
        sd = d / cur.read_text().strip()
        run = json.loads((sd / "run.json").read_text())
        n = nets[d.name]
        sources[d.name] = SourceMeta(
            source_id=d.name, source_kind="insurer_tic",
            publisher=f"{aliases[n.payer_id]['label']} · {n.label}",
            source_file=run["fetch"]["local_copy"],
            source_sha256=run["normalize"]["source_sha256"],
            source_date=run.get("last_updated_on"), last_updated=run.get("last_updated_on"),
            fetched_at=_date(run["fetch"]["fetched_at"]), source_rule="tic_45_days",
            our_rule="tic_monthly", payer_id=n.payer_id, product=n.product,
            network_label=n.label, line_of_business=n.lob,
        )  # fmt: skip
        # networks publish on their own day (Fallon 09-01, MGB 09-27, BCBS 10-01): the pack's
        # release is the newest month; each file's own date drives its freshness (D18)
        rel = "tic-" + run["last_updated_on"][:7]
        release = max(release or rel, rel)
        dirs.append((d.name, sd))

    groups: dict[tuple[str, int, int], tuple[str, ...]] = {}
    wanted: dict[str, set[tuple[int, int]]] = {}

    def gen() -> Iterator[Row]:
        for sid, sd in dirs:
            t = pq.read_table(sd / "rate_row.parquet", columns=_TIC_COLS,
                              filters=[("code", "in", sorted(codes))])  # fmt: skip
            meta = sources[sid]
            keys = wanted.setdefault(sid, set())
            for d in t.to_pylist():
                if d["excluded"] or d["modifiers"] not in PACKED_MODIFIERS:
                    continue
                d["ref"] = standard_ref(meta, d["row_ref"], d["stage_row"])
                r = make_row(d)
                keys.add((r.provider_group_id, r.group_ordinal))
                yield r
            g = pq.read_table(sd / "groups.parquet",
                              columns=["provider_group_id", "group_ordinal", "npis", "n_npi"])  # fmt: skip
            for rec in g.to_pylist():
                k = (rec["provider_group_id"], rec["group_ordinal"])
                if k in keys and 0 < rec["n_npi"] <= MAX_GROUP_NPIS:
                    groups[(sid, *k)] = tuple(sorted(tin_digits(n) for n in rec["npis"]))

    return gen(), sources, groups, release


def gov_rows(rows_file: Path, sources_yaml: Path, codes: set[str]):
    """RateRow-contract rows (parquet or CSV) + their sources (extract YAML format)."""
    doc = yaml.safe_load(sources_yaml.read_text())
    sources = {sid: SourceMeta(source_id=sid, **m) for sid, m in doc["sources"].items()}
    if rows_file.suffix == ".parquet":
        import pyarrow.parquet as pq

        recs: list[dict[str, Any]] = pq.read_table(rows_file).to_pylist()
    else:
        import csv

        with rows_file.open() as f:
            recs = list(csv.DictReader(f))
    out = []
    for d in recs:
        if d["code"] not in codes or d["source_id"] not in sources:
            continue
        if str(d.get("excluded", "")).lower() in ("1", "true"):
            continue
        meta = sources[d["source_id"]]
        d["ref"] = standard_ref(meta, d["row_ref"], int(d["stage_row"]))
        out.append(make_row(d))
    return out, sources


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hospital-build", type=Path)
    ap.add_argument("--tic-root", type=Path)
    ap.add_argument("--gov-rows", type=Path, action="append", default=[])
    ap.add_argument("--gov-sources", type=Path, action="append", default=[])
    ap.add_argument("--from-extract", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    t0 = time.perf_counter()
    if a.from_extract:
        n = pack_from_extract(a.out)
        print(f"{a.out}: {n} rows from the committed extract")
        return
    if not (a.hospital_build and a.tic_root):
        raise SystemExit("--hospital-build and --tic-root (or --from-extract)")
    codes = priced_codes()
    hrows, sources = hospital_rows(a.hospital_build, codes)
    trows, tsources, groups, release = tic_rows(a.tic_root, codes)
    sources.update(tsources)
    rows: list[Row] = list(hrows)
    for f, s in zip(a.gov_rows, a.gov_sources, strict=True):
        grows, gs = gov_rows(f, s, codes)
        rows += grows
        sources.update(gs)
    manifest = json.loads((a.hospital_build / "manifest.json").read_text())
    version = DataVersionInfo(manifest["build_id"], manifest["build_date"], release)

    def all_rows() -> Iterator[Row]:
        yield from rows
        yield from trows

    loaded = target_codes()
    n = write_pack(a.out, rows=all_rows(), sources=sources, version=version, codes=loaded,
                   group_npis=groups)  # fmt: skip
    # (groups is filled while write_pack streams the TiC rows, before it writes group_npis)
    mb = a.out.stat().st_size / 1e6
    print(f"{a.out}: {n} rows, {len(sources)} sources, {len(groups)} small TiC groups with NPIs, "
          f"{mb:.0f} MB, {time.perf_counter() - t0:.0f} s")  # fmt: skip


if __name__ == "__main__":  # pragma: no cover
    main()
