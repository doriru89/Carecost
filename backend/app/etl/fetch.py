"""Stage 1: fetch source files into a content-addressed store.

``raw/store/<source_id>/<sha256><ext>`` + one JSON line per attempt in ``fetch_manifest.jsonl``.
Downloads must stay on ``fetch.allowed_domains`` (every redirect hop is checked) and under the
size cap (Content-Length and the actual stream are both checked). Unchanged content is a no-op
(``status: unchanged``), so downstream stages can skip it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.etl.config import FetchSettings, Paths, SourceSpec

MAX_REDIRECTS = 5
USER_AGENT = "CareCost-ETL/1.0 (+price transparency research; contact via repo)"


class FetchError(RuntimeError):
    pass


def host_allowed(host: str, domains: list[str]) -> bool:
    host = (host or "").lower().rstrip(".")
    return bool(host) and any(host == d or host.endswith("." + d) for d in domains)


@dataclass
class FetchRecord:
    source_id: str
    method: str  # download | import
    url: str | None
    final_url: str | None
    sha256: str
    bytes: int
    relpath: str  # relative to the store
    fetched_at: str
    http_last_modified: str | None
    etag: str | None
    status: str  # new | unchanged
    store: str = ""

    @property
    def path(self) -> Path:
        return Path(self.store) / self.relpath


def _ext(spec: SourceSpec, url: str | None) -> str:
    name = urlparse(url).path if url else (spec.legacy_filename or "")
    low = name.lower()
    for e in (".csv.zip", ".json.gz", ".zip", ".csv", ".json", ".gz", ".xlsx", ".pdf", ".html"):
        if low.endswith(e):
            return ".zip" if e == ".csv.zip" else e
    return ".bin"


def _append(paths: Paths, rec: FetchRecord) -> None:
    paths.store.mkdir(parents=True, exist_ok=True)
    d = asdict(rec)
    d.pop("store")
    with paths.fetch_manifest.open("a") as f:
        f.write(json.dumps(d, sort_keys=True) + "\n")


def read_manifest(paths: Paths) -> list[FetchRecord]:
    if not paths.fetch_manifest.exists():
        return []
    out = []
    for line in paths.fetch_manifest.read_text().splitlines():
        if line.strip():
            out.append(FetchRecord(**json.loads(line), store=str(paths.store)))
    return out


def current(paths: Paths, source_id: str) -> FetchRecord | None:
    """The most recent stored copy of a source (last manifest line for it)."""
    recs = [r for r in read_manifest(paths) if r.source_id == source_id]
    return recs[-1] if recs else None


def _finish(
    spec: SourceSpec, paths: Paths, tmp: Path, sha: str, size: int, ext: str, **kw: Any
) -> FetchRecord:
    rel = f"{spec.source_id}/{sha}{ext}"
    dest = paths.store / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    status = "unchanged" if dest.exists() else "new"
    if status == "new":
        os.replace(tmp, dest)
    else:
        tmp.unlink(missing_ok=True)
    rec = FetchRecord(
        source_id=spec.source_id,
        sha256=sha,
        bytes=size,
        relpath=rel,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        status=status,
        store=str(paths.store),
        **kw,
    )
    _append(paths, rec)
    return rec


def fetch_source(
    spec: SourceSpec, settings: FetchSettings, paths: Paths, client: httpx.Client | None = None
) -> FetchRecord:
    if not spec.url:
        raise FetchError(f"{spec.source_id}: no url in sources.yaml (import it with --import-dir)")
    cap = spec.max_bytes or settings.default_max_bytes
    own = client is None
    client = client or httpx.Client(timeout=settings.timeout_s, headers={"User-Agent": USER_AGENT})
    url = spec.url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            host = urlparse(url).hostname or ""
            if urlparse(url).scheme != "https" or not host_allowed(host, settings.allowed_domains):
                raise FetchError(f"{spec.source_id}: {url} is not https on the domain allowlist")
            with client.stream("GET", url, follow_redirects=False) as resp:
                if resp.is_redirect:
                    url = urljoin(url, resp.headers.get("location", ""))
                    continue
                if resp.status_code != 200:
                    raise FetchError(f"{spec.source_id}: HTTP {resp.status_code} for {url}")
                declared = resp.headers.get("content-length")
                if declared and int(declared) > cap:
                    raise FetchError(
                        f"{spec.source_id}: {declared} bytes exceeds the {cap}-byte cap"
                    )
                paths.store.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                size = 0
                fd, name = tempfile.mkstemp(
                    dir=paths.store, prefix=f".{spec.source_id}.", suffix=".part"
                )
                tmp = Path(name)
                try:
                    with os.fdopen(fd, "wb") as out:
                        for chunk in resp.iter_bytes(1 << 20):
                            size += len(chunk)
                            if size > cap:
                                raise FetchError(
                                    f"{spec.source_id}: stream exceeds the {cap}-byte cap"
                                )
                            h.update(chunk)
                            out.write(chunk)
                except BaseException:
                    tmp.unlink(missing_ok=True)
                    raise
                return _finish(
                    spec,
                    paths,
                    tmp,
                    h.hexdigest(),
                    size,
                    _ext(spec, spec.url),
                    method="download",
                    url=spec.url,
                    final_url=url,
                    http_last_modified=resp.headers.get("last-modified"),
                    etag=resp.headers.get("etag"),
                )
        raise FetchError(f"{spec.source_id}: more than {MAX_REDIRECTS} redirects")
    except httpx.HTTPError as e:
        raise FetchError(f"{spec.source_id}: {type(e).__name__}: {e}") from e
    finally:
        if own:
            client.close()


def import_local(spec: SourceSpec, src_dir: Path, paths: Paths) -> FetchRecord | None:
    """Register an existing local copy (``legacy_filename``) in the store: hardlink, else copy."""
    if not spec.legacy_filename:
        return None
    src = src_dir / spec.legacy_filename
    if not src.exists():
        return None
    h = hashlib.sha256()
    with src.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    sha = h.hexdigest()
    paths.store.mkdir(parents=True, exist_ok=True)
    tmp = paths.store / f".{spec.source_id}.{sha}.import"
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copy2(src, tmp)
    mtime = datetime.fromtimestamp(src.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    return _finish(
        spec,
        paths,
        tmp,
        sha,
        src.stat().st_size,
        _ext(spec, None),
        method="import",
        url=None,
        final_url=None,
        http_last_modified=mtime,
        etag=None,
    )
