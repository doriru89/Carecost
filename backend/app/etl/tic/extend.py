"""``tic extend``: add codes to a network's current run without a full re-run (R9).

Staging keeps only the in_network items of the codes it was cut for, so a code added to the
list (a new care path) is absent until its items are read. ``extend`` reads only those items:

* **range** (default when the publisher answers ``206``): the seek index of the current run
  names each item's raw byte span; each item is re-inflated from the nearest checkpoint with
  HTTP Range reads (or from a local copy, ``--local-dir``). Before any item is read, the remote
  file must be the one the index was built from: same total size (Content-Range) and, when both
  are known, the same Last-Modified; then one already-staged item is re-read and must give the
  same price rows. Any mismatch aborts the network (its CURRENT stays as it is).
* **stream** (a host that ignores Range, e.g. mrfstorage.uhc.com): one full pass over the file
  scanning for the new codes only; the stream's sha256 must equal the run's, else it aborts.

New price rows are numbered after the existing ``stage_row``s, so every row reference already
cited (``source:sha:stage_row``) still points at the same row. Provider groups of the file head
are already staged; the head groups are re-checked for placeholder NPIs (R10) and the new
items' inline groups appended. The merged run is written to a sibling directory and swapped in
with renames; ``run.json`` gains ``target_codes`` (the list this run now covers) and an
``extends`` entry (codes, items, bytes, how, when). ``tic normalize`` runs on it afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.etl import fetch as fetch_mod
from app.etl.npi import clean_npis
from app.etl.npi import count as count_npis
from app.etl.tic.index import SeekIndex, atomic_write_table, atomic_write_text, load_index
from app.etl.tic.networks import TicNetwork
from app.etl.tic.ranged import FetchCounter, http_fetcher, read_item
from app.etl.tic.run import TicRunError, _Tee, http_chunks
from app.etl.tic.scan import ScanResult, TargetItem, scan
from app.etl.tic.stage import GROUP_SCHEMA, ITEMS_SCHEMA, PRICE_SCHEMA, Stager
from app.etl.tic.zran import Fetch, InflatePass, file_fetcher


def staged_codes(d: Path) -> set[str]:
    return set(pq.read_table(d / "items.parquet", columns=["billing_code"]).column(0).to_pylist())


def done_codes(run: dict[str, Any], legacy: set[str]) -> set[str]:
    """The list a run was cut with: ``run.json`` ``target_codes``; runs from before R9 did not
    record it and were cut with the hand-written list (codes.yaml domains + visit codes)."""
    got = run.get("target_codes")
    return set(got) if got is not None else set(legacy)


def clean_groups(t: pa.Table) -> tuple[pa.Table, Counter[str]]:
    """Drop placeholder NPIs from already-staged groups (R10); raw values go to ``extra``."""
    rows = t.to_pylist()
    dropped: Counter[str] = Counter()
    changed = False
    for r in rows:
        kept, bad = clean_npis(r["npis"] or [])
        if not bad:
            continue
        changed = True
        dropped.update(count_npis(bad))
        ex = json.loads(r["extra"]) if r["extra"] else {}
        ex["dropped_npis"] = sorted(set(ex.get("dropped_npis", [])) | set(bad))
        r["npis"], r["n_npi"], r["extra"] = kept, len(kept), json.dumps(ex, sort_keys=True)
    return (pa.Table.from_pylist(rows, GROUP_SCHEMA) if changed else t), dropped


def remote_identity(url: str, allowed: list[str]) -> dict[str, Any]:
    """One 1-byte Range request: does the host do Range, and which file is it."""
    with fetch_mod.http_open(url, allowed, byte_range=(0, 1), timeout_s=120) as (resp, final):
        cr = resp.headers.get("content-range") or ""
        total = int(cr.rsplit("/", 1)[1]) if resp.status_code == 206 and "/" in cr else None
        return {
            "status": resp.status_code,
            "total": total,
            "last_modified": resp.headers.get("last-modified"),
            "final_host": fetch_mod.urlparse(final).hostname,
        }


def _check_same_file(ident: dict[str, Any], idx: SeekIndex, run: dict[str, Any], sid: str) -> None:
    if ident["total"] != idx.meta.comp_bytes:
        raise TicRunError(
            f"{sid}: remote file is {ident['total']} bytes, the indexed run {idx.meta.comp_bytes}; "
            "the publisher replaced it, so a full `tic run` is due instead"
        )
    lm, was = ident.get("last_modified"), (run.get("fetch") or {}).get("http_last_modified")
    if lm and was and lm != was:
        raise TicRunError(f"{sid}: remote Last-Modified {lm!r} != the run's {was!r}")


def _probe_item(idx: SeekIndex, d: Path, fetch: Fetch, sid: str) -> None:
    """Re-read the smallest already-staged item; its rows must equal the staged ones."""
    staged = staged_codes(d)
    refs = [r for r in idx.items if r.billing_code in staged]
    if not refs:
        return
    ref = min(refs, key=lambda r: r.raw_end - r.raw_start)
    t = read_item(idx, ref, fetch)
    tmp = d.parent / f".probe-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    st = Stager(tmp, sid, idx.meta.source_sha256)
    try:
        st.add_item(t)
        st.finish(ScanResult())
        got = pq.read_table(tmp / "prices.parquet").drop(["stage_row"]).to_pylist()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    have = (
        pq.read_table(d / "prices.parquet", filters=[("item_ordinal", "=", ref.ordinal)])
        .drop(["stage_row"])
        .to_pylist()
    )
    if got != have:
        raise TicRunError(f"{sid}: re-read of staged item {ref.ordinal} differs; file changed")


def _items_by_range(
    idx: SeekIndex, new: set[str], fetch: Fetch
) -> tuple[list[TargetItem], int, int]:
    fc = FetchCounter(fetch)
    items = [read_item(idx, ref, fc) for ref in idx.items_for(new)]
    return items, fc.bytes, fc.calls


def _items_by_stream(
    net: TicNetwork, chunks: Any, idx: SeekIndex, new: set[str]
) -> tuple[list[TargetItem], int]:
    tee = _Tee(chunks)
    items: list[TargetItem] = []
    for x in scan(InflatePass(tee, net.container, max_raw=net.max_raw), new):
        if isinstance(x, TargetItem):
            items.append(x)
    sha = tee.h.hexdigest()
    if sha != idx.meta.source_sha256:
        raise TicRunError(
            f"{net.source_id}: streamed sha {sha[:12]} != run sha {idx.meta.source_sha256[:12]}; "
            "the publisher replaced the file, so a full `tic run` is due instead"
        )
    want = [r.ordinal for r in idx.items_for(new)]
    if [t.ref.ordinal for t in items] != want:
        raise TicRunError(f"{net.source_id}: stream items {len(items)} != index items {len(want)}")
    return items, tee.n


def extend_network(
    net: TicNetwork,
    d: Path,
    codes_now: set[str],
    *,
    legacy: set[str],
    allowed: list[str],
    local_copy: Path | None = None,
    url: str | None = None,
    log: Any = print,
) -> dict[str, Any]:
    """Bring the run in ``d`` (a CURRENT run dir) up to ``codes_now``. -> the ``extends`` entry."""
    run = json.loads((d / "run.json").read_text())
    idx = load_index(d)
    sid = net.source_id
    done = done_codes(run, legacy)
    in_file = {r.billing_code for r in idx.items}
    new = {c for c in codes_now - done if c in in_file and c not in staged_codes(d)}
    entry: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "codes_added": sorted(codes_now - done),
        "codes_in_file": sorted(new),
        "items": 0,
        "price_rows": 0,
        "how": "none",
        "bytes": 0,
    }
    t0 = time.time()
    items: list[TargetItem] = []
    if new:
        if local_copy is not None:
            fetch = file_fetcher(str(local_copy))
            _probe_item(idx, d, fetch, sid)
            items, entry["bytes"], _ = _items_by_range(idx, new, fetch)
            entry["how"] = "local_copy"
        else:
            u = url or run["fetch"]["url"]
            ident = remote_identity(u, allowed)
            if ident["status"] == 206:
                _check_same_file(ident, idx, run, sid)
                fetch = http_fetcher(u, allowed)
                _probe_item(idx, d, fetch, sid)
                items, entry["bytes"], calls = _items_by_range(idx, new, fetch)
                entry["how"] = f"http_range ({calls} reads)"
            else:
                log(f"       {sid}: host answered {ident['status']} to Range; streaming the file")
                chunks, _hdr = http_chunks(TicNetwork(**{**net.__dict__, "url": u}), allowed)
                items, entry["bytes"] = _items_by_stream(net, chunks, idx, new)
                entry["how"] = "http_stream (host ignores Range; sha256 checked)"
    entry["items"] = len(items)
    entry["seconds"] = round(time.time() - t0, 1)
    _merge(d, run, idx, items, entry, codes_now)
    return entry


def _merge(
    d: Path,
    run: dict[str, Any],
    idx: SeekIndex,
    items: list[TargetItem],
    entry: dict[str, Any],
    codes_now: set[str],
) -> None:
    sid, sha = idx.meta.source_id, idx.meta.source_sha256
    old_prices = pq.read_table(d / "prices.parquet")
    start = (max(old_prices.column("stage_row").to_pylist()) + 1) if old_prices.num_rows else 0
    work = d.parent / f".extend-{d.name[:12]}-{os.getpid()}"
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(d, work)
    try:
        add = work / ".add"
        st = Stager(add, sid, sha, stage_row_start=start)
        for t in items:
            st.add_item(t)
        stats = st.finish(ScanResult())
        new_prices = pq.read_table(add / "prices.parquet")
        new_items = pq.read_table(add / "items.parquet")
        new_groups = pq.read_table(add / "groups.parquet")
        shutil.rmtree(add)
        prices = pa.concat_tables([old_prices, new_prices.cast(PRICE_SCHEMA)])
        it = pa.concat_tables([pq.read_table(d / "items.parquet"), new_items.cast(ITEMS_SCHEMA)])
        groups, dropped = clean_groups(pq.read_table(d / "groups.parquet"))
        groups = pa.concat_tables([groups.cast(GROUP_SCHEMA), new_groups.cast(GROUP_SCHEMA)])
        atomic_write_table(prices, work / "prices.parquet")
        atomic_write_table(it, work / "items.parquet")
        atomic_write_table(groups, work / "groups.parquet")
        entry["price_rows"] = stats.price_rows
        entry["inline_group_rows"] = stats.inline_group_rows
        entry["codes"] = dict(sorted(stats.codes.items()))
        npi = Counter(run.get("stage", {}).get("npi_placeholders_dropped") or {})
        npi.update(dropped)
        npi.update(stats.npi_placeholders_dropped)
        s = dict(run.get("stage") or {})
        s["target_items"] = s.get("target_items", 0) + stats.target_items
        s["price_rows"] = s.get("price_rows", 0) + stats.price_rows
        s["prices_parsed"] = s.get("prices_parsed", 0) + stats.prices_parsed
        s["independent_prices"] = s.get("independent_prices", 0) + stats.independent_prices
        s["empty_rate_groups"] = s.get("empty_rate_groups", 0) + stats.empty_rate_groups
        s["group_rows"] = s.get("group_rows", 0) + stats.group_rows
        s["inline_group_rows"] = s.get("inline_group_rows", 0) + stats.inline_group_rows
        s["codes"] = dict(sorted({**(s.get("codes") or {}), **stats.codes}.items()))
        s["npi_placeholders_dropped"] = dict(sorted(npi.items()))
        run["stage"] = s
        run["target_items"] = s["target_items"]
        run["target_codes"] = sorted(codes_now)
        run["extends"] = [*(run.get("extends") or []), entry]
        atomic_write_text(work / "stage.json", json.dumps(s, indent=1, sort_keys=True))
        atomic_write_text(work / "run.json", json.dumps(run, indent=1, sort_keys=True, default=str))
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    old = d.parent / f".prev-{d.name[:12]}-{os.getpid()}"
    d.replace(old)
    work.replace(d)
    shutil.rmtree(old, ignore_errors=True)
