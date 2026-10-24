"""fetch: content-addressed by sha256, domain allowlist, size cap; import of legacy local files."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from app.etl import fetch
from app.etl.config import FetchSettings, Paths, load_sources

SETTINGS = FetchSettings(allowed_domains=["massgeneralbrigham.org"], default_max_bytes=1000)
SPEC = load_sources().get("brigham_mrf")


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "host, ok",
    [
        ("www.massgeneralbrigham.org", True),
        ("massgeneralbrigham.org", True),
        ("evilmassgeneralbrigham.org", False),
        ("massgeneralbrigham.org.evil.com", False),
        ("", False),
    ],
)
def test_host_allowlist_is_suffix_on_label_boundary(host, ok):
    assert fetch.host_allowed(host, ["massgeneralbrigham.org"]) is ok


def test_download_is_content_addressed_and_idempotent(tmp_path):
    body = b"PK fake zip bytes"
    sha = hashlib.sha256(body).hexdigest()
    paths = Paths(tmp_path)
    c = client(
        lambda req: httpx.Response(200, content=body, headers={"Last-Modified": "Thu, 23 Jul 2026"})
    )
    rec = fetch.fetch_source(SPEC, SETTINGS, paths, client=c)
    assert rec.sha256 == sha and rec.status == "new" and rec.bytes == len(body)
    stored = paths.store / "brigham_mrf" / f"{sha}.zip"
    assert stored.read_bytes() == body
    assert rec.http_last_modified == "Thu, 23 Jul 2026"
    again = fetch.fetch_source(SPEC, SETTINGS, paths, client=c)
    assert again.status == "unchanged"
    lines = [json.loads(x) for x in paths.fetch_manifest.read_text().splitlines()]
    assert [x["status"] for x in lines] == ["new", "unchanged"]
    assert fetch.current(paths, "brigham_mrf").path == stored


def test_size_cap_from_content_length_and_from_stream(tmp_path):
    paths = Paths(tmp_path)
    big = b"x" * 1001
    with pytest.raises(fetch.FetchError, match="cap"):
        fetch.fetch_source(
            SPEC, SETTINGS, paths, client=client(lambda r: httpx.Response(200, content=big))
        )

    def no_length(req):
        return httpx.Response(200, content=iter([b"x" * 600, b"x" * 600]))

    with pytest.raises(fetch.FetchError, match="cap"):
        fetch.fetch_source(SPEC, SETTINGS, paths, client=client(no_length))
    assert (
        not list((paths.store / "brigham_mrf").glob("*"))
        if (paths.store / "brigham_mrf").exists()
        else True
    )


def test_redirect_off_allowlist_is_refused(tmp_path):
    def h(req):
        if req.url.host == "www.massgeneralbrigham.org":
            return httpx.Response(302, headers={"Location": "https://cdn.example.com/x.zip"})
        return httpx.Response(200, content=b"x")

    with pytest.raises(fetch.FetchError, match="allowlist"):
        fetch.fetch_source(SPEC, SETTINGS, Paths(tmp_path), client=client(h))


def test_http_error_is_loud(tmp_path):
    with pytest.raises(fetch.FetchError, match="403"):
        fetch.fetch_source(
            SPEC, SETTINGS, Paths(tmp_path), client=client(lambda r: httpx.Response(403))
        )


def test_import_local_registers_legacy_file(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "brigham_standardcharges.zip").write_bytes(b"old bytes")
    paths = Paths(tmp_path / "data")
    rec = fetch.import_local(SPEC, legacy, paths)
    assert rec is not None and rec.method == "import" and rec.status == "new"
    assert rec.path.read_bytes() == b"old bytes"
    assert fetch.current(paths, "brigham_mrf").sha256 == rec.sha256
