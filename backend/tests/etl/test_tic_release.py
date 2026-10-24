"""Failure isolation, fallback to the last good release, size-drop gate, atomic outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

from app.etl.config import Paths
from app.etl.tic.networks import TicNetwork, get_network, target_codes
from app.etl.tic.normalize import normalize_network
from app.etl.tic.release import assemble
from app.etl.tic.run import (
    FetchInfo,
    TicRunError,
    check_size_drop,
    file_chunks,
    record_fetch,
    run_pass,
    set_current,
    tic_root,
)
from app.etl.tic.targets import load_targets

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tic"
MAN = yaml.safe_load((FIX / "MANIFEST.yaml").read_text())["fixtures"]


def _net(name: str) -> TicNetwork:
    m = MAN[name]
    n = get_network(m["source_id"])
    return TicNetwork(
        **{**n.__dict__, "url": f"https://fixture.invalid/{name}", "container": m["container"]}
    )


def _ok(paths: Paths, name: str, fetched_at: str) -> TicNetwork:
    net = _net(name)
    rr = run_pass(
        net,
        file_chunks(FIX / name),
        FetchInfo(url=net.url, fetched_at=fetched_at),
        paths,
        target_codes(),
    )
    st = normalize_network(Path(rr.out_dir), net, rr.__dict__, load_targets())
    rr.normalize = st.__dict__
    (Path(rr.out_dir) / "run.json").write_text(json.dumps(rr.__dict__, default=str))
    set_current(paths, net.source_id, rr.source_sha256)
    record_fetch(paths, rr, "ok")
    return net


def _fail(paths: Paths, net: TicNetwork, err: str) -> None:
    m = tic_root(paths) / "fetch_manifest.jsonl"
    with m.open("a") as f:
        f.write(json.dumps({"source_id": net.source_id, "status": "failed", "error": err}) + "\n")


def test_failed_network_falls_back_and_others_ship(tmp_path):
    a, b = "mgb_hmo_slice.json.gz", "aetna_ppo_slice.json.gz"
    # month 1: both good
    p1 = Paths(tmp_path / "m1")
    na = _ok(p1, a, "2026-09-24T10:00:00Z")
    nb = _ok(p1, b, "2026-09-24T10:05:00Z")
    r1 = assemble(p1, [na, nb], "2026-09", tmp_path / "rel1", None)
    assert r1["ok"] == 2
    # month 2: b fails, a is good
    p2 = Paths(tmp_path / "m2")
    _ok(p2, a, "2026-10-24T10:00:00Z")
    _fail(p2, nb, "TicRunError: HTTP 503")
    r2 = assemble(p2, [na, nb], "2026-10", tmp_path / "rel2", tmp_path / "rel1")
    man = json.loads((tmp_path / "rel2" / "manifest.json").read_text())["networks"]
    assert (
        man[na.source_id]["status"] == "ok"
        and man[na.source_id]["fetched_at"] == "2026-10-24T10:00:00Z"
    )
    fb = man[nb.source_id]
    assert (
        fb["status"] == "fallback" and fb["fetched_at"] == "2026-09-24T10:05:00Z"
    )  # old date = stale on our side
    assert fb["from_release"] == "tic-2026-09" and "503" in fb["fallback_reason"]
    assert (tmp_path / "rel2" / f"{nb.source_id}__rate_row.parquet").exists()
    total = pq.read_table(tmp_path / "rel2" / "tic_rate_row.parquet").num_rows
    assert total == r2["networks"][na.source_id]["rate_rows"] + fb["rate_rows"]
    assert not list((tmp_path / "rel2").glob(".*tmp*"))  # atomic: no temp files left


def test_missing_without_previous_release(tmp_path):
    p = Paths(tmp_path)
    net = _net("mgb_hmo_slice.json.gz")
    tic_root(p).mkdir(parents=True, exist_ok=True)
    _fail(p, net, "boom")
    r = assemble(p, [net], "2026-10", tmp_path / "rel", None)
    assert r["missing"] == 1 and r["ok"] == 0


def test_size_drop_fails_only_that_network():
    check_size_drop(900, 1000, "x")
    check_size_drop(1000, None, "x")
    with pytest.raises(TicRunError, match="previous"):
        check_size_drop(400, 1000, "x")


def test_size_drop_is_checked_in_the_pass_and_leaves_no_output(tmp_path):
    p = Paths(tmp_path)
    net = _net("mgb_hmo_slice.json.gz")
    size = (FIX / "mgb_hmo_slice.json.gz").stat().st_size
    with pytest.raises(TicRunError):
        run_pass(net, file_chunks(FIX / "mgb_hmo_slice.json.gz"), FetchInfo(url="u", fetched_at="t"), p,
                 target_codes(), prev_bytes=size * 10)  # fmt: skip
    root = tic_root(p) / net.source_id
    assert not (root / "CURRENT").exists()
    assert not root.exists() or not list(root.iterdir())  # no half-written run left behind
