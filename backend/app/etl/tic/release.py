"""Monthly ``tic-YYYY-MM`` release: one set of assets per network + a manifest.

Assets are flat files (GitHub Release assets have no directories)::

    <source_id>__rate_row.parquet   matched rate rows (RateRow + tic_* columns)
    <source_id>__prices.parquet     every staged price of the target codes (all providers)
    <source_id>__items.parquet      target item headers
    <source_id>__groups.parquet     every provider group (TIN + NPI list) of the file
    <source_id>__index.ckpt.parquet / __index.items.parquet / __index.json   sparse seek index
    <source_id>__run.json           pass metrics, stage + normalize stats, fetch info
    tic_rate_row.parquet            all networks' rate rows concatenated
    manifest.json                   per network: status ok | fallback | missing, sha256, bytes,
                                    fetched_at, publisher_last_updated_on, rows, from_release

A network whose run failed this month is copied from ``--previous`` (last month's release,
downloaded first by the workflow) with ``status: fallback`` and its *old* ``fetched_at``, so the
UI shows it as stale on our side. Every file is written to a temp name and ``os.replace``d.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.etl.config import Paths
from app.etl.tic.index import atomic_write_text
from app.etl.tic.networks import TicNetwork
from app.etl.tic.normalize import TIC_RATE_ROW_SCHEMA
from app.etl.tic.run import current_dir, tic_root

PARTS = ("rate_row.parquet", "prices.parquet", "items.parquet", "groups.parquet",
         "index.ckpt.parquet", "index.items.parquet", "index.json", "run.json")  # fmt: skip


def _copy(src: Path, dst: Path) -> None:
    tmp = dst.with_name(f".{dst.name}.tmp-{os.getpid()}")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _last_status(paths: Paths, source_id: str) -> dict[str, Any] | None:
    m = tic_root(paths) / "fetch_manifest.jsonl"
    if not m.exists():
        return None
    last = None
    for line in m.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            if d.get("source_id") == source_id:
                last = d
    return last


def assemble(
    paths: Paths, nets: list[TicNetwork], month: str, out: Path, previous: Path | None
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    prev_manifest: dict[str, Any] = {}
    if previous and (previous / "manifest.json").exists():
        prev_manifest = json.loads((previous / "manifest.json").read_text()).get("networks", {})
    entries: dict[str, dict[str, Any]] = {}
    for net in nets:
        sid = net.source_id
        d = current_dir(paths, sid)
        last = _last_status(paths, sid)
        this_month_ok = (
            d is not None
            and last is not None
            and last.get("status") == "ok"
            and (d / "rate_row.parquet").exists()
        )
        if this_month_ok:
            assert d is not None and last is not None
            run = json.loads((d / "run.json").read_text())
            for part in PARTS:
                if (d / part).exists():
                    _copy(d / part, out / f"{sid}__{part}")
            entries[sid] = {
                "status": "ok", "payer_id": net.payer_id, "label": net.label,
                "file": run["source_file"], "sha256": run["source_sha256"],
                "bytes": run["comp_bytes"], "raw_bytes": run["raw_bytes"],
                "fetched_at": run["fetch"].get("fetched_at"),
                "publisher_last_updated_on": run.get("last_updated_on"),
                "rate_rows": (run.get("normalize") or {}).get("rate_rows"),
                "from_release": f"tic-{month}",
            }  # fmt: skip
            continue
        pe = prev_manifest.get(sid)
        if (
            previous
            and pe
            and all((previous / f"{sid}__{p}").exists() for p in ("rate_row.parquet",))
        ):
            for part in PARTS:
                src = previous / f"{sid}__{part}"
                if src.exists():
                    _copy(src, out / f"{sid}__{part}")
            entries[sid] = {**pe, "status": "fallback",
                            "fallback_reason": (last or {}).get("error") or "no successful run this month",
                            "from_release": pe.get("from_release")}  # fmt: skip
            continue
        entries[sid] = {"status": "missing", "payer_id": net.payer_id, "label": net.label,
                        "error": (last or {}).get("error") or "never run"}  # fmt: skip
    # concatenated rate rows (ok + fallback networks)
    tables = [
        pq.read_table(out / f"{sid}__rate_row.parquet").cast(TIC_RATE_ROW_SCHEMA)
        for sid, e in sorted(entries.items())
        if e["status"] in ("ok", "fallback") and (out / f"{sid}__rate_row.parquet").exists()
    ]
    all_rows = pa.concat_tables(tables) if tables else TIC_RATE_ROW_SCHEMA.empty_table()
    tmp = out / f".tic_rate_row.parquet.tmp-{os.getpid()}"
    pq.write_table(all_rows, tmp, compression="zstd")
    os.replace(tmp, out / "tic_rate_row.parquet")
    manifest = {
        "release": f"tic-{month}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rate_rows": all_rows.num_rows,
        "networks": entries,
    }
    atomic_write_text(out / "manifest.json", json.dumps(manifest, indent=1, sort_keys=True))
    counts = {
        s: sum(1 for e in entries.values() if e["status"] == s)
        for s in ("ok", "fallback", "missing")
    }
    return {**counts, "networks": entries}
