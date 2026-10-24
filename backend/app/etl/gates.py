"""Data-quality gates (config: data/etl/gates.yaml). ``fail`` stops the build (unless the source
has a last-good copy to fall back to, see build.py); ``warn`` is reported."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from app.sites.contracts import Freshness  # D18: the one implementation of both cadences


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
    sources: dict[str, tuple[date | None, date]], today: date, cfg: dict[str, Any]
) -> list[GateResult]:
    """Freshness is a label, never a fail (D13). ``sources``: sid -> (publisher's own
    last_updated_on, our fetched_at date). Both sides come from ``Freshness.compute`` (the one
    implementation of the 365-day / monthly cadences, D18); ``warn_after_days`` is an internal
    ETL warning only. A file without last_updated_on is never "late" (no date, no deadline)."""
    out = []
    warn_after = int(cfg.get("warn_after_days", 180))
    for sid, (d, fetched) in sorted(sources.items()):
        f = Freshness.compute(
            as_of=today,
            source_rule="hospital_mrf_365_days",
            last_updated=d,
            our_rule="hospital_monthly",
            fetched_at=fetched,
        )
        notes = []
        if d is None:
            notes.append("file has no last_updated_on (never late)")
        else:
            notes.append(f"last_updated_on {d.isoformat()} ({(today - d).days} days)")
        notes.append(f"fetched_at {fetched.isoformat()}")
        if f.late_to_refresh:
            notes.append(f"late_to_refresh (expected_by {f.expected_by})")
        if f.stale_on_our_side:
            notes.append(f"stale_on_our_side (our_refresh_due {f.our_refresh_due})")
        flagged = (
            f.late_to_refresh
            or f.stale_on_our_side
            or (d is not None and (today - d).days > warn_after)
        )
        out.append(GateResult("staleness", sid, "warn" if flagged else "pass", "; ".join(notes)))
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
