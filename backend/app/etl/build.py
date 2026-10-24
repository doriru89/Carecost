"""Stage 5: assemble the normalized per-source files into one versioned build + run the gates.

Output (``data/build/<build_id>/``): ``rate_row.parquet``, ``rate_row.sqlite`` (what the FastAPI
runtime will ship and read; no Postgres), ``manifest.json`` and ``gates.json``. Only a build
whose gates all pass moves ``data/build/LATEST``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.etl import gates
from app.etl.config import Paths, SourcesFile
from app.etl.fetch import current
from app.etl.normalize import RATE_ROW_SCHEMA

_SQL_TYPES = {pa.int64(): "INTEGER", pa.float64(): "REAL", pa.bool_(): "INTEGER"}


@dataclass
class BuildResult:
    build_id: str
    dir: Path
    ok: bool
    gate_results: list[gates.GateResult]


def latest_build(paths: Paths) -> Path | None:
    p = paths.builds / "LATEST"
    if not p.exists():
        return None
    d = paths.builds / p.read_text().strip()
    return d if d.exists() else None


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


def run_build(
    paths: Paths,
    sources: SourcesFile,
    gates_cfg: dict[str, Any],
    today: date | None = None,
) -> BuildResult:
    today = today or date.today()
    present: dict[str, dict[str, Any]] = {}
    for spec in sources.sources:
        rec = current(paths, spec.source_id)
        if rec is None:
            continue
        norm = paths.normalized / spec.source_id / f"{rec.sha256}.parquet"
        stage_meta = paths.staging / spec.source_id / f"{rec.sha256}.meta.json"
        if not norm.exists() or not stage_meta.exists():
            continue
        stats = json.loads(norm.with_suffix(".stats.json").read_text())
        smeta = json.loads(stage_meta.read_text())
        present[spec.source_id] = {
            "path": norm,
            "sha256": rec.sha256,
            "fetch_method": rec.method,
            "fetched_at": rec.fetched_at,
            "http_last_modified": rec.http_last_modified,
            "raw_file": smeta["raw_file"],
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
    digest = hashlib.sha1(
        "|".join(f"{k}:{v['sha256']}" for k, v in sorted(present.items())).encode()
    )
    build_id = f"{today:%Y%m%d}-{digest.hexdigest()[:8]}"
    out = paths.builds / build_id
    out.mkdir(parents=True, exist_ok=True)

    # gates
    results: list[gates.GateResult] = []
    results += gates.check_sources_present([s.source_id for s in sources.sources], set(present))
    for sid, p in present.items():  # NPI check: file must still carry the registry NPIs
        missing = [n for n in sources.get(sid).npis if n not in p["type_2_npis"]]
        results.append(
            gates.GateResult(
                "npi", sid, "fail" if missing else "pass",
                f"registry NPIs missing from file: {missing}" if missing else "ok",
            )
        )  # fmt: skip
    prev = None
    lb = latest_build(paths)
    if lb is not None and (lb / "manifest.json").exists() and lb != out:
        prev = json.loads((lb / "manifest.json").read_text())["sources"]
    results += gates.check_row_counts(present, prev, gates_cfg["row_count"])
    results += gates.check_staleness(
        {
            sid: date.fromisoformat(p["last_updated_on"]) if p["last_updated_on"] else None
            for sid, p in present.items()
        },
        today,
        gates_cfg["staleness"],
    )
    anchor_entities = {a["entity_id"] for a in gates_cfg["anchors"]}
    anchor_rows: list[dict[str, Any]] = []
    cols = ["entity_id", "code", "payer_raw", "plan_raw", "rev_code", "amount", "source_sha256"]
    for sid, p in present.items():
        if sources.get(sid).entity_id in anchor_entities:
            anchor_rows += pq.read_table(p["path"], columns=cols).to_pylist()
    anchors = [
        a
        for a in gates_cfg["anchors"]
        if a["entity_id"] in {sources.get(s).entity_id for s in present}
    ]
    results += gates.check_anchors(anchor_rows, anchors)

    # assemble
    parquet = out / "rate_row.parquet"
    with pq.ParquetWriter(parquet, RATE_ROW_SCHEMA, compression="zstd") as w:
        for sid in sorted(present):
            w.write_table(pq.read_table(present[sid]["path"]).cast(RATE_ROW_SCHEMA))
    n_sql = _sqlite(parquet, out / "rate_row.sqlite")
    total = sum(p["rate_rows"] for p in present.values())
    if n_sql != total:
        results.append(
            gates.GateResult("sqlite_rows", "build", "fail", f"sqlite {n_sql} != rate_rows {total}")
        )

    ok = not gates.failed(results)
    manifest = {
        "build_id": build_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "build_date": today.isoformat(),
        "ok": ok,
        "rate_rows": total,
        "sources": {
            sid: {k: v for k, v in p.items() if k != "path"} for sid, p in sorted(present.items())
        },
        "gates": [r.to_json() for r in results],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True, default=str))
    (out / "gates.json").write_text(json.dumps([r.to_json() for r in results], indent=1))
    if ok:
        (paths.builds / "LATEST").write_text(build_id + "\n")
    return BuildResult(build_id, out, ok, results)
