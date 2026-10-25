"""``python -m app.etl gov fetch|build|show``: government fee schedules.

    gov fetch [--source ID|all] [--headless]   download / browser-click / import manual files
    gov build [--source ID|all] [--as-of D]    read each source's current file -> RateRow parquet
    gov show  CODE [--entity E]                print every loaded price for a code (spot checks)

Outputs (gitignored, under the data root)::

    raw/store/<source_id>/<sha><ext>                 the file, content-addressed (fetch)
    raw/store/fetch_manifest.jsonl                   one line per fetch (D18 fields)
    intermediate/gov/<source_id>/<sha>.parquet       RateRow rows (contracts.RateRow, hospital cols)
    intermediate/gov/<source_id>/<sha>.manifest.json source + fetch + freshness inputs + counts
    intermediate/gov/LATEST.json                     source_id -> current parquet + manifest

Exit status is non-zero when any source failed (the others still run).
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.etl import fetch as fetch_mod
from app.etl.config import Paths, SourcesFile, SourceSpec, load_sources
from app.etl.gov import masshealth, opps_asc, pfs
from app.etl.refresh import RefreshRun, with_retry
from app.etl.gov.common import GovReadError, ReadResult, finish, write_json, write_parquet
from app.sites.contracts import Freshness

SOURCE_RULE = {
    "medicare_pfs": "fee_schedule_quarterly",
    "medicare_opps": "fee_schedule_quarterly",
    "medicare_asc": "fee_schedule_quarterly",
    "masshealth_fs": "fee_schedule_annual",
}


def _log(msg: str) -> None:
    print(msg, flush=True)


def gov_specs(sources: SourcesFile, which: str | None) -> list[SourceSpec]:
    return [s for s in sources.select(which) if s.is_gov_source]


# ------------------------------------------------------------------------------------- fetch


def fetch_one(
    spec: SourceSpec, sources: SourcesFile, paths: Paths, headless: bool
) -> fetch_mod.FetchRecord:
    if spec.access == "download":
        return fetch_mod.fetch_source(spec, sources.fetch, paths)
    if spec.access == "manual":
        src = paths.manual / (spec.manual_filename or "")
        if not src.is_file():
            raise fetch_mod.FetchError(
                f"{spec.source_id}: manual file missing: put {spec.manual_filename} in {paths.manual} "
                f"(download it from {spec.discovery})"
            )
        obtained = datetime.fromtimestamp(src.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds"
        )
        return fetch_mod.store_local(
            spec, src, paths, method="manual", url=spec.url, final_url=None, fetched_at=obtained,
            note=(spec.note or "") + f" | imported from raw/manual/{src.name}; fetched_at = file mtime",
        )  # fmt: skip
    if spec.access == "browser":
        from app.etl.gov.browser import BrowserBlocked, download_via_page

        with tempfile.TemporaryDirectory(prefix=f"gov-{spec.source_id}-") as tmp:
            try:
                dl = download_via_page(
                    spec.landing_url or "", spec.link_href or "", Path(tmp),
                    sources.fetch.allowed_domains, headless=headless,
                )  # fmt: skip
            except BrowserBlocked as e:
                raise fetch_mod.FetchError(
                    f"{spec.source_id}: BLOCKED ({e}). Do not escalate: set access: manual, download "
                    f"{spec.url} by hand into {paths.manual}, set manual_filename"
                ) from e
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return fetch_mod.store_local(
                spec, dl.path, paths, method="browser", url=dl.link_url, final_url=dl.final_url,
                fetched_at=now, landing_url=dl.landing_url, user_agent=dl.user_agent,
                note=f"plain headed Chromium clicked the link on {dl.landing_url} (HTTP {dl.landing_status})",
            )  # fmt: skip
    raise fetch_mod.FetchError(f"{spec.source_id}: access {spec.access} is not a gov access mode")


def cmd_fetch(a: argparse.Namespace, paths: Paths) -> int:
    """One retry per source (P11); a source that still fails keeps its last stored copy (LATEST
    keeps pointing at it), goes to intermediate/refresh_status.json and is alerted."""
    sources = load_sources(a.config_dir)
    errors = 0
    run = RefreshRun(paths, "fee schedules (gov fetch)")
    for spec in gov_specs(sources, a.source):
        rec, errs = with_retry(
            lambda spec=spec: fetch_one(spec, sources, paths, a.headless), spec.source_id, log=_log
        )
        if rec is None:
            prev = fetch_mod.current(paths, spec.source_id)
            lg = (
                {"sha256": prev.sha256, "fetched_at": prev.fetched_at or prev.imported_at}
                if prev is not None and prev.path.exists()
                else None
            )
            e = run.failed(spec.source_id, errs, lg)
            _log(f"FAIL   {spec.source_id}: {e['reason']} -> {e['status']}")
            errors += 1
            continue
        run.ok(spec.source_id, sha256=rec.sha256, fetched_at=rec.fetched_at)
        _log(
            f"{rec.status.upper():6} {spec.source_id}: {rec.sha256[:12]} {rec.bytes:,} bytes ({rec.method})"
        )
    if run.outcomes and not run.finish(log=_log):
        errors = max(errors, 1)
    return 1 if errors else 0


# ------------------------------------------------------------------------------------- build


def read_source(spec: SourceSpec, rec: fetch_mod.FetchRecord, paths: Paths) -> ReadResult:
    eff = spec.effective_date
    assert eff is not None
    kw = {"source_id": spec.source_id, "sha": rec.sha256}
    if spec.format == "cms_pfs_rvu_zip":
        return pfs.read_pfs(rec.path, effective=eff, **kw)
    if spec.format == "cms_anes_base_units_zip":
        if len(spec.inputs) != 1:
            raise GovReadError(f"{spec.source_id}: needs exactly one input (the RVU zip)")
        rvu = fetch_mod.current(paths, spec.inputs[0])
        if rvu is None:
            raise GovReadError(f"{spec.source_id}: input {spec.inputs[0]} not fetched")
        return pfs.read_anesthesia(rec.path, rvu.path, rvu.sha256, effective=eff, **kw)
    if spec.format == "cms_opps_addendum_b_zip":
        return opps_asc.read_opps(rec.path, effective=eff, **kw)
    if spec.format == "cms_asc_addenda_zip":
        return opps_asc.read_asc(rec.path, effective=eff, **kw)
    if spec.format == "masshealth_regulation_pdf":
        res = masshealth.read_masshealth(rec.path, regulation=spec.regulation or "", **kw)
        if res.effective_date != eff:
            raise GovReadError(
                f"{spec.source_id}: the regulation says effective {res.effective_date}, "
                f"sources.d says {eff}"
            )
        return res
    raise GovReadError(f"{spec.source_id}: no reader for {spec.format}")


def freshness_inputs(spec: SourceSpec, rec: fetch_mod.FetchRecord) -> dict[str, Any]:
    """D18: (a) the publisher side from the release cycle, (b) our side = due at next release."""
    fetched = (rec.fetched_at or rec.imported_at or "")[:10]
    return {
        "last_updated": spec.effective_date,
        "expected_by": spec.next_release,
        "source_rule": SOURCE_RULE[spec.kind.value],
        "fetched_at": date.fromisoformat(fetched),
        "our_refresh_due": spec.next_release,
        "our_rule": "fee_schedule_per_release",
    }


def check_anchors(
    spec: SourceSpec, sha: str, rows: list[dict[str, Any]], anchors: list[dict[str, Any]]
) -> list[str]:
    """Every anchor of this source's kind must be present (and within tolerance). -> problems.
    An anchor applies to a source when its format matches and its entity occurs in the rows."""
    problems, checked = [], []
    entities = {r["entity_id"] for r in rows}
    for a in anchors:
        if a["format"] != spec.format or a["entity_id"] not in entities:
            continue
        hits = [
            r for r in rows
            if r["entity_id"] == a["entity_id"] and r["code"] == str(a["code"])
            and r["modifiers"] == a.get("modifiers", "") and r["plan_raw"] == a["plan_raw"]
        ]  # fmt: skip
        if spec.kind.value == "masshealth_fs" and not hits:
            continue  # each MassHealth regulation holds its own codes; another one has it
        checked.append(a["id"])
        if not hits:
            problems.append(f"anchor {a['id']}: missing")
            continue
        amt = float(hits[0]["amount"])
        if sha == a.get("exact_sha256"):
            if abs(amt - float(a["amount"])) > 0.005:
                problems.append(
                    f"anchor {a['id']}: {amt} != {a['amount']} on the anchor's own file"
                )
        elif abs(amt - float(a["amount"])) > float(a["amount"]) * float(a["tolerance_pct"]) / 100:
            problems.append(
                f"anchor {a['id']}: {amt} drifted > {a['tolerance_pct']}% from {a['amount']}"
            )
    return problems


def load_anchors(config_dir: Path | None) -> list[dict[str, Any]]:
    from app.etl.config import load_yaml

    try:
        return list(load_yaml("gov_anchors.yaml", config_dir).get("anchors") or [])
    except FileNotFoundError:
        return []


def build_one(
    spec: SourceSpec, paths: Paths, as_of: date, anchors: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    rec = fetch_mod.current(paths, spec.source_id)
    if rec is None or not rec.path.exists():
        raise GovReadError(f"{spec.source_id}: nothing fetched yet (python -m app.etl gov fetch)")
    res = read_source(spec, rec, paths)
    rows = finish(res.rows)
    if not rows:
        raise GovReadError(f"{spec.source_id}: 0 rows")
    problems = check_anchors(spec, rec.sha256, rows, anchors or [])
    if problems:
        raise GovReadError(f"{spec.source_id}: " + "; ".join(problems))
    out = paths.gov / spec.source_id / f"{rec.sha256}.parquet"
    write_parquet(rows, out)
    fr = freshness_inputs(spec, rec)
    fresh = Freshness.compute(as_of=as_of, **fr)
    manifest = {
        "source_id": spec.source_id,
        "kind": spec.kind.value,
        "format": spec.format,
        "access": spec.access,
        "release": spec.release,
        "regulation": spec.regulation,
        "effective_date": res.effective_date,
        "next_release": spec.next_release,
        "fetch": {
            k: getattr(rec, k)
            for k in (
                "method",
                "url",
                "final_url",
                "fetched_at",
                "imported_at",
                "sha256",
                "bytes",
                "relpath",
                "publisher_last_updated_on",
                "note",
                "landing_url",
                "user_agent",
            )
        },  # fmt: skip
        "inputs": {
            sid: (lambda r: {"sha256": r.sha256, "relpath": r.relpath} if r else None)(
                fetch_mod.current(paths, sid)
            )
            for sid in spec.inputs
        },
        "freshness_inputs": fr,
        "freshness_at_build": fresh.model_dump(mode="json"),
        "as_of": as_of,
        "rows": len(rows),
        "codes": len({r["code"] for r in rows}),
        "counts": res.counts,
        "notes": res.notes,
        "parquet": str(out.relative_to(paths.data)),
    }
    write_json(manifest, out.with_suffix(".manifest.json"))
    return manifest


def _write_latest(paths: Paths, entries: dict[str, Any]) -> None:
    p = paths.gov / "LATEST.json"
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur.update(entries)
    write_json(cur, p)


def cmd_build(a: argparse.Namespace, paths: Paths) -> int:
    sources = load_sources(a.config_dir)
    as_of = date.fromisoformat(a.as_of) if a.as_of else date.today()
    errors = 0
    done: dict[str, Any] = {}
    anchors = load_anchors(a.config_dir)
    for spec in gov_specs(sources, a.source):
        try:
            m = build_one(spec, paths, as_of, anchors)
            done[spec.source_id] = {
                "parquet": m["parquet"],
                "manifest": m["parquet"].replace(".parquet", ".manifest.json"),
                "sha256": m["fetch"]["sha256"],
                "rows": m["rows"],
                "effective_date": str(m["effective_date"]),
            }
            f = m["freshness_at_build"]
            _log(
                f"GOV    {spec.source_id}: {m['rows']:,} rows, {m['codes']:,} codes, effective "
                f"{m['effective_date']}, late={f['late_to_refresh']} stale_ours={f['stale_on_our_side']}"
            )
            for n in m["notes"]:
                if n.startswith("NOT LOADED"):
                    _log(f"WARN   {spec.source_id}: {n}")
        except (GovReadError, fetch_mod.FetchError, OSError) as e:
            _log(f"FAIL   {spec.source_id}: {type(e).__name__}: {e}")
            errors += 1
    if done:
        _write_latest(paths, done)
    return 1 if errors else 0


def cmd_show(a: argparse.Namespace, paths: Paths) -> int:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    latest = json.loads((paths.gov / "LATEST.json").read_text())
    for sid, e in sorted(latest.items()):
        t = pq.read_table(paths.data / e["parquet"])
        t = t.filter(pc.equal(t["code"], a.code))
        if a.entity:
            t = t.filter(pc.equal(t["entity_id"], a.entity))
        for r in t.to_pylist():
            _log(
                f"{sid:28} {r['entity_id']:18} {r['code']}{('-' + r['modifiers']) if r['modifiers'] else '':5} "
                f"{r['plan_raw']:16} ${r['amount']:>10,.2f}  {r['row_ref']}\n"
                f"{'':30}{r['negotiated_algorithm']}"
            )
    return 0


def add_parser(sub: Any) -> None:
    g = sub.add_parser(
        "gov", help="government fee schedules (PFS, anesthesia, OPPS, ASC, MassHealth)"
    )
    gs = g.add_subparsers(dest="gov_cmd", required=True)
    f = gs.add_parser("fetch")
    f.add_argument("--source", default="all")
    f.add_argument(
        "--headless", action="store_true", help="browser sources: no window (default headed)"
    )
    b = gs.add_parser("build")
    b.add_argument("--source", default="all")
    b.add_argument("--as-of", default=None)
    s = gs.add_parser("show")
    s.add_argument("code")
    s.add_argument("--entity", default=None)


def cmd(a: argparse.Namespace, paths: Paths) -> int:
    return {"fetch": cmd_fetch, "build": cmd_build, "show": cmd_show}[a.gov_cmd](a, paths)
