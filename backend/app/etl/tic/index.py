"""Sparse seek index for one TiC file: checkpoints + item map + head span.

Stored next to the staged Parquet (``index.ckpt.parquet``, ``index.items.parquet``,
``index.json``). Windows are zlib-compressed (32 KiB of JSON text -> ~2-5 KB), so a UHC
network (188 GB raw, one checkpoint per 16 MiB) needs ~12k checkpoints, tens of MB.

With the index, reading one billing code (or the provider_references head) costs
``(item size + up to one span) / ratio`` compressed bytes via HTTP Range instead of a full pass.
"""

from __future__ import annotations

import json
import os
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.etl.tic.scan import ItemRef
from app.etl.tic.zran import Checkpoint

CKPT_SCHEMA = pa.schema(
    [
        ("raw_off", pa.int64()),
        ("comp_off", pa.int64()),
        ("bits", pa.int8()),
        ("prime_byte", pa.int16()),
        ("member", pa.int32()),
        ("window_z", pa.binary()),
    ]
)
ITEM_SCHEMA = pa.schema(
    [
        ("ordinal", pa.int64()),
        ("raw_start", pa.int64()),
        ("raw_end", pa.int64()),
        ("billing_code_type", pa.string()),
        ("billing_code", pa.string()),
        ("negotiation_arrangement", pa.string()),
    ]
)


@dataclass
class IndexMeta:
    source_id: str
    source_sha256: str
    source_file: str
    container: str
    comp_bytes: int
    raw_bytes: int
    span: int
    checkpoints: int
    items: int
    provider_references_span: list[int]
    item_key: str


def atomic_write_table(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def save_index(
    out_dir: Path, meta: IndexMeta, checkpoints: list[Checkpoint], items: list[ItemRef]
) -> None:
    ck = pa.table(
        {
            "raw_off": [c.raw_off for c in checkpoints],
            "comp_off": [c.comp_off for c in checkpoints],
            "bits": [c.bits for c in checkpoints],
            "prime_byte": [c.prime_byte for c in checkpoints],
            "member": [c.member for c in checkpoints],
            "window_z": [zlib.compress(c.window, 9) for c in checkpoints],
        },
        schema=CKPT_SCHEMA,
    )
    it = pa.table(
        {
            "ordinal": [i.ordinal for i in items],
            "raw_start": [i.raw_start for i in items],
            "raw_end": [i.raw_end for i in items],
            "billing_code_type": [i.billing_code_type for i in items],
            "billing_code": [i.billing_code for i in items],
            "negotiation_arrangement": [i.negotiation_arrangement for i in items],
        },
        schema=ITEM_SCHEMA,
    )
    atomic_write_table(ck, out_dir / "index.ckpt.parquet")
    atomic_write_table(it, out_dir / "index.items.parquet")
    atomic_write_text(out_dir / "index.json", json.dumps(asdict(meta), indent=1, sort_keys=True))


@dataclass
class SeekIndex:
    meta: IndexMeta
    checkpoints: list[Checkpoint]
    items: list[ItemRef]

    def items_for(self, codes: set[str]) -> list[ItemRef]:
        return [i for i in self.items if i.billing_code in codes]

    def bytes_on_disk(self, d: Path) -> int:
        return sum(
            (d / n).stat().st_size
            for n in ("index.ckpt.parquet", "index.items.parquet", "index.json")
        )


def load_index(d: Path) -> SeekIndex:
    meta = IndexMeta(**json.loads((d / "index.json").read_text()))
    ck: list[dict[str, Any]] = pq.read_table(d / "index.ckpt.parquet").to_pylist()
    cps = [
        Checkpoint(
            r["raw_off"],
            r["comp_off"],
            r["bits"],
            r["prime_byte"],
            zlib.decompress(r["window_z"]),
            r["member"],
        )
        for r in ck
    ]
    items = [ItemRef(**r) for r in pq.read_table(d / "index.items.parquet").to_pylist()]
    return SeekIndex(meta, cps, items)
