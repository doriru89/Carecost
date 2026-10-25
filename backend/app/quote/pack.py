"""Write the runtime quote pack (``quote_pack.sqlite``) from real ETL outputs.

    cd backend
    uv run --frozen --extra etl python -m app.quote.pack \\
        --hospital-build /path/to/data/build/20261024-10d8a893 \\
        --tic-root /path/to/data/intermediate/tic \\
        --gov-root /path/to/data/intermediate/gov \\
        [--gov-rows extra.csv --gov-sources extra.sources.yaml ...] \\
        --out ../data/runtime/quote_pack.sqlite

    # or the committed extract (what CI and the default Docker image use)
    uv run --frozen python -m app.quote.pack --from-extract --out ../data/runtime/quote_pack.sqlite

Reads with pyarrow (ETL side). The server reads the pack with stdlib sqlite3 (P1 problem 11).

Kept: rows of the codes we price (codes.yaml + visit codes + every care-path code), modifiers
none / 26 / TC, not ``excluded``. TiC rows are aggregated (``AGG_KEY``, see ``app.quote.store``);
NPIs only when every provider group folded into a packed row has at most ``MAX_GROUP_NPIS`` (D6).
Government fee-schedule rows: A3's ``gov build`` output (``--gov-root``: ``LATEST.json`` -> one
RateRow parquet + manifest per source, freshness inputs from the manifest, D18), or RateRow rows
with a sources YAML in the extract's format (``--gov-rows`` / ``--gov-sources``).
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from dataclasses import replace
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
    valid_npi,
    write_pack,
)
from app.registries import all_hospitals

_HOSPITAL_COLS = [
    "row_ref", "row_id", "source_id", "source_kind", "row_kind", "code", "modifiers", "component",
    "billing_class", "setting", "rev_code", "payer_id", "product", "line_of_business", "plan_raw",
    "amount", "amount_method", "negotiated_pct", "discounted_cash", "gross", "stage_row",
    "entity_id",
]  # fmt: skip
_TIC_COLS = [
    *_HOSPITAL_COLS, "excluded", "tic_tin_value", "tic_tin_type", "tic_service_codes",
    "tic_business_name", "tic_negotiated_type", "tic_provider_group_id", "tic_group_ordinal",
    "tic_site_ids",
]  # fmt: skip
AGG_KEY = ("tin", "tin_type", "code", "modifiers", "service_codes", "amount", "negotiated_pct",
           "billing_class", "negotiated_type", "business_name", "site_ids", "component",
           "amount_method")  # fmt: skip
"""TiC rows of one network file that agree on all of these are one packed row (C2 memory)."""


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
) -> tuple[Iterator[Row], dict[str, SourceMeta], tuple[dict, dict, dict, dict], str | None]:
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

    npi_sets: dict[int, tuple[str, ...]] = {}
    census: dict[str, set[str]] = {}
    flags: dict[str, frozenset[str]] = {}  # C4b: packed row uid -> A6 flags of its bunch
    stats = {
        "tic_rows_read": 0,
        "tic_rows_kept": 0,
        "tic_rows_packed": 0,
        "tic_placeholder_npis_dropped": 0,
        "tic_packed_rows_flagged": 0,
    }

    def gen() -> Iterator[Row]:
        set_ids: dict[tuple[str, ...], int] = {}
        for sid, sd in dirs:
            t = pq.read_table(sd / "rate_row.parquet", columns=_TIC_COLS,
                              filters=[("code", "in", sorted(codes))])  # fmt: skip
            meta = sources[sid]
            stats["tic_rows_read"] += t.num_rows
            # A6 (O's audit at the source): flags.parquet = row_id -> '|'-joined flags
            fl: dict[str, str] = {}
            if (sd / "flags.parquet").exists():
                ft = pq.read_table(sd / "flags.parquet", columns=["row_id", "flags"])
                fl = dict(zip(ft.column("row_id").to_pylist(), ft.column("flags").to_pylist()))
            bflags: dict[tuple, set[str]] = {}
            bunch: dict[tuple, tuple[Row, set[tuple[int, int]]]] = {}
            for d in t.to_pylist():
                if d["excluded"] or d["modifiers"] not in PACKED_MODIFIERS:
                    continue
                stats["tic_rows_kept"] += 1
                d["ref"] = standard_ref(meta, d["row_ref"], d["stage_row"])
                r = make_row(d)
                k = tuple(getattr(r, c) for c in AGG_KEY)
                grp = (d["tic_provider_group_id"] or 0, d["tic_group_ordinal"] or 0)
                if fl.get(r.row_id):
                    bflags.setdefault(k, set()).update(fl[r.row_id].split("|"))
                have = bunch.get(k)
                if have is None:
                    bunch[k] = (r, {grp})
                else:
                    if (r.stage_row, r.row_id) < (have[0].stage_row, have[0].row_id):
                        bunch[k] = (r, have[1])
                    bunch[k][1].add(grp)
            g = pq.read_table(sd / "groups.parquet",
                              columns=["provider_group_id", "group_ordinal", "npis", "n_npi"])  # fmt: skip
            gnpis: dict[tuple[int, int], tuple[str, ...] | None] = {}
            for rec in g.to_pylist():
                k2 = (rec["provider_group_id"], rec["group_ordinal"])
                ok = 0 < rec["n_npi"] <= MAX_GROUP_NPIS
                got = tuple(tin_digits(n) for n in rec["npis"]) if ok else None
                if got is not None:  # R10: "0" and other placeholders are "unknown", not an NPI
                    keep = tuple(n for n in got if valid_npi(n))
                    stats["tic_placeholder_npis_dropped"] += len(got) - len(keep)
                    got = keep or None
                gnpis[k2] = got
            for k, (r, grps) in sorted(bunch.items(),
                                       key=lambda kv: (kv[1][0].stage_row, kv[1][0].row_id)):  # fmt: skip
                if k in bflags:  # one flagged row in the bunch flags the packed row
                    flags[r.uid] = frozenset(bflags[k])
                    stats["tic_packed_rows_flagged"] += 1
                npis: set[str] | None = set()
                for grp in grps:
                    got = gnpis.get(grp)
                    if got is None:
                        npis = None
                        break
                    npis |= set(got)  # type: ignore[operator]
                set_id = 0
                if npis and len(npis) <= MAX_GROUP_NPIS:
                    key = tuple(sorted(npis))
                    set_id = set_ids.setdefault(key, len(set_ids) + 1)
                    npi_sets[set_id] = key
                for c in r.site_ids.split(";") if r.site_ids else ():
                    census.setdefault(c, set()).add(r.tin)
                stats["tic_rows_packed"] += 1
                yield replace(r, npi_set=set_id)

    return gen(), sources, (npi_sets, census, stats, flags), release


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


GOV_PUBLISHERS = {
    "medicare_pfs": "CMS (Medicare physician fee schedule)",
    "medicare_opps": "CMS (Medicare hospital outpatient, OPPS)",
    "medicare_asc": "CMS (Medicare ambulatory surgery centers)",
    "masshealth_fs": "MassHealth (EOHHS fee schedule)",
}


def gov_root_rows(gov_root: Path, codes: set[str]) -> tuple[list[Row], dict[str, SourceMeta]]:
    """A3's ``gov build`` output: ``LATEST.json`` names one parquet + manifest per source."""
    import pyarrow.parquet as pq

    data_dir = gov_root.parents[1]  # <repo>/data/intermediate/gov -> <repo>/data
    latest = json.loads((gov_root / "LATEST.json").read_text())
    rows: list[Row] = []
    sources: dict[str, SourceMeta] = {}
    for sid, ent in sorted(latest.items()):
        man = json.loads((data_dir / ent["manifest"]).read_text())
        fi = man["freshness_inputs"]
        recs = pq.read_table(data_dir / ent["parquet"]).to_pylist()
        if not recs:
            continue
        first = recs[0]
        label = man.get("regulation") or man.get("release") or ""
        sources[sid] = SourceMeta(
            source_id=sid, source_kind=man["kind"],
            publisher=f"{GOV_PUBLISHERS[man['kind']]} · {label}".rstrip(" ·"),
            source_file=first["source_file"], source_sha256=first["source_sha256"],
            source_date=str(first["source_date"]) if first.get("source_date") else None,
            last_updated=fi.get("last_updated"), fetched_at=fi["fetched_at"],
            source_rule=fi["source_rule"], our_rule=fi["our_rule"],
            expected_by=fi.get("expected_by"), our_refresh_due=fi.get("our_refresh_due"),
        )  # fmt: skip
        meta = sources[sid]
        for d in recs:
            if d["code"] not in codes or d.get("excluded"):
                continue
            if d["modifiers"] not in PACKED_MODIFIERS:
                continue
            d["ref"] = standard_ref(meta, d["row_ref"], int(d["stage_row"]))
            rows.append(make_row(d))
    return rows, sources


def refresh_status(roots: list[Path | None]) -> dict[str, dict]:
    """P11 / R11: the ETL's ``intermediate/refresh_status.json`` next to each input root (A5's
    app.etl.refresh), merged, so the server can say on /health which sources failed to refresh
    (``stale_on_our_side`` / ``no_good_copy``) instead of reading them as "no public price"."""
    out: dict[str, dict] = {}
    seen: set[Path] = set()
    for root in roots:
        if root is None:
            continue
        for cand in (root.parent / "refresh_status.json",
                     root.parent.parent / "intermediate" / "refresh_status.json"):  # fmt: skip
            if cand.exists() and cand.resolve() not in seen:
                seen.add(cand.resolve())
                out.update(json.loads(cand.read_text()).get("sources") or {})
    return dict(sorted(out.items()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hospital-build", type=Path)
    ap.add_argument("--tic-root", type=Path)
    ap.add_argument("--gov-root", type=Path, help="A3 data/intermediate/gov (LATEST.json)")
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
    trows, tsources, (npi_sets, census, stats, flags), release = tic_rows(a.tic_root, codes)
    sources.update(tsources)
    rows: list[Row] = list(hrows)
    if a.gov_root:
        grows, gs = gov_root_rows(a.gov_root, codes)
        rows += grows
        sources.update(gs)
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
    status = refresh_status([a.hospital_build, a.tic_root, a.gov_root])
    n = write_pack(a.out, rows=all_rows(), sources=sources, version=version, codes=loaded,
                   npi_sets=npi_sets, census_tins=census, refresh_status=status,
                   flags=flags)  # fmt: skip
    # (npi_sets / census are filled while write_pack streams the TiC rows, before it writes them)
    mb = a.out.stat().st_size / 1e6
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r.source_kind] = by_kind.get(r.source_kind, 0) + 1
    by_kind["insurer_tic"] = stats["tic_rows_packed"]
    print(f"{a.out}: {n} rows, {len(sources)} sources, {len(npi_sets)} NPI sets, "
          f"{len(census)} census ids linked, {mb:.0f} MB, {time.perf_counter() - t0:.0f} s")  # fmt: skip
    print("rows by source kind:", json.dumps(dict(sorted(by_kind.items()))))
    print("tic:", json.dumps(stats))


if __name__ == "__main__":  # pragma: no cover
    main()
