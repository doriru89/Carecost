"""Run the outlier audit on a quote pack and write ``data/audit/``.

    cd backend
    uv run --frozen --extra etl python -m app.audit --pack <quote_pack.sqlite> [--out ../data/audit]

Writes ``outliers.csv`` (one row per outlier line, most extreme first, with the source pointer,
the quoted source text and the cause) and ``summary.json`` (denominators, cause counts, the fix
simulation and the X2 backtest). Read-only on everything else.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter
from functools import partial
from pathlib import Path
from typing import Any

from app.audit.backtest import backtest
from app.audit.causes import CAUSES, Classifier, outlying
from app.audit.fixes import ORDER, children_apart
from app.audit.peers import HIGH, LOW, MIN_GROUPS, LineBuilder, Measured, measure
from app.audit.trace import DEFAULT_RAW, DEFAULT_STAGING, DEFAULT_TIC, Tracer
from app.quote.registry import Registry
from app.quote.store import REPO_ROOT, load_pack

FIX_FOR = {
    "not_dollars": ("-", "A5", "normalize: a stated dollar under 1% of the row's gross is a unit / weight -> excluded, reason not_dollars"),
    "facility_professional_mixup": ("-", "A2/A5", "component: a TiC 'institutional' row of a doctors' group, or a hospital row without billing_class, is checked against both component medians before it prices a line"),
    "peers_flat_rate": ("-", "C3", "peer median: count a flat-rate group once per family, not per code (or exclude flat groups from per-code medians)"),
    "placeholder": ("F1", "A5/A2", "normalize: amount <= $1 or >= $99,999 -> excluded, reason placeholder"),
    "chargemaster_as_rate": ("F1", "A5", "normalize: payer amount == the row's gross -> excluded, reason chargemaster_as_rate"),
    "percent_as_dollars": ("-", "A5", "normalize: a percentage contract's amount = pct x gross, never the pct itself"),
    "per_diem_or_case_rate": ("-", "A5", "normalize: items whose description / methodology says per diem, half day or case rate are not a CPT line price (Children's 'HC PER DIEM PAIN TREATMENT' carries 99215)"),
    "wrong_plan": ("F2", "A5", "payers.py: non-commercial / non-contracted / unknown-LOB plan text -> not an insurance rate"),
    "anesthesia_per_unit": ("-", "A2+C3", "tag 008xx rates equal across codes as per-unit; price x base units only for anesthesia groups"),
    "pos_facility_rate_at_office": ("F3a", "C3", "engine.yaml place_of_service: office sites read POS 11 only"),
    "pos_office_rate_at_hospital": ("-", "C3", "engine.yaml: hospital professional lines drop POS-11-only rows"),
    "pos_office_rate_at_urgent_care": ("F3b", "C3", "engine.yaml: urgent care reads the POS 20 rate when the group has one"),
    "flat_rate": ("-", "C3", "genuine (one contract rate for several levels): show with note, compare as is"),
    "ambiguous_multi_rate": ("-", "A2+C3", "A2 flags same-NPI same-POS duplicates; C3 shows both, not summed"),
    "rate_group_within_tin": ("F5", "C3", "D6: price the TIN at its largest NPI rate group, list the others by doctor"),
    "children_only_contract": ("F4", "C3", "X2 peers: children-only sites are their own kind"),
    "contract_level": ("-", "-", "genuine: the group is consistently far from peers on >= 5 codes"),
    "unexplained": ("-", "O", "manual review"),
}  # fmt: skip


QUOTE_MAX = 320


def _severity(m: Measured) -> float:
    return max(math.log(max(m.line.high, 0.005) / m.peer_median),
               -math.log(max(m.line.low, 0.005) / m.peer_median))  # fmt: skip


def _pooled(bt: dict[str, Any]) -> dict[str, float]:
    """same_kind backtest pooled over kinds: n, median APE is not poolable, so the n-weighted
    share more than 2x off and inside p25-p75."""
    sk = [v["same_kind"] for v in bt.values() if v["same_kind"].get("n")]
    n = sum(x["n"] for x in sk)
    if not n:
        return {"n": 0}
    return {"n": n,
            "share_over_2x_off": round(sum(x["n"] * x["share_over_2x_off"] for x in sk) / n, 4),
            "share_inside_p25_p75": round(sum(x["n"] * x["share_inside_p25_p75"] for x in sk) / n,
                                          4)}  # fmt: skip


def _ident(ln) -> tuple:
    return (ln.kind.split(":")[0], ln.code, ln.mod, ln.component, ln.payer, ln.product, ln.network,
            ln.group, ln.family)  # fmt: skip


def run(pack: Path, out: Path, raw: Path, staging: Path, tic: Path,
        sites: Path | None = None) -> dict[str, Any]:  # fmt: skip
    t0 = time.time()
    reg = Registry.load(sites)
    store = load_pack(pack, tins=reg.tins, census_ids=reg.census_ids)
    children = frozenset(s.id for s in reg.sites.values() if s.children_only)
    lines = LineBuilder(store, reg).build()
    measured = measure(lines)
    outl = sorted((m for m in measured if m.outlier), key=_severity, reverse=True)
    # trace the most extreme outlying row of every outlier, then classify with its raw text
    prim = [outlying(m)[0] for m in outl]
    tracer = Tracer(store, raw, staging, tic)
    # a hospital row can be the extreme row of a payer line and of a self-pay line: trace the
    # two uses apart, each matched on the number it priced
    by_use: dict[bool, Any] = {}
    for cash in (False, True):
        use = [(v, r) for m, (v, r) in zip(outl, prim) if (m.line.family == "mrf_cash") == cash]
        by_use[cash] = tracer.trace_all([r for _, r in use], {r.uid: v for v, r in use})
    traces = [by_use[m.line.family == "mrf_cash"].get(r.uid) for m, (_, r) in zip(outl, prim)]
    cl = Classifier(lines, measured, children)
    verdicts = [cl.classify(m, tr.quote if tr else "") for m, tr in zip(outl, traces)]

    # fix simulation (cumulative)
    steps = [
        {
            "fix": "base",
            "rule": "as packed",
            "measured_lines": len(measured),
            "outliers": len(outl),
            "removed": 0,
            "backtest_same_kind": _pooled(backtest(lines)),
        }
    ]
    cur = lines
    before = len(outl)
    for fid, desc, fix in ORDER:
        f = partial(children_apart, children_only=children) if fix is children_apart else fix
        cur = f(cur, store)
        mm = measure(cur)
        n = sum(1 for m in mm if m.outlier)
        steps.append({"fix": fid, "rule": desc, "measured_lines": len(mm), "outliers": n,
                      "removed": before - n, "backtest_same_kind": _pooled(backtest(cur))})  # fmt: skip
        before = n
    after = measure(cur)
    residual_ids = {_ident(m.line) for m in after if m.outlier}
    cl_after = Classifier(cur, after, children)
    residual_causes = Counter(cl_after.classify(m).cause for m in after if m.outlier)

    out.mkdir(parents=True, exist_ok=True)
    cols = ["rank", "side", "ratio", "kind", "code", "modifier", "component", "payer", "product",
            "network", "group", "group_name", "sites", "systems", "peer_median", "peer_groups",
            "peer_p25", "peer_p75", "line_low", "line_high", "line_rows", "outlying_rows",
            "value", "source_id", "source_kind", "row_id", "stage_row", "source_pointer",
            "source_quote", "trace", "cause", "cause_detail", "fix", "fix_owner", "fix_rule",
            "outlier_after_fixes"]  # fmt: skip
    with (out / "outliers.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for i, (m, v, (val, r), tr) in enumerate(zip(outl, verdicts, prim, traces), start=1):
            ln = m.line
            fid, owner, rule = FIX_FOR[v.cause]
            w.writerow([
                i, m.outlier, round(val / m.peer_median, 3), ln.kind, ln.code, ln.mod,
                ln.component, ln.payer, ln.product, ln.network, ln.group,
                "; ".join(sorted(ln.business))[:120], ";".join(sorted(ln.sites)),
                ";".join(sorted(ln.systems)), round(m.peer_median, 2), m.peer_groups,
                round(m.peer_p25, 2), round(m.peer_p75, 2), round(ln.low, 2), round(ln.high, 2),
                len(ln.rows), len(outlying(m)), val, r.source_id, r.source_kind, r.row_id,
                r.stage_row, tr.pointer if tr else "", (tr.quote if tr else "")[:QUOTE_MAX],
                tr.verified if tr else "not_found", v.cause, v.detail, fid, owner, rule,
                _ident(ln) in residual_ids,
            ])  # fmt: skip
    # the engine's default request (no network): every network file of the payer + product
    prod = measure(LineBuilder(store, reg, level="product").build())
    kinds = Counter(m.line.kind for m in measured)
    okinds = Counter((m.line.kind, m.outlier) for m in outl)
    distinct_rows = {r.uid for m in outl for _, r in outlying(m)}
    summary = {
        "pack": str(pack),
        "build_id": store.version.build_id,
        "tic_release": store.version.tic_release,
        "sites": len(reg.sites),
        "rows_loaded": len(store.rows),
        "rule": {
            "min_peer_groups": MIN_GROUPS,
            "high": HIGH,
            "low": round(LOW, 4),
            "peer": "same_kind (X2), network level",
        },  # fmt: skip
        "lines_built": len(lines),
        "lines_measured": len(measured),
        "outliers": len(outl),
        "outlier_share": round(len(outl) / len(measured), 4) if measured else 0.0,
        "distinct_source_rows_outlying": len(distinct_rows),
        "measured_by_kind": dict(kinds),
        "outliers_by_kind_side": {f"{k}/{s}": n for (k, s), n in sorted(okinds.items())},
        "product_level": {
            "lines_measured": len(prod),
            "outliers": sum(1 for m in prod if m.outlier),
        },
        "causes": {c: sum(1 for v in verdicts if v.cause == c) for c in CAUSES},
        "trace_status": dict(
            Counter(tr.verified if tr else "not_found" for tr in traces)
        ),  # fmt: skip
        "fixes": steps,
        "residual_after_fixes": {
            "outliers": len(residual_ids),
            "measured": len(after),
            "causes": dict(residual_causes.most_common()),
        },  # fmt: skip
        "backtest": backtest(lines),
        "backtest_after_fixes": backtest(cur),
        "seconds": round(time.time() - t0, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "audit")
    ap.add_argument("--sites", type=Path, default=None)
    ap.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING)
    ap.add_argument("--tic-root", type=Path, default=DEFAULT_TIC)
    a = ap.parse_args()
    s = run(a.pack, a.out, a.raw_root, a.staging_root, a.tic_root, a.sites)
    print(json.dumps({k: s[k] for k in ("lines_measured", "outliers", "outlier_share", "causes",
                                        "trace_status", "fixes", "seconds")}, indent=1))  # fmt: skip


if __name__ == "__main__":
    main()
