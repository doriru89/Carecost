"""Read target items / the provider_references head through the seek index (no full pass).

``fetch`` is any ``(comp_a, comp_b) -> bytes``: :func:`zran.file_fetcher` for a local copy, or
:func:`http_fetcher` (HTTP Range through ``fetch.http_range``: 206 + matching Content-Range or
abort). :func:`verify_against_stream` re-stages the target items read this way and checks they
equal the rows of the full-stream pass, row for row.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from app.etl import fetch as fetch_mod
from app.etl.tic.index import SeekIndex
from app.etl.tic.scan import ItemRef, ScanResult, TargetItem, _loads
from app.etl.tic.stage import Stager
from app.etl.tic.zran import Fetch, read_raw_range

_RE_PRICE = re.compile(rb'"negotiated_rate"\s*:')


class FetchCounter:
    """Wraps a fetch callable and counts the compressed bytes it pulled."""

    def __init__(self, f: Fetch) -> None:
        self.f = f
        self.bytes = 0
        self.calls = 0

    def __call__(self, a: int, b: int) -> bytes:
        data = self.f(a, b)
        self.bytes += len(data)
        self.calls += 1
        return data


def http_fetcher(url: str, allowed: list[str]) -> Fetch:
    def f(a: int, b: int) -> bytes:
        return fetch_mod.http_range(url, a, b, allowed)

    return f


def read_item(idx: SeekIndex, ref: ItemRef, fetch: Fetch) -> TargetItem:
    m = idx.meta
    raw = read_raw_range(
        idx.checkpoints, ref.raw_start, ref.raw_end, fetch, m.container, m.comp_bytes
    )
    obj = _loads(raw)
    if not isinstance(obj, dict) or obj.get("billing_code", "").strip() != ref.billing_code:
        raise ValueError(f"item {ref.ordinal}: range read did not return {ref.billing_code}")
    return TargetItem(ref, obj, len(_RE_PRICE.findall(raw)))


def read_items(idx: SeekIndex, codes: set[str], fetch: Fetch) -> Iterator[TargetItem]:
    for ref in idx.items_for(codes):
        yield read_item(idx, ref, fetch)


def read_head(idx: SeekIndex, fetch: Fetch) -> list[dict[str, Any]]:
    a, b = idx.meta.provider_references_span
    m = idx.meta
    raw = read_raw_range(idx.checkpoints, a, b, fetch, m.container, m.comp_bytes)
    refs: list[dict[str, Any]] = json.loads(raw, parse_float=str)
    return refs


def restage(idx: SeekIndex, codes: set[str], fetch: Fetch, out_dir: Path) -> tuple[Stager, Any]:
    """Stage the given codes from range reads only (head + items)."""
    st = Stager(out_dir, idx.meta.source_id, idx.meta.source_sha256)
    try:
        for t in read_items(idx, codes, fetch):
            st.add_item(t)
        a, b = idx.meta.provider_references_span
        raw_head = read_raw_range(
            idx.checkpoints, a, b, fetch, idx.meta.container, idx.meta.comp_bytes
        )
        res = ScanResult(provider_references=json.loads(raw_head, parse_float=str))
        res.independent_groups = len(re.findall(rb'"tin"\s*:', raw_head))
        stats = st.finish(res)
    except BaseException:
        st.abort()
        raise
    return st, stats


def _rows(p: Path, drop: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    t = pq.read_table(p)
    return [{k: v for k, v in r.items() if k not in drop} for r in t.to_pylist()]


def verify_against_stream(
    stream_dir: Path, idx: SeekIndex, codes: set[str], fetch: Fetch, work: Path
) -> dict[str, Any]:
    """Range-read the codes, stage them, compare with the stream-pass Parquet. -> report."""
    if work.exists():
        shutil.rmtree(work)
    fc = FetchCounter(fetch)
    _, stats = restage(idx, codes, fc, work)
    out: dict[str, Any] = {"codes": sorted(codes), "range_bytes": fc.bytes, "range_calls": fc.calls}
    sel = {r.ordinal for r in idx.items_for(codes)}
    a = [
        r for r in _rows(stream_dir / "prices.parquet", ("stage_row",)) if r["item_ordinal"] in sel
    ]
    b = _rows(work / "prices.parquet", ("stage_row",))
    out["price_rows_stream"], out["price_rows_range"] = len(a), len(b)
    out["prices_equal"] = a == b
    ga, gb = _rows(stream_dir / "groups.parquet"), _rows(work / "groups.parquet")
    ga = [g for g in ga if not g["inline"]]
    gb = [g for g in gb if not g["inline"]]
    out["group_rows_stream"], out["group_rows_range"] = len(ga), len(gb)
    out["groups_equal"] = ga == gb
    out["ok"] = bool(out["prices_equal"] and out["groups_equal"])
    shutil.rmtree(work, ignore_errors=True)
    return out
