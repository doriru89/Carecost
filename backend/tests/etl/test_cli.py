"""End-to-end: the single CLI runs fetch(import) -> stage -> normalize -> build -> report."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import yaml

from app.etl.cli import main
from app.etl.config import CONFIG_DIR

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mrf"


def _config(tmp: Path) -> Path:
    """Real config, but only the two fixture sources, read as plain files."""
    cfg = tmp / "cfg"
    shutil.copytree(CONFIG_DIR, cfg)
    doc = yaml.safe_load((cfg / "sources.yaml").read_text())
    keep = {"brigham_mrf": "brigham_11102.csv", "bidmc_mrf": "bidmc_73030.json"}
    doc["sources"] = [
        dict(s, container="plain", legacy_filename=keep[s["source_id"]])
        for s in doc["sources"]
        if s["source_id"] in keep
    ]
    (cfg / "sources.yaml").write_text(yaml.safe_dump(doc))
    return cfg


def _run(tmp: Path, cfg: Path, *args: str) -> int:
    return main(["--data-dir", str(tmp / "data"), "--config-dir", str(cfg), *args])


def test_cli_end_to_end(tmp_path, capsys):
    cfg = _config(tmp_path)
    assert _run(tmp_path, cfg, "fetch", "--import-dir", str(FIX)) == 0
    assert _run(tmp_path, cfg, "stage") == 0
    assert _run(tmp_path, cfg, "stage") == 0  # idempotent: unchanged sha -> skipped
    assert "already staged" in capsys.readouterr().out
    assert _run(tmp_path, cfg, "normalize") == 0
    assert _run(tmp_path, cfg, "build", "--build-date", "2026-10-24") == 0
    latest = (tmp_path / "data" / "build" / "LATEST").read_text().strip()
    bdir = tmp_path / "data" / "build" / latest
    con = sqlite3.connect(bdir / "rate_row.sqlite")
    n = con.execute("select count(*) from rate_row").fetchone()[0]
    amt = con.execute(
        "select round(sum(amount), 2) from rate_row where entity_id='brigham' and code='11102' "
        "and plan_raw='HB AMC AETNA HMO'"
    ).fetchone()[0]
    assert n > 0 and amt == 532.57
    assert (
        con.execute("select count(*) from rate_row where source_file like '%/%'").fetchone()[0] == 0
    )
    out = tmp_path / "out"
    assert _run(tmp_path, cfg, "report", "--out", str(out)) == 0
    md = (out / "coverage.md").read_text()
    assert "old DB vs new" in md and "| derm | 11102 |" in md
    assert (out / "coverage.csv").read_text().startswith("code,domain,entity_id,payer_id")


def test_build_fails_loudly_and_keeps_latest_when_a_gate_fails(tmp_path):
    cfg = _config(tmp_path)
    gates = yaml.safe_load((cfg / "gates.yaml").read_text())
    gates["anchors"][0]["amount"] = 1.23  # impossible anchor on the anchor's own file
    (cfg / "gates.yaml").write_text(yaml.safe_dump(gates))
    for cmd in (["fetch", "--import-dir", str(FIX)], ["stage"], ["normalize"]):
        assert _run(tmp_path, cfg, *cmd) == 0
    assert _run(tmp_path, cfg, "build", "--build-date", "2026-10-24") == 1
    assert not (tmp_path / "data" / "build" / "LATEST").exists()


def test_fetch_without_url_or_file_is_reported(tmp_path, capsys):
    cfg = _config(tmp_path)
    assert _run(tmp_path, cfg, "stage") == 1  # nothing fetched -> loud
    assert "nothing fetched" in capsys.readouterr().out
