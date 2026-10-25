"""fetch.py hardening (security review + A1 requests): allowlist rules for shared cloud hosts,
one HTTP entry point with per-hop checks, TOC hosts are reported not fetched, HTTP Range must be
206, publisher date + import time in the manifest, signatures stripped, per-host extra CA."""

from __future__ import annotations

import gzip
import hashlib
import json
import ssl
import zipfile

import httpx
import pytest

from app.etl import fetch
from app.etl.config import FetchSettings, Paths, load_sources

HP = "eusprdtransparencymrfp32.blob.core.windows.net/hphc"


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- 1. allowlist


@pytest.mark.parametrize(
    "url, ok",
    [
        ("https://eusprdtransparencymrfp32.blob.core.windows.net/hphc/x.zip", True),
        ("https://eusprdtransparencymrfp32.blob.core.windows.net/thp/x.zip", False),  # other path
        ("https://eusprdtransparencymrfp32.blob.core.windows.net/hphcevil/x.zip", False),
        ("https://evil.blob.core.windows.net/hphc/x.zip", False),  # another bucket, same suffix
        ("https://x.eusprdtransparencymrfp32.blob.core.windows.net/hphc/x", False),  # no subdomains
        ("https://transparency-in-coverage.bluecrossma.com/a.json.gz", True),  # owned domain
        ("https://bluecrossma.com.evil.net/a.json.gz", False),  # suffix spoof
        ("https://evilbluecrossma.com/a.json.gz", False),
        ("http://transparency-in-coverage.bluecrossma.com/a.json.gz", False),  # not https
    ],
)
def test_shared_hosts_are_exact_and_owned_domains_are_suffix(url, ok):
    allowed = [HP, "bluecrossma.com"]
    assert fetch.url_allowed(url, allowed) is ok


@pytest.mark.parametrize(
    "entry",
    ["blob.core.windows.net", "core.windows.net", "s3.amazonaws.com", "cloudfront.net",
     "s3-us-west-2.amazonaws.com", "z13.web.core.windows.net", "storage.googleapis.com"],
)  # fmt: skip
def test_bare_shared_cloud_entries_are_rejected(entry):
    with pytest.raises(fetch.FetchError, match="shared cloud"):
        fetch.url_allowed("https://x.blob.core.windows.net/a", [entry])


def test_a1_exact_host_entries_keep_working():
    allowed = ["dfci.widen.net", "cf-store.widencdn.net"]
    assert fetch.url_allowed("https://dfci.widen.net/s/abc/file.json", allowed)
    assert fetch.url_allowed("https://cf-store.widencdn.net/x/y.json?Signature=z", allowed)
    assert not fetch.url_allowed("https://evil-widen.net/x", allowed)


def test_committed_tic_allowlist_has_no_bare_shared_suffix():
    allowed = load_sources().fetch.allowed_domains
    for e in allowed:
        fetch.AllowEntry.parse(e)  # raises on a bare shared suffix
    shared = [e for e in allowed if fetch.is_shared_host(e.split("/")[0])]
    assert shared and all("/" in e for e in shared), "shared hosts need a path prefix"


# ---------------------------------------------------------------- 2. one entry point, per hop


def test_redirect_to_non_allowlisted_host_is_refused_before_request():
    seen = []

    def h(req):
        seen.append(req.url.host)
        if req.url.host == "transparency-in-coverage.uhc.com":
            return httpx.Response(302, headers={"Location": "https://evil.blob.core.windows.net/x"})
        return httpx.Response(200, content=b"never")

    with pytest.raises(fetch.FetchError, match="allowlist"):
        with fetch.http_open(
            "https://transparency-in-coverage.uhc.com/f", ["uhc.com"], client=client(h)
        ):
            pass
    assert seen == ["transparency-in-coverage.uhc.com"]  # the off-list host was never contacted


def test_redirect_within_allowlist_is_followed():
    def h(req):
        if req.url.host == "transparency-in-coverage.uhc.com":
            return httpx.Response(
                302, headers={"Location": "https://mrfstorage.uhc.com/x?sig=SECRET"}
            )
        return httpx.Response(200, content=b"ok")

    body, final, _ = fetch.http_get_bytes("https://transparency-in-coverage.uhc.com/f", ["uhc.com"], 100,
                                          client=client(h))  # fmt: skip
    assert body == b"ok" and fetch.redact(final) == "https://mrfstorage.uhc.com/x"


# ---------------------------------------------------------------- 3. TOC hosts are reported only


def test_toc_url_on_new_host_is_reported_not_fetched():
    from app.etl.tic.discover import discover
    from app.etl.tic.networks import get_network

    net = get_network("tic_mgb_hp_commercial_hmo")
    toc = {"reporting_structure": [{"in_network_files": [
        {"location": "https://new-cdn.example.net/INN_COMMERCIAL_HMO_2026-10-27.json.gz"}]}]}  # fmt: skip
    hits = []

    def h(req):
        hits.append(req.url.host)
        return httpx.Response(200, content=json.dumps(toc).encode())

    (d,) = discover([net], client=client(h))
    assert d.status == "blocked_host" and d.url is None
    assert d.to_json()["blocked"] == [
        "https://new-cdn.example.net/INN_COMMERCIAL_HMO_2026-10-27.json.gz"
    ]
    assert "new-cdn.example.net" not in hits
    assert not any("example.net" in a for a in load_sources().fetch.allowed_domains)


# ---------------------------------------------------------------- HTTP Range must be 206


def test_range_read_aborts_on_200_without_reading_the_body():
    read = {"n": 0}

    def body():
        for _ in range(1000):
            read["n"] += 1
            yield b"x" * 1_000_000

    def h(req):
        assert req.headers["range"] == "bytes=10-19"
        return httpx.Response(200, content=body())  # server ignored Range

    with pytest.raises(fetch.FetchError, match="expected 206"):
        fetch.http_range("https://mrfstorage.uhc.com/f", 10, 20, ["uhc.com"], client=client(h))
    assert read["n"] <= 1  # never streamed the 200 body


@pytest.mark.parametrize("cr", ["bytes 0-9/100", "bytes 10-40/100", "", "bytes */100"])
def test_range_read_requires_the_requested_content_range(cr):
    h = lambda req: httpx.Response(206, content=b"0123456789", headers={"content-range": cr})  # noqa: E731
    with pytest.raises(fetch.FetchError, match="Content-Range"):
        fetch.http_range("https://mrfstorage.uhc.com/f", 10, 20, ["uhc.com"], client=client(h))


def test_range_read_ok():
    def h(req):
        return httpx.Response(
            206, content=b"abcdefghij", headers={"content-range": "bytes 10-19/100"}
        )

    assert (
        fetch.http_range("https://mrfstorage.uhc.com/f", 10, 20, ["uhc.com"], client=client(h))
        == b"abcdefghij"
    )


# ---------------------------------------------------------------- 4. decompressed cap


def test_decompressed_bytes_are_capped():
    from app.etl.tic.zran import DecompressCapExceeded, InflatePass

    bomb = gzip.compress(b"\0" * 5_000_000)  # 5 MB from ~5 KB
    with pytest.raises(DecompressCapExceeded):
        for _ in InflatePass([bomb], "gzip", max_raw=1_000_000, coalesce=1 << 16):
            pass


def test_network_raw_cap_is_ratio_of_byte_cap():
    from app.etl.tic.networks import MAX_RATIO, load_networks

    for n in load_networks():
        assert n.max_raw == n.max_bytes * MAX_RATIO


# ---------------------------------------------------------------- A1: manifest fields


SPEC = load_sources().get("brigham_mrf")
SETTINGS = FetchSettings(allowed_domains=["massgeneralbrigham.org"], default_max_bytes=10_000)


def _zip_csv(text: str) -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", text)
    return buf.getvalue()


def test_fetch_records_publisher_date_and_strips_signatures(tmp_path):
    body = _zip_csv("hospital_name,last_updated_on,version\nBrigham,3/20/2026,3.0.0\nhdr\n")

    def h(req):
        if "sig" not in str(req.url):
            return httpx.Response(
                302, headers={"Location": "https://cdn.massgeneralbrigham.org/f.zip?sig=TOKEN"}
            )
        return httpx.Response(200, content=body)

    rec = fetch.fetch_source(SPEC, SETTINGS, Paths(tmp_path), client=client(h))
    assert rec.publisher_last_updated_on == "2026-03-20"
    assert rec.fetched_at and rec.imported_at is None
    line = json.loads(Paths(tmp_path).fetch_manifest.read_text().splitlines()[-1])
    assert line["final_url"] == "https://cdn.massgeneralbrigham.org/f.zip"
    assert "TOKEN" not in Paths(tmp_path).fetch_manifest.read_text()


def test_import_sets_imported_at_not_fetched_at(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "brigham_standardcharges.zip").write_bytes(
        _zip_csv("a,last_updated_on\nx,2026-03-27\n")
    )
    rec = fetch.import_local(SPEC, legacy, Paths(tmp_path / "data"))
    assert rec is not None and rec.fetched_at is None and rec.imported_at
    assert rec.publisher_last_updated_on == "2026-03-27"
    line = json.loads(Paths(tmp_path / "data").fetch_manifest.read_text())
    assert line["fetched_at"] is None and line["imported_at"]


def test_publisher_date_from_json_and_gzip(tmp_path):
    p = tmp_path / "x.json.gz"
    p.write_bytes(
        gzip.compress(
            b'{"reporting_entity_name":"X","last_updated_on":"2026-10-01","version":"2.0.0"}'
        )
    )
    assert fetch.peek_publisher_date(p, "gzip") == "2026-10-01"
    q = tmp_path / "y.json"
    q.write_bytes(b"not a price file")
    assert fetch.peek_publisher_date(q) is None


def test_old_manifest_lines_still_load(tmp_path):
    paths = Paths(tmp_path)
    paths.store.mkdir(parents=True)
    old = {"source_id": "a", "method": "download", "url": None, "final_url": None, "sha256": "0" * 64,
           "bytes": 1, "relpath": "a/x", "fetched_at": "2026-10-01T00:00:00+00:00",
           "http_last_modified": None, "etag": None, "status": "new"}  # fmt: skip
    paths.fetch_manifest.write_text(json.dumps(old) + "\n")
    (r,) = fetch.read_manifest(paths)
    assert r.imported_at is None and r.publisher_last_updated_on is None


# ---------------------------------------------------------------- A1: extra intermediate CA


def test_extra_ca_keeps_verification_on(tmp_path):
    from app.etl.config import CONFIG_DIR

    assert (CONFIG_DIR / "tls" / "franciscans.childrenshospital.org.pem").exists()
    ctx = fetch.ssl_context_for("franciscans.childrenshospital.org")
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert fetch.ssl_context_for("www.massgeneralbrigham.org") is True  # default verification
    pem = (CONFIG_DIR / "tls" / "franciscans.childrenshospital.org.pem").read_text()
    der = ssl.PEM_cert_to_DER_cert(pem[pem.index("-----BEGIN") :])
    assert hashlib.sha256(der).hexdigest().upper().startswith("6542D176")
