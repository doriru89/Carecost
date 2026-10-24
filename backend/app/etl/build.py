"""Stage 5: assemble the normalized per-source files into one versioned build + run the gates.

Output (``data/build/<build_id>/``): ``rate_row.parquet``, ``rate_row.sqlite`` (what the FastAPI
runtime will ship and read; no Postgres), ``manifest.json`` and ``gates.json``.

Failure recovery:

* Per source: a source whose current copy fails a gate (not normalized, NPI, row count, anchor)
  is built from its last good copy instead -- the ``data/etl/pins.yaml`` pin, else the baseline
  build's sha if the store still has it -- keeping that copy's own ``fetched_at`` so it honestly
  shows as stale on our side. Only a source with no good copy fails the build.
* Row-count baseline: the LATEST build, or ``baseline_manifest`` (CI has no data/build). With
  neither, the build fails unless ``first_build`` is set.
* Atomic: the build is written to ``data/build/.tmp-<id>-<pid>/`` and moved into place with
  ``os.replace``; an existing build id is never rewritten (a re-run gets ``<id>-2`` ...).
  ``LATEST`` is written via a temp file + ``os.replace`` and only for a build whose gates pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from app.etl import gates
from app.etl.config import CONFIG_DIR, Paths, SourcesFile, SourceSpec
from app.etl.fetch import FetchRecord, current, read_manifest
from app.etl.normalize import RATE_ROW_SCHEMA

_SQL_TYPES = {pa.int64(): "INTEGER", pa.float64(): "REAL", pa.bool_(): "INTEGER"}
BUILD_ID_RE = re.compile(r"^[0-9]{8}-[0-9a-f]{8}(-[0-9]+)?$")
PINS_FILE = "pins.yaml"
_PIN_KEYS = {"source_id", "sha256", "reason", "set_by", "date"}


class BuildError(RuntimeError):
    pass


@dataclass
class BuildResult:
    build_id: str
    dir: Path
    ok: bool
    gate_results: list[gates.GateResult]
    fallbacks: dict[str, dict[str, Any]] = field(default_factory=dict)


def latest_build(paths: Paths) -> Path | None:
    """The build LATEST points at, or None when LATEST is missing, empty, not a build id, or
    names a build directory without a manifest."""
    p = paths.builds / "LATEST"
    if not p.exists():
        return None
    bid = p.read_text().strip()
    if not BUILD_ID_RE.match(bid):
        return None
    d = paths.builds / bid
    return d if (d / "manifest.json").is_file() else None


def _write_latest(paths: Paths, build_id: str) -> None:
    tmp = paths.builds / f".LATEST.{os.getpid()}.tmp"
    tmp.write_text(build_id + "\n")
    os.replace(tmp, paths.builds / "LATEST")


def load_pins(config_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """``data/etl/pins.yaml``: source_id -> {sha256, reason, set_by, date}. Version-controlled,
    so every pin has an author and a reason in git."""
    path = (config_dir or CONFIG_DIR) / PINS_FILE
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    out: dict[str, dict[str, Any]] = {}
    for p in doc.get("pins") or []:
        missing = _PIN_KEYS - set(p)
        if missing:
            raise BuildError(f"{PINS_FILE}: pin {p} is missing {sorted(missing)}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(p["sha256"])):
            raise BuildError(f"{PINS_FILE}: {p['source_id']}: sha256 must be 64 hex chars")
        if p["source_id"] in out:
            raise BuildError(f"{PINS_FILE}: duplicate pin for {p['source_id']}")
        out[p["source_id"]] = p
    return out


def load_baseline(paths: Paths, baseline_manifest: Path | None) -> dict[str, Any] | None:
    """Per-source baseline (rate_rows, sha256, ...) from an explicit manifest, else LATEST."""
    if baseline_manifest is not None:
        if not baseline_manifest.is_file():
            raise BuildError(f"--baseline-manifest {baseline_manifest} does not exist")
        doc = json.loads(baseline_manifest.read_text())
        return dict(doc["sources"])
    lb = latest_build(paths)
    if lb is None:
        return None
    return dict(json.loads((lb / "manifest.json").read_text())["sources"])


def _sqlite(parquet: Path, db: Path) -> int:
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    cols = [(f.name, _SQL_TYPES.get(f.type, "TEXT")) for f in RATE_ROW_SCHEMA]
    con.execute(f"CREATE TABLE rate_row ({', '.join(f'{n} {t}' for n, t in cols)})")
    names = [n for n, _ in cols]
    sql = f"INSERT INTO rate_row ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})"
    n = 0
    for batch in pq.ParquetFile(parquet).iter_batches(batch_size=50_000):
        rows = []
        for r in batch.to_pylist():
            rows.append(
                tuple(v.isoformat() if isinstance(v, date) else v for v in (r[k] for k in names))
            )
        con.executemany(sql, rows)
        n += len(rows)
    con.execute("CREATE UNIQUE INDEX ux_rate_row_id ON rate_row(source_id, row_id)")
    con.execute("CREATE INDEX ix_rate_row_lookup ON rate_row(code, entity_id, payer_id)")
    con.commit()
    con.close()
    return n


Materialize = Callable[[SourceSpec, FetchRecord], None]
"""Stage + normalize one stored copy (used for a fallback copy whose files are not built yet)."""


def _info(
    spec: SourceSpec, rec: FetchRecord, paths: Paths, materialize: Materialize | None
) -> dict[str, Any] | None:
    norm = paths.normalized / spec.source_id / f"{rec.sha256}.parquet"
    stage_meta = paths.staging / spec.source_id / f"{rec.sha256}.meta.json"
    ready = norm.exists() and norm.with_suffix(".stats.json").exists() and stage_meta.exists()
    if not ready and materialize is not None and rec.path.exists():
        try:
            materialize(spec, rec)
        except Exception:  # noqa: BLE001 - a broken fallback copy is just not a candidate
            return None
        ready = norm.exists() and norm.with_suffix(".stats.json").exists() and stage_meta.exists()
    if not ready:
        return None
    stats = json.loads(norm.with_suffix(".stats.json").read_text())
    smeta = json.loads(stage_meta.read_text())
    return {
        "path": norm,
        "sha256": rec.sha256,
        "bytes": rec.bytes,
        "fetch_method": rec.method,
        "url": rec.url,
        "fetched_at": rec.fetched_at,
        "http_last_modified": rec.http_last_modified,
        "raw_file": smeta["raw_file"],
        # D18 side (a): the publisher's own date, from the file header (never our fetch date)
        "last_updated_on": smeta["meta"]["last_updated_on"],
        "type_2_npis": smeta["meta"]["type_2_npis"],
        "staged_rows": smeta["staged_rows"],
        "independent_count": smeta["independent_count"],
        "rate_rows": stats["rate_rows"],
        "payer_rate_rows": stats["payer_rate_rows"],
        "placeholders_dropped": stats["placeholders_dropped"],
        "excluded": stats["excluded"],
        "ambiguous_rows": stats["ambiguous_rows"],
        "above_gross_rows": stats["above_gross_rows"],
    }


_ANCHOR_COLS = ["entity_id", "code", "payer_raw", "plan_raw", "rev_code", "amount", "source_sha256"]


def _source_gates(
    spec: SourceSpec,
    info: dict[str, Any],
    prev: dict[str, Any] | None,
    gates_cfg: dict[str, Any],
) -> list[gates.GateResult]:
    """Every gate that judges ONE source's copy (so a failure can fall back per source)."""
    sid = spec.source_id
    missing = [n for n in spec.npis if n not in info["type_2_npis"]]
    out = [
        gates.GateResult(
            "npi", sid, "fail" if missing else "pass",
            f"registry NPIs missing from file: {missing}" if missing else "ok",
        )
    ]  # fmt: skip
    out += gates.check_row_counts(
        {sid: info}, {sid: prev} if prev else None, gates_cfg["row_count"]
    )
    anchors = [a for a in gates_cfg["anchors"] if a["entity_id"] == spec.entity_id]
    if anchors:
        rows = pq.read_table(info["path"], columns=_ANCHOR_COLS).to_pylist()
        out += gates.check_anchors(rows, anchors)
    return out


def _records_for(paths: Paths, sid: str, sha: str) -> FetchRecord | None:
    """The newest manifest line for this exact copy (its own fetched_at), if still in the store."""
    recs = [r for r in read_manifest(paths) if r.source_id == sid and r.sha256 == sha]
    return recs[-1] if recs and recs[-1].path.exists() else None


def _demote(results: list[gates.GateResult], why: str) -> list[gates.GateResult]:
    return [
        gates.GateResult(r.gate, r.subject, "warn", f"{why}: {r.detail}")
        if r.status == "fail"
        else r
        for r in results
    ]


def run_build(
    paths: Paths,
    sources: SourcesFile,
    gates_cfg: dict[str, Any],
    today: date | None = None,
    *,
    config_dir: Path | None = None,
    baseline_manifest: Path | None = None,
    first_build: bool = False,
    materialize: Materialize | None = None,
) -> BuildResult:
    today = today or date.today()
    pins = load_pins(config_dir)
    baseline = load_baseline(paths, baseline_manifest)
    results: list[gates.GateResult] = []
    if baseline is None and not first_build:
        results.append(
            gates.GateResult(
                "baseline", "build", "fail",
                "no row-count baseline (no LATEST build): pass --baseline-manifest <manifest.json>, "
                "or --first-build for a deliberate first build",
            )
        )  # fmt: skip

    present: dict[str, dict[str, Any]] = {}
    fallbacks: dict[str, dict[str, Any]] = {}
    for spec in sources.rate_row_sources:
        sid = spec.source_id
        prev = (baseline or {}).get(sid)
        cands: list[tuple[str, FetchRecord, str]] = []
        cur = current(paths, sid)
        if cur is not None:
            cands.append(("current", cur, "latest fetch"))
        fb_shas: list[tuple[str, str, str]] = []
        if sid in pins:
            pin = pins[sid]
            fb_shas.append(
                (
                    "pin",
                    pin["sha256"],
                    f"{PINS_FILE}: {pin['reason']} ({pin['set_by']}, {pin['date']})",
                )
            )
        if prev and prev.get("sha256"):
            fb_shas.append(("last_good", prev["sha256"], "sha of the baseline build"))
        for role, sha, why in fb_shas:
            if any(c[1].sha256 == sha for c in cands):
                continue
            rec = _records_for(paths, sid, sha)
            if rec is not None:
                cands.append((role, rec, why))
        tried: list[tuple[str, FetchRecord, list[gates.GateResult]]] = []
        chosen: tuple[str, FetchRecord, str, dict[str, Any], list[gates.GateResult]] | None = None
        for role, rec, why in cands:
            info = _info(spec, rec, paths, None if role == "current" else materialize)
            if info is None:
                res = [
                    gates.GateResult(
                        "source_present",
                        sid,
                        "fail",
                        f"{role} copy {rec.sha256[:12]} is not staged/normalized",
                    )
                ]
            else:
                res = _source_gates(spec, info, prev, gates_cfg)
            if info is not None and not gates.failed(res):
                chosen = (role, rec, why, info, res)
                break
            tried.append((role, rec, res))
        if chosen is None:
            if not tried:
                results.append(
                    gates.GateResult(
                        "source_present",
                        sid,
                        "fail",
                        "nothing fetched and no pinned / last-good copy",
                    )
                )
            for role, rec, res in tried:  # keep every fail: this source has no good copy
                results += [
                    gates.GateResult(
                        g.gate, g.subject, g.status, f"{role} {rec.sha256[:12]}: {g.detail}"
                    )
                    for g in res
                ]
            if tried and all(role == "current" for role, _, _ in tried):
                results.append(
                    gates.GateResult(
                        "fallback",
                        sid,
                        "fail",
                        "no pinned or last-good copy in the store to fall back to",
                    )
                )
            continue
        role, rec, why, info, res = chosen
        results.append(
            gates.GateResult("source_present", sid, "pass", f"{role} copy {rec.sha256[:12]}")
        )
        if tried:
            failed_detail = "; ".join(
                f"{g.gate}: {g.detail}" for _, _, r in tried for g in r if g.status == "fail"
            )
            results += [
                g
                for _, _, r in tried
                for g in _demote(r, f"not shipped ({role} copy used instead)")
            ]
            fallbacks[sid] = {
                "used": role,
                "used_sha256": rec.sha256,
                "used_fetched_at": rec.fetched_at,
                "why_this_copy": why,
                "rejected_sha256": tried[0][1].sha256,
                "rejected_because": failed_detail,
            }
            results.append(
                gates.GateResult(
                    "fallback", sid, "warn",
                    f"current copy {tried[0][1].sha256[:12]} failed ({failed_detail}); built from {role} "
                    f"{rec.sha256[:12]} fetched_at {rec.fetched_at} (stale on our side until fixed)",
                )
            )  # fmt: skip
        results += res
        info["fallback"] = fallbacks.get(sid)
        present[sid] = info

    results += gates.check_staleness(
        {
            sid: (
                date.fromisoformat(p["last_updated_on"]) if p["last_updated_on"] else None,
                datetime.fromisoformat(p["fetched_at"]).date(),
            )
            for sid, p in present.items()
        },
        today,
        gates_cfg["staleness"],
    )

    digest = hashlib.sha1(
        "|".join(f"{k}:{v['sha256']}" for k, v in sorted(present.items())).encode()
    )
    base_id = f"{today:%Y%m%d}-{digest.hexdigest()[:8]}"
    build_id, n = base_id, 1
    while (paths.builds / build_id).exists():  # never rewrite an existing build in place
        n += 1
        build_id = f"{base_id}-{n}"
    paths.builds.mkdir(parents=True, exist_ok=True)
    tmp = paths.builds / f".tmp-{build_id}-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        parquet = tmp / "rate_row.parquet"
        with pq.ParquetWriter(parquet, RATE_ROW_SCHEMA, compression="zstd") as w:
            for sid in sorted(present):
                w.write_table(pq.read_table(present[sid]["path"]).cast(RATE_ROW_SCHEMA))
        n_sql = _sqlite(parquet, tmp / "rate_row.sqlite")
        total = sum(p["rate_rows"] for p in present.values())
        if n_sql != total:
            results.append(
                gates.GateResult(
                    "sqlite_rows", "build", "fail", f"sqlite {n_sql} != rate_rows {total}"
                )
            )
        ok = not gates.failed(results)
        manifest = {
            "build_id": build_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "build_date": today.isoformat(),
            "ok": ok,
            "rate_rows": total,
            "baseline": str(baseline_manifest)
            if baseline_manifest
            else ("LATEST" if baseline else None),
            "sources": {
                sid: {k: v for k, v in p.items() if k != "path"}
                for sid, p in sorted(present.items())
            },
            "gates": [r.to_json() for r in results],
        }
        (tmp / "manifest.json").write_text(
            json.dumps(manifest, indent=1, sort_keys=True, default=str)
        )
        (tmp / "gates.json").write_text(json.dumps([r.to_json() for r in results], indent=1))
        out = paths.builds / build_id
        os.replace(tmp, out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if ok:
        _write_latest(paths, build_id)
    return BuildResult(build_id, out, ok, results, fallbacks)
