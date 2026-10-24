"""Coverage report: target code x hospital x payer, compared with the pre-re-ETL baseline.

Writes ``coverage.md`` (headline + per-code + per-hospital + payer matrix) and ``coverage.csv``
(the full code x hospital x payer matrix) into the build directory (and ``--out`` if given).

Counting rule ("usable rate"): row_kind == payer_rate, not excluded, amount is not None.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from app.etl.config import CodeList, SourcesFile

COLS = [
    "row_kind", "excluded", "exclude_reason", "amount", "amount_method", "dollar_basis",
    "negotiated_pct", "code", "entity_id", "payer_id", "line_of_business", "component",
    "ambiguous_multi_rate", "above_gross", "source_id",
]  # fmt: skip
HEADLINE_PAYERS = [
    "BCBS_MA", "HARVARD_PILGRIM", "TUFTS_HP", "MGB_HP", "AETNA", "UHC", "UHC_HPHC_ALLIANCE",
    "CIGNA", "WELLSENSE", "FALLON", "MEDICARE", "MASSHEALTH",
]  # fmt: skip


def _usable(r: dict[str, Any]) -> bool:
    return r["row_kind"] == "payer_rate" and not r["excluded"] and r["amount"] is not None


def build_report(
    build_dir: Path, sources: SourcesFile, codes: CodeList, baseline: dict[str, Any]
) -> dict[str, Any]:
    manifest = json.loads((build_dir / "manifest.json").read_text())
    rows = pq.read_table(build_dir / "rate_row.parquet", columns=COLS).to_pylist()
    entities = [s.entity_id for s in sources.sources if s.kind.value == "hospital_mrf"]
    n_h = len(entities)
    target = sorted(codes.codes, key=lambda c: (codes.domains_for(c)[0], c))

    usable = [r for r in rows if _usable(r)]
    payer_rows = [r for r in rows if r["row_kind"] == "payer_rate"]
    cell: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for r in usable:
        cell[(r["code"], r["entity_id"], r["payer_id"] or "(unmapped)")].append(r["amount"])
    by_code_h: dict[str, set[str]] = defaultdict(set)
    by_code_rows: Counter[str] = Counter()
    by_h_rows: Counter[str] = Counter()
    by_h_payers: dict[str, set[str]] = defaultdict(set)
    by_h_codes: dict[str, set[str]] = defaultdict(set)
    for r in usable:
        by_code_h[r["code"]].add(r["entity_id"])
        by_code_rows[r["code"]] += 1
        by_h_rows[r["entity_id"]] += 1
        if r["payer_id"]:
            by_h_payers[r["entity_id"]].add(r["payer_id"])
        by_h_codes[r["entity_id"]].add(r["code"])
    pct_only = Counter(
        r["code"]
        for r in payer_rows
        if not r["excluded"] and r["amount"] is None and r["negotiated_pct"] is not None
    )
    alg_only = Counter(
        r["code"]
        for r in payer_rows
        if not r["excluded"] and r["amount"] is None and r["negotiated_pct"] is None
    )
    excluded = Counter(r["exclude_reason"] for r in payer_rows if r["excluded"])
    mapped = sum(1 for r in usable if r["payer_id"])
    derived = sum(1 for r in usable if r["amount_method"] == "derived_pct_x_gross")
    ambiguous = sum(1 for r in usable if r["ambiguous_multi_rate"])
    above = sum(1 for r in usable if r["above_gross"])
    comp = Counter(r["component"] for r in usable)
    placeholders = sum(
        sum(s["placeholders_dropped"].values()) for s in manifest["sources"].values()
    )
    bl = baseline["codes"]
    bt = baseline["totals"]
    hosp_with_rates = {r["entity_id"] for r in usable}

    # ---------------------------------------------------------------- CSV (full matrix)
    csv_path = build_dir / "coverage.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(
            ["code", "domain", "entity_id", "payer_id", "usable_rows", "min", "median", "max"]
        )
        for (code, h, p), amts in sorted(cell.items()):
            w.writerow([
                code, "/".join(codes.domains_for(code)), h, p, len(amts),
                f"{min(amts):.2f}", f"{statistics.median(amts):.2f}", f"{max(amts):.2f}",
            ])  # fmt: skip

    # ---------------------------------------------------------------- markdown
    L: list[str] = []
    L.append(f"# Coverage report: build `{manifest['build_id']}`\n")
    gate_fail = [g for g in manifest["gates"] if g["status"] == "fail"]
    gate_warn = [g for g in manifest["gates"] if g["status"] == "warn"]
    L.append(
        f"Build date {manifest['build_date']} · gates: **{'PASS' if manifest['ok'] else 'FAIL'}** "
        f"({len(gate_fail)} fail, {len(gate_warn)} warn) · source: hospital MRFs only "
        f"({len(manifest['sources'])}/{n_h} files). Usable rate = payer-specific line, not excluded, "
        "with a dollar amount (stated, or % x the line's gross charge).\n"
    )
    L.append("## Headline: old DB vs new rate_row\n")
    L.append("| measure | old (DB / audit) | new | denominator |")
    L.append("|---|---|---|---|")
    old_cov = sum(1 for c in target if bl.get(c, {}).get("db_hosp_mrf", 0) > 0)
    new_cov = sum(1 for c in target if by_code_h.get(c))
    L.append(
        f"| target codes with any hospital payer rate | {old_cov} | {new_cov} | {len(target)} codes |"
    )
    old_cells = sum(bl.get(c, {}).get("db_hosp_mrf", 0) for c in target)
    new_cells = sum(len(by_code_h.get(c, ())) for c in target)
    L.append(
        f"| code x hospital cells with a payer rate | {old_cells} | {new_cells} | {len(target)} x {n_h} = {len(target) * n_h} |"
    )
    L.append(
        f"| hospitals with MRF payer rates | {bt['hospitals_with_mrf_payer_rows']} | {len(hosp_with_rates)} | {n_h} |"
    )
    old_rows = sum(bl.get(c, {}).get("db_mrf_rows", 0) for c in target)
    L.append(f"| MRF payer-rate rows, target codes | {old_rows} (DB) | {len(usable)} usable | — |")
    L.append(
        f"| target payer-$ rows in raw files (audit census) | {bt['target_payer_dollar_rows_raw']} | "
        f"{sum(1 for r in payer_rows if r['amount_method'] == 'stated')} stated-$ rows kept "
        f"(+{derived} derived from %) | — |"
    )
    L.append(
        f"| rows with a mapped payer | {bt['rows_mapped_to_4_payers']} (4 payers) | {mapped} "
        f"({len({r['payer_id'] for r in usable if r['payer_id']})} payers) | {len(usable)} usable |"
    )
    L.append(
        f"| distinct rates thrown away by coarse dedup | 3,613 | 0 (never collapsed; {ambiguous} rows flagged ambiguous) | — |"
    )
    L.append("")
    L.append(
        f"Also: {placeholders} placeholder rows ($0 / $0.01 / $1) dropped and counted; {above} usable rows above "
        f"gross (flagged); components of usable rows: "
        + ", ".join(f"{k} {v}" for k, v in sorted(comp.items()))
        + "; excluded payer rows: "
        + ", ".join(f"{k} {v}" for k, v in excluded.most_common())
        + ".\n"
    )

    L.append("## Per code\n")
    L.append(
        "| domain | code | what | hospitals w/ rate (old DB → new) /12 | files w/ payer $ (audit) | usable rows (old DB MRF rows → new) | %-only, no gross | algorithm-only |"
    )
    L.append("|---|---|---|---|---|---|---|---|")
    for c in target:
        b = bl.get(c, {})
        L.append(
            f"| {'/'.join(codes.domains_for(c))} | {c} | {codes.description(c)} | "
            f"{b.get('db_hosp_mrf', '?')} → **{len(by_code_h.get(c, ()))}** | {b.get('files_payer_dollar', '?')} | "
            f"{b.get('db_mrf_rows', '?')} → **{by_code_rows.get(c, 0)}** | {pct_only.get(c, 0)} | {alg_only.get(c, 0)} |"
        )
    L.append("")

    L.append("## Per hospital\n")
    L.append(
        "| hospital | file date | staged rows (= independent count) | rate rows | usable payer rates | payers | target codes /"
        f"{len(target)} | placeholders dropped |"
    )
    L.append("|---|---|---|---|---|---|---|---|")
    for s in sources.sources:
        m = manifest["sources"].get(s.source_id)
        if not m:
            L.append(f"| {s.entity_id} | — | not built | — | — | — | — | — |")
            continue
        L.append(
            f"| {s.entity_id} | {m['last_updated_on']} | {m['staged_rows']:,} (= {m['independent_count']:,}) | "
            f"{m['rate_rows']:,} | {by_h_rows.get(s.entity_id, 0):,} | {len(by_h_payers.get(s.entity_id, ()))} | "
            f"{len(by_h_codes.get(s.entity_id, ()))} | {sum(m['placeholders_dropped'].values())} |"
        )
    L.append("")

    L.append("## Hospital x payer: target codes with a usable rate\n")
    L.append("| hospital | " + " | ".join(HEADLINE_PAYERS) + " |")
    L.append("|---|" + "---|" * len(HEADLINE_PAYERS))
    hp_codes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for code, h, p in cell:
        hp_codes[(h, p)].add(code)
    for h in entities:
        L.append(
            f"| {h} | "
            + " | ".join(str(len(hp_codes.get((h, p), ()))) for p in HEADLINE_PAYERS)
            + " |"
        )
    L.append("")

    L.append("## Gates\n")
    L.append("| gate | subject | status | detail |")
    L.append("|---|---|---|---|")
    for g in manifest["gates"]:
        if g["status"] != "pass" or g["gate"] == "anchor":
            L.append(f"| {g['gate']} | {g['subject']} | {g['status']} | {g['detail']} |")
    L.append("")
    md_path = build_dir / "coverage.md"
    md_path.write_text("\n".join(L) + "\n")
    return {
        "md": md_path,
        "csv": csv_path,
        "usable_rows": len(usable),
        "codes_covered": new_cov,
        "codes_total": len(target),
        "cells_new": new_cells,
        "cells_old": old_cells,
        "hospitals_with_rates": len(hosp_with_rates),
    }
