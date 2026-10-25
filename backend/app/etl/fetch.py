"""Stage 1: fetch source files into a content-addressed store.

``raw/store/<source_id>/<sha256><ext>`` + one JSON line per attempt in ``fetch_manifest.jsonl``.
Downloads must stay on ``fetch.allowed_domains`` (every redirect hop is checked) and under the
size cap (Content-Length and the actual stream are both checked). Unchanged content is a no-op
(``status: unchanged``), so downstream stages can skip it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import ssl
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import certifi
import httpx

from app.etl.config import CONFIG_DIR, FetchSettings, Paths, SourceSpec

MAX_REDIRECTS = 5
USER_AGENT = "CareCost-ETL/1.0 (+price transparency research; contact via repo)"


class FetchError(RuntimeError):
    pass


# Shared cloud hosts: anyone can create a bucket / container / distribution under these, so an
# allowlist entry here must name the exact hostname (optionally plus a path prefix). Suffix
# matching is only for registrable domains the publisher owns (bluecrossma.com, uhc.com, ...).
SHARED_HOST_SUFFIXES = (
    "core.windows.net",  # Azure blob / static web (…blob.core.windows.net, …web.core.windows.net)
    "azurefd.net",
    "azureedge.net",
    "cloudfront.net",
    "amazonaws.com",
    "googleapis.com",
    "googleusercontent.com",
    "akamaized.net",
    "akamaihd.net",
    "fastly.net",
    "github.io",
    "githubusercontent.com",
    "herokuapp.com",
    "r2.dev",
    "digitaloceanspaces.com",
)


# A bare service endpoint (no account / bucket label) is never a valid entry.
_GENERIC_SERVICE_HOST = re.compile(
    r"^((blob|web|dfs|file|queue|table|z\d+\.web)\.core\.windows\.net"
    r"|s3([.-][a-z0-9-]+)?\.amazonaws\.com|storage\.googleapis\.com)$"
)


def is_shared_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in SHARED_HOST_SUFFIXES)


@dataclass(frozen=True)
class AllowEntry:
    host: str
    path_prefix: str  # "" = any path
    exact: bool  # True on shared cloud hosts: no subdomain matching

    @classmethod
    def parse(cls, entry: str) -> AllowEntry:
        e = entry.strip().lower()
        if "://" in e:
            raise FetchError(f"allowlist entry {entry!r}: give a host, not a URL")
        host, _, path = e.partition("/")
        host = host.rstrip(".")
        if not host or "." not in host:
            raise FetchError(f"allowlist entry {entry!r} is not a hostname")
        if host in SHARED_HOST_SUFFIXES or _GENERIC_SERVICE_HOST.match(host):
            raise FetchError(
                f"allowlist entry {entry!r} is a shared cloud service host: name the exact "
                "bucket / account hostname instead"
            )
        return cls(host, ("/" + path) if path else "", is_shared_host(host))

    def matches(self, host: str, path: str) -> bool:
        host = (host or "").lower().rstrip(".")
        if self.exact:
            ok = host == self.host
        else:
            ok = host == self.host or host.endswith("." + self.host)
        if not ok:
            return False
        if self.path_prefix:
            prefix = self.path_prefix.rstrip("/")
            return path == prefix or path.startswith(prefix + "/")
        return True


def _entries(allowed: list[str]) -> list[AllowEntry]:
    return [AllowEntry.parse(a) for a in allowed]


def host_allowed(host: str, domains: list[str]) -> bool:
    """Host-only check (no path). Shared cloud hosts need an exact entry."""
    host = (host or "").lower().rstrip(".")
    return bool(host) and any(e.matches(host, e.path_prefix or "/") for e in _entries(domains))


def url_allowed(url: str, allowed: list[str]) -> bool:
    """https + host (+ path prefix) on the allowlist."""
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        return False
    return any(e.matches(u.hostname, u.path or "/") for e in _entries(allowed))


def blocked_urls(urls: list[str], allowed: list[str]) -> list[str]:
    """URLs (e.g. read from an insurer table of contents) that are NOT on the allowlist.
    These are reported, never fetched, and never added to the allowlist automatically."""
    return [u for u in urls if not url_allowed(u, allowed)]


def redact(url: str) -> str:
    """Drop the query string (signed-URL tokens) before a URL is logged or stored."""
    return url.split("?", 1)[0]


# ---------------------------------------------------------------- publisher date peek

_JSON_DATE = re.compile(rb'"last_updated_on"\s*:\s*"([^"]{6,40})"')


def peek_publisher_date(path: Path, container: str = "plain", peek: int = 1 << 20) -> str | None:
    """The file's own ``last_updated_on`` (ISO date) from its first bytes, or None.

    JSON (hospital v3 JSON, TiC): the ``"last_updated_on"`` key. CMS v3 CSV: the
    ``last_updated_on`` column of the header block (row 1 = names, row 2 = values)."""
    import csv
    import gzip
    import io
    import zipfile

    try:
        if container == "zip":
            with zipfile.ZipFile(path) as zf:
                names = [
                    n for n in zf.namelist() if not n.startswith("__MACOSX") and not n.endswith("/")
                ]
                with zf.open(names[0]) as f:
                    head = f.read(peek)
        elif container == "gzip":
            with gzip.open(path) as f:
                head = f.read(peek)
        else:
            with open(path, "rb") as f:
                head = f.read(peek)
    except (OSError, zipfile.BadZipFile, IndexError, EOFError):
        return None
    from app.etl.stage import parse_date

    m = _JSON_DATE.search(head)
    raw: str | None = m.group(1).decode("utf-8", "replace") if m else None
    if raw is None:
        text = head.lstrip(b"\xef\xbb\xbf").decode("utf-8", "replace")
        rows = list(csv.reader(io.StringIO("\n".join(text.splitlines()[:2]))))
        if len(rows) == 2 and "last_updated_on" in rows[0]:
            i = rows[0].index("last_updated_on")
            raw = rows[1][i] if i < len(rows[1]) else None
    if not raw:
        return None
    try:
        return parse_date(raw).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------- TLS: extra intermediates

TLS_DIR = CONFIG_DIR / "tls"


def extra_ca_file(host: str, tls_dir: Path | None = None) -> Path | None:
    """``data/etl/tls/<host>.pem``: an intermediate a misconfigured server forgets to send."""
    p = (tls_dir or TLS_DIR) / f"{(host or '').lower()}.pem"
    return p if p.is_file() else None


def ssl_context_for(host: str, tls_dir: Path | None = None) -> ssl.SSLContext | bool:
    """Default verification, plus the host's extra CA file when there is one. Never off."""
    extra = extra_ca_file(host, tls_dir)
    if extra is None:
        return True
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cafile=str(extra))
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    return ctx


def _client_for(host: str, timeout_s: float) -> httpx.Client:
    return httpx.Client(
        timeout=timeout_s, headers={"User-Agent": USER_AGENT}, verify=ssl_context_for(host)
    )


# ---------------------------------------------------------------- the one HTTP entry point


@contextlib.contextmanager
def http_open(
    url: str,
    allowed: list[str],
    *,
    client: httpx.Client | None = None,
    timeout_s: float = 600,
    byte_range: tuple[int, int] | None = None,
) -> Iterator[tuple[httpx.Response, str]]:
    """Every ETL HTTP read goes through here: https only, the allowlist on every redirect hop
    (redirects are followed by hand), optional ``Range: bytes=a-(b-1)``. Yields the final
    response and final URL. Body size caps are enforced by the readers below."""
    headers = {"Range": f"bytes={byte_range[0]}-{byte_range[1] - 1}"} if byte_range else {}
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not url_allowed(url, allowed):
                raise FetchError(f"{redact(url)} is not https on the domain allowlist")
            hop = client or _client_for(urlparse(url).hostname or "", timeout_s)
            try:
                with hop.stream("GET", url, headers=headers, follow_redirects=False) as resp:
                    if resp.is_redirect:
                        url = urljoin(url, resp.headers.get("location", ""))
                        continue
                    yield resp, url
                    return
            finally:
                if client is None:
                    hop.close()
        raise FetchError(f"more than {MAX_REDIRECTS} redirects for {redact(url)}")
    except httpx.HTTPError as e:
        raise FetchError(f"{type(e).__name__}: {e} ({redact(url)})") from e


def capped_chunks(
    resp: httpx.Response, cap: int, what: str, chunk: int = 1 << 20
) -> Iterator[bytes]:
    """Body chunks; fails when Content-Length or the actual stream exceeds ``cap`` bytes."""
    declared = resp.headers.get("content-length")
    if declared and int(declared) > cap:
        raise FetchError(f"{what}: {declared} bytes exceeds the {cap}-byte cap")
    size = 0
    for c in resp.iter_bytes(chunk):
        size += len(c)
        if size > cap:
            raise FetchError(f"{what}: stream exceeds the {cap}-byte cap")
        yield c


def http_get_bytes(
    url: str, allowed: list[str], cap: int, *, client: httpx.Client | None = None
) -> tuple[bytes, str, httpx.Headers]:
    """A small whole document (table of contents, listing). -> (body, final_url, headers)."""
    with http_open(url, allowed, client=client) as (resp, final):
        if resp.status_code != 200:
            raise FetchError(f"HTTP {resp.status_code} for {redact(url)}")
        return b"".join(capped_chunks(resp, cap, redact(url))), final, resp.headers


_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")


def http_range(
    url: str, a: int, b: int, allowed: list[str], *, client: httpx.Client | None = None
) -> bytes:
    """Bytes ``[a, b)`` with HTTP Range. Anything but ``206`` with exactly the requested
    ``Content-Range`` aborts *before* reading the body: a server that ignores Range answers 200
    with the whole file (one UHC Azure host did, 17.9 GB), and that body is never streamed."""
    if b <= a:
        return b""
    with http_open(url, allowed, client=client, byte_range=(a, b)) as (resp, _final):
        if resp.status_code != 206:
            raise FetchError(
                f"range read refused: HTTP {resp.status_code}, expected 206 ({redact(url)})"
            )
        m = _CONTENT_RANGE.match(resp.headers.get("content-range", ""))
        if not m or int(m.group(1)) != a or int(m.group(2)) > b - 1:
            raise FetchError(
                f"range read: Content-Range {resp.headers.get('content-range')!r} does not "
                f"match bytes {a}-{b - 1} ({redact(url)})"
            )
        want = int(m.group(2)) - a + 1
        body = b"".join(capped_chunks(resp, want, redact(url)))
        if len(body) != want:
            raise FetchError(f"range read: got {len(body)} bytes, expected {want}")
        return body


@dataclass
class FetchRecord:
    source_id: str
    method: str  # download | import
    url: str | None
    final_url: str | None
    sha256: str
    bytes: int
    relpath: str  # relative to the store
    fetched_at: str | None  # when WE last downloaded it from the publisher; None for imports
    http_last_modified: str | None
    etag: str | None
    status: str  # new | unchanged
    store: str = ""
    imported_at: str | None = None  # set (instead of fetched_at) for --import-dir copies
    publisher_last_updated_on: str | None = None  # the file's own date (header peek), D18
    note: str | None = None  # browser / manual: how the file was obtained
    landing_url: str | None = None  # browser: the page whose link was clicked
    user_agent: str | None = None  # browser: the browser's own (unchanged) user agent

    @property
    def path(self) -> Path:
        return Path(self.store) / self.relpath


def _ext(spec: SourceSpec, url: str | None) -> str:
    name = (urlparse(url).path if "://" in url else url) if url else (spec.legacy_filename or "")
    low = name.lower()
    for e in (".csv.zip", ".json.gz", ".zip", ".csv", ".json", ".gz", ".xlsx", ".pdf", ".html"):
        if low.endswith(e):
            return ".zip" if e == ".csv.zip" else e
    return ".bin"


def _append(paths: Paths, rec: FetchRecord) -> None:
    paths.store.mkdir(parents=True, exist_ok=True)
    d = asdict(rec)
    d.pop("store")
    if d.get("final_url"):
        d["final_url"] = redact(d["final_url"])
    if d.get("url"):
        d["url"] = redact(d["url"])
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
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    obtained = kw.pop("fetched_at", None) or now  # browser / manual: when the file was obtained
    imported = kw.get("method") == "import"
    rec = FetchRecord(
        source_id=spec.source_id,
        sha256=sha,
        bytes=size,
        relpath=rel,
        fetched_at=None if imported else obtained,
        imported_at=now if imported else None,
        publisher_last_updated_on=peek_publisher_date(dest, spec.container),
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
    try:
        with http_open(
            spec.url, settings.allowed_domains, client=client, timeout_s=settings.timeout_s
        ) as (resp, final_url):
            if resp.status_code != 200:
                raise FetchError(f"HTTP {resp.status_code} for {redact(final_url)}")
            paths.store.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            size = 0
            fd, name = tempfile.mkstemp(
                dir=paths.store, prefix=f".{spec.source_id}.", suffix=".part"
            )
            tmp = Path(name)
            try:
                with os.fdopen(fd, "wb") as out:
                    for chunk in capped_chunks(resp, cap, spec.source_id):
                        size += len(chunk)
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
                final_url=redact(final_url),
                http_last_modified=resp.headers.get("last-modified"),
                etag=resp.headers.get("etag"),
            )
    except FetchError as e:
        raise FetchError(f"{spec.source_id}: {e}") from e


def store_local(
    spec: SourceSpec,
    src: Path,
    paths: Paths,
    *,
    method: str,
    url: str | None,
    final_url: str | None,
    fetched_at: str,
    note: str,
    landing_url: str | None = None,
    user_agent: str | None = None,
) -> FetchRecord:
    """Put a file obtained outside ``fetch_source`` (``browser`` click, ``manual`` download) in
    the content-addressed store. The source file is copied, never moved or modified."""
    if method not in ("browser", "manual"):
        raise FetchError(f"{spec.source_id}: store_local method {method!r}")
    h = hashlib.sha256()
    with src.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    sha = h.hexdigest()
    paths.store.mkdir(parents=True, exist_ok=True)
    tmp = paths.store / f".{spec.source_id}.{sha}.{method}"
    shutil.copy2(src, tmp)
    rec = _finish(
        spec,
        paths,
        tmp,
        sha,
        src.stat().st_size,
        _ext(spec, src.name),
        fetched_at=fetched_at,
        method=method,
        url=url,
        final_url=final_url,
        http_last_modified=None,
        etag=None,
        note=note,
        landing_url=landing_url,
        user_agent=user_agent,
    )
    return rec


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
