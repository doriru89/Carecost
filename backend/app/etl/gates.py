"""Data-quality gates (config: data/etl/gates.yaml). ``fail`` stops the build; ``warn`` is reported."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class GateResult:
    gate: str
    subject: str
    status: str  # pass | warn | fail
    detail: str

    def to_json(self) -> dict[str, str]:
        return asdict(self)


def failed(results: Iterable[GateResult]) -> list[GateResult]:
    return [r for r in results if r.status == "fail"]


def check_anchors(
    rows: Iterable[dict[str, Any]], anchors: list[dict[str, Any]]
) -> list[GateResult]:
    want = {
        (a["entity_id"], a["code"], a["payer_raw"], a["plan_raw"], a.get("rev_code", "")): a
        for a in anchors
    }
    hits: dict[str, list[dict[str, Any]]] = {a["id"]: [] for a in anchors}
    for r in rows:
        k = (r["entity_id"], r["code"], r["payer_raw"], r["plan_raw"], r["rev_code"])
        if k in want:
            hits[want[k]["id"]].append(r)
    out = []
    for a in anchors:
        found = [r for r in hits[a["id"]] if r.get("amount") is not None]
        if not found:
            out.append(GateResult("anchor", a["id"], "fail", "anchor row missing from rate_row"))
            continue
        amounts = sorted({round(float(r["amount"]), 2) for r in found})
        same_file = any(r["source_sha256"] == a.get("exact_sha256") for r in found)
        target = float(a["amount"])
        if same_file:
            ok = target in amounts
            detail = f"exact match required on the anchor file: want {target}, got {amounts}"
        else:
            tol = float(a.get("tolerance_pct", 0)) / 100.0
            ok = any(abs(x - target) <= tol * target for x in amounts)
            detail = f"newer file: want {target} +/-{a.get('tolerance_pct')}%, got {amounts}"
        out.append(GateResult("anchor", a["id"], "pass" if ok else "fail", detail))
    return out


def check_row_counts(
    current: dict[str, dict[str, int]],
    previous: dict[str, dict[str, int]] | None,
    cfg: dict[str, Any],
) -> list[GateResult]:
    out = []
    max_drop = float(cfg.get("max_drop_pct", 20)) / 100.0
    min_payer = int(cfg.get("min_payer_rate_rows_per_source", 1))
    for sid, cur in sorted(current.items()):
        problems = []
        if cur.get("payer_rate_rows", 0) < min_payer:
            problems.append(f"{cur.get('payer_rate_rows', 0)} payer-rate rows (< {min_payer})")
        prev = (previous or {}).get(sid)
        if prev and prev.get("rate_rows"):
            drop = 1 - cur["rate_rows"] / prev["rate_rows"]
            if drop > max_drop:
                problems.append(
                    f"rate_rows fell {drop:.0%} ({prev['rate_rows']} -> {cur['rate_rows']})"
                )
        out.append(
            GateResult(
                "row_count", sid, "fail" if problems else "pass", "; ".join(problems) or "ok"
            )
        )
    return out


def check_staleness(
    dates: dict[str, date | None], today: date, cfg: dict[str, Any]
) -> list[GateResult]:
    out = []
    for sid, d in sorted(dates.items()):
        if d is None:
            out.append(GateResult("staleness", sid, "fail", "file has no last_updated_on"))
            continue
        age = (today - d).days
        if age > int(cfg["fail_after_days"]):
            status = "fail"
        elif age > int(cfg["warn_after_days"]):
            status = "warn"
        else:
            status = "pass"
        out.append(
            GateResult("staleness", sid, status, f"last_updated_on {d.isoformat()} ({age} days)")
        )
    return out


def check_sources_present(expected: list[str], present: set[str]) -> list[GateResult]:
    return [
        GateResult(
            "source_present",
            sid,
            "pass" if sid in present else "fail",
            "normalized" if sid in present else "no normalized file for the current fetch",
        )
        for sid in expected
    ]
