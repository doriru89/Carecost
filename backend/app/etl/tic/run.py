"""One payer x network job: one sequential pass over the in-network file.

    source (local file, or an HTTP stream through fetch.http_open)
      -> sha256 + byte count of the compressed bytes as they pass
      -> zran.InflatePass (seek checkpoints, decompressed-bytes cap)
      -> scan.scan (target items + provider_references + item map)
      -> stage.Stager (prices / items / groups Parquet, row conservation)
      -> index.save_index (checkpoints + item map)
    then normalize.normalize_network (rate_row Parquet).

Layout (all written to a temp name, then ``os.replace``)::

    data/intermediate/tic/<source_id>/<sha256>/   index.*, prices/items/groups.parquet,
                                                  stage.json, rate_row.parquet, normalize.json,
                                                  verify.json, run.json
    data/intermediate/tic/<source_id>/CURRENT     sha256 of the last good run
    data/intermediate/tic/fetch_manifest.jsonl    one line per pass (sha, bytes, fetched_at, ...)

No raw file is needed on disk: on a GitHub runner the pass reads the HTTP stream directly.
"""

from __future__ import annotations

import hashlib
import json
import resource
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.etl import fetch
from app.etl.config import Paths, load_sources
from app.etl.tic.index import IndexMeta, atomic_write_text, save_index
from app.etl.tic.networks import TicNetwork, target_codes
from app.etl.tic.scan import ScanResult, TargetItem, scan
from app.etl.tic.stage import Stager, stats_json
from app.etl.tic.zran import InflatePass

SPAN = 16 << 20
SIZE_DROP_FAIL = 0.5  # a file < 50% of the previous fetch of the same network fails that network


class TicRunError(RuntimeError):
    pass


def tic_root(paths: Paths) -> Path:
    return paths.data / "intermediate" / "tic"


@dataclass
class FetchInfo:
    """Where the bytes came from. ``fetched_at`` is when we read them from the publisher (for a
    local copy: the time it was downloaded, from its ``.fetch.json`` sidecar)."""

    url: str  # redacted (no query string)
    fetched_at: str
    http_last_modified: str | None = None
    etag: str | None = None
    final_host: str | None = None
    local_copy: str | None = None  # basename of the local file, when read from disk


@dataclass
class RunResult:
    source_id: str
    payer_id: str
    source_file: str
    source_sha256: str
    comp_bytes: int
    raw_bytes: int
    last_updated_on: str | None
    reporting_entity_name: str
    fetch: dict[str, Any]
    seconds_pass: float
    download_mb_s: float | None
    inflate_gb_s: float
    peak_rss_mb: float
    items: int
    target_items: int
    checkpoints: int
    index_bytes: int
    stage: dict[str, Any] = field(default_factory=dict)
    normalize: dict[str, Any] = field(default_factory=dict)
    out_dir: str = ""
    target_codes: list[str] = field(default_factory=list)  # the code list this run was cut for (R9)


class _Tee:
    """Compressed chunks -> sha256 + byte count (and download timing)."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self.chunks = chunks
        self.h = hashlib.sha256()
        self.n = 0

    def __iter__(self) -> Iterator[bytes]:
        for c in self.chunks:
            self.h.update(c)
            self.n += len(c)
            yield c


def file_chunks(path: Path, size: int = 1 << 22) -> Iterator[bytes]:
    with path.open("rb") as f:
        while b := f.read(size):
            yield b


def http_chunks(net: TicNetwork, allowed: list[str]) -> tuple[Iterator[bytes], dict[str, Any]]:
    """Stream the network's file over HTTP (allowlist per hop, byte cap)."""
    info: dict[str, Any] = {}

    def gen() -> Iterator[bytes]:
        with fetch.http_open(net.url, allowed, timeout_s=3600) as (resp, final):
            if resp.status_code != 200:
                raise TicRunError(f"{net.source_id}: HTTP {resp.status_code}")
            info.update(
                final_host=fetch.urlparse(final).hostname,
                http_last_modified=resp.headers.get("last-modified"),
                etag=resp.headers.get("etag"),
                content_length=resp.headers.get("content-length"),
            )
            yield from fetch.capped_chunks(resp, net.max_bytes, net.source_id, 1 << 22)

    return gen(), info


def previous_bytes(paths: Paths, source_id: str) -> int | None:
    """Bytes of the last successful pass of this network (local manifest)."""
    m = tic_root(paths) / "fetch_manifest.jsonl"
    if not m.exists():
        return None
    last = None
    for line in m.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            if d["source_id"] == source_id and d.get("status") == "ok":
                last = d["bytes"]
    return last


def check_size_drop(new: int, prev: int | None, source_id: str) -> None:
    if prev and new < prev * (1 - SIZE_DROP_FAIL):
        raise TicRunError(
            f"{source_id}: file is {new:,} bytes, < {1 - SIZE_DROP_FAIL:.0%} of the previous "
            f"fetch ({prev:,}); refusing it (this network only falls back to its last release)"
        )


def run_pass(
    net: TicNetwork,
    chunks: Iterator[bytes],
    fetch_info: FetchInfo,
    paths: Paths,
    codes: set[str] | None = None,
    prev_bytes: int | None = None,
) -> RunResult:
    """The single pass. Outputs go to a temp dir that is renamed to ``<sha256>`` at the end."""
    codes = codes or target_codes()
    root = tic_root(paths) / net.source_id
    work = root / f".work-{int(time.time() * 1000)}"
    work.mkdir(parents=True, exist_ok=True)
    tee = _Tee(chunks)
    inflate = InflatePass(tee, net.container, span=SPAN, max_raw=net.max_raw)
    stager = Stager(work, net.source_id, "0" * 64)  # sha is only known at the end; patched below
    t0 = time.time()
    res: ScanResult | None = None
    try:
        for x in scan(inflate, codes):
            if isinstance(x, TargetItem):
                stager.add_item(x)
            else:
                res = x
        assert res is not None
        sha = tee.h.hexdigest()
        stager.sha = sha  # rows written so far carry the placeholder; rewritten by _fix_sha
        st = stager.finish(res)
    except BaseException:
        stager.abort()
        _rmtree(work)
        raise
    dt = time.time() - t0
    try:
        check_size_drop(tee.n, prev_bytes, net.source_id)
    except TicRunError:
        _rmtree(work)
        raise
    st.source_sha256 = sha
    _fix_sha(work, sha)
    meta = IndexMeta(
        source_id=net.source_id, source_sha256=sha, source_file=net.basename,
        container=net.container, comp_bytes=tee.n, raw_bytes=inflate.stats.raw_bytes,
        span=SPAN, checkpoints=len(inflate.checkpoints), items=len(res.items),
        provider_references_span=list(res.provider_references_span), item_key=res.item_key,
    )  # fmt: skip
    save_index(work, meta, inflate.checkpoints, res.items)
    atomic_write_text(work / "stage.json", stats_json(st))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / 1e6 if rss > 1e7 else rss / 1e3  # macOS bytes, Linux KiB
    out = root / sha
    rr = RunResult(
        source_id=net.source_id,
        payer_id=net.payer_id,
        source_file=net.basename,
        source_sha256=sha,
        comp_bytes=tee.n,
        raw_bytes=inflate.stats.raw_bytes,
        last_updated_on=str(res.header.get("last_updated_on") or "") or None,
        reporting_entity_name=str(res.header.get("reporting_entity_name") or ""),
        fetch=asdict(fetch_info),
        seconds_pass=round(dt, 1),
        download_mb_s=None,
        inflate_gb_s=round(inflate.stats.raw_bytes / dt / 1e9, 2) if dt else 0.0,
        peak_rss_mb=round(rss_mb, 0),
        items=len(res.items),
        target_items=st.target_items,
        checkpoints=len(inflate.checkpoints),
        index_bytes=sum(
            (work / n).stat().st_size
            for n in ("index.ckpt.parquet", "index.items.parquet", "index.json")
        ),
        stage=json.loads(stats_json(st)),
        out_dir=str(out),
        target_codes=sorted(codes),
    )
    atomic_write_text(work / "run.json", json.dumps(asdict(rr), indent=1, sort_keys=True))
    if out.exists():
        _rmtree(out)
    work.replace(out)
    return rr


def _fix_sha(d: Path, sha: str) -> None:
    """Rewrite the placeholder sha in the staged Parquet (known only after the last byte)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.etl.tic.index import atomic_write_table

    for name in ("prices.parquet", "items.parquet", "groups.parquet"):
        p = d / name
        t = pq.read_table(p)
        i = t.schema.get_field_index("source_sha256")
        col = pa.repeat(pa.scalar(sha, pa.string()), t.num_rows)
        atomic_write_table(t.set_column(i, "source_sha256", col), p)


def _rmtree(p: Path) -> None:
    import shutil

    shutil.rmtree(p, ignore_errors=True)


def record_fetch(paths: Paths, rr: RunResult, status: str, error: str = "") -> None:
    """Append one line to the TiC fetch manifest (redacted URL, sha, bytes, both dates)."""
    m = tic_root(paths) / "fetch_manifest.jsonl"
    m.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "source_id": rr.source_id,
        "payer_id": rr.payer_id,
        "status": status,
        "error": error,
        "source_file": rr.source_file,
        "sha256": rr.source_sha256,
        "bytes": rr.comp_bytes,
        "raw_bytes": rr.raw_bytes,
        "fetched_at": rr.fetch.get("fetched_at"),
        "publisher_last_updated_on": rr.last_updated_on,
        "http_last_modified": rr.fetch.get("http_last_modified"),
        "url": fetch.redact(rr.fetch.get("url") or ""),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with m.open("a") as f:
        f.write(json.dumps(line, sort_keys=True) + "\n")


def set_current(paths: Paths, source_id: str, sha: str) -> None:
    atomic_write_text(tic_root(paths) / source_id / "CURRENT", sha + "\n")


def current_dir(paths: Paths, source_id: str) -> Path | None:
    p = tic_root(paths) / source_id / "CURRENT"
    if not p.exists():
        return None
    d = tic_root(paths) / source_id / p.read_text().strip()
    return d if d.exists() else None


def allowlist() -> list[str]:
    return load_sources().fetch.allowed_domains
