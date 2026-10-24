"""Failure recovery: the failure-recovery reviewer's break-it scenarios (review-v3.1), as tests.

A  good baseline build                    D  only the build date moves past 365 days
B1 shrunk file, LATEST exists             E  re-run killed mid-sqlite on the live build id
B2 shrunk file, fresh data dir (CI)       G  empty LATEST
C  file cut inside its header             +  pins.yaml, size-drop and last-row truncation signals
C2 file cut mid-row
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.etl import build as build_mod
from app.etl import stage as stage_mod
from app.etl.cli import main
from app.etl.config import CONFIG_DIR, Paths, load_sources

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mrf"
BROKEN = Path(__file__).resolve().parents[1] / "fixtures" / "mrf_broken"
KEEP = {"brigham_mrf": "brigham_11102.csv", "bidmc_mrf": "bidmc_73030.json"}


def _config(tmp: Path, pins: list[dict] | None = None) -> Path:
    cfg = tmp / "cfg"
    shutil.copytree(CONFIG_DIR, cfg)
    doc = yaml.safe_load((cfg / "sources.yaml").read_text())
    doc["sources"] = [
        dict(s, container="plain", legacy_filename=KEEP[s["source_id"]])
        for s in doc["sources"]
        if s["source_id"] in KEEP
    ]
    (cfg / "sources.yaml").write_text(yaml.safe_dump(doc))
    (cfg / "pins.yaml").write_text(yaml.safe_dump({"version": 1, "pins": pins or []}))
    return cfg


def _imp(tmp: Path, name: str, brigham: bytes | None = None) -> Path:
    d = tmp / name
    d.mkdir()
    shutil.copy(FIX / KEEP["bidmc_mrf"], d / KEEP["bidmc_mrf"])
    (d / KEEP["brigham_mrf"]).write_bytes(
        brigham if brigham is not None else (FIX / KEEP["brigham_mrf"]).read_bytes()
    )
    return d


def _shrunk() -> bytes:
    lines = (FIX / KEEP["brigham_mrf"]).read_bytes().split(b"\n")
    keep = lines[:3] + [x for x in lines[3:] if b"HB AMC AETNA HMO" in x]
    return b"\n".join(keep) + b"\n"


def _run(data: Path, cfg: Path, *args: str) -> int:
    return main(["--data-dir", str(data), "--config-dir", str(cfg), *args])


def _pipeline(data: Path, cfg: Path, imp: Path, day: str, *build_args: str) -> int:
    _run(data, cfg, "fetch", "--import-dir", str(imp))
    _run(data, cfg, "stage")
    _run(data, cfg, "normalize")
    return _run(data, cfg, "build", "--build-date", day, *build_args)


def _latest(data: Path) -> str | None:
    p = data / "build" / "LATEST"
    return p.read_text().strip() if p.exists() else None


def _manifest(data: Path, bid: str) -> dict:
    return json.loads((data / "build" / bid / "manifest.json").read_text())


@pytest.fixture
def baseline(tmp_path):
    """Scenario A: a good first build."""
    cfg = _config(tmp_path)
    data = tmp_path / "X"
    assert _pipeline(data, cfg, _imp(tmp_path, "good"), "2026-10-24", "--first-build") == 0
    return cfg, data, _latest(data)


# ---------------------------------------------------------------- 1. staleness is a label (D13)


def test_d_build_date_past_365_days_still_ships(baseline):
    cfg, data, base = baseline
    assert _run(data, cfg, "build", "--build-date", "2027-04-01") == 0
    bid = _latest(data)
    assert bid != base
    st = {g["subject"]: g for g in _manifest(data, bid)["gates"] if g["gate"] == "staleness"}
    assert st["brigham_mrf"]["status"] == "warn"  # 370 days: labelled, not failed
    assert all(g["status"] != "fail" for g in _manifest(data, bid)["gates"])


# ---------------------------------------------------------------- 2. per-source last-good fallback


def test_b1_shrunk_file_falls_back_to_last_good_and_ships_the_rest(baseline, tmp_path):
    cfg, data, base = baseline
    good = _manifest(data, base)["sources"]["brigham_mrf"]
    _run(data, cfg, "fetch", "--import-dir", str(_imp(tmp_path, "shrunk", _shrunk())))
    assert (
        _run(data, cfg, "stage", "--allow-shrink") == 0
    )  # get past the size check to the row gate
    assert _run(data, cfg, "normalize") == 0
    assert _run(data, cfg, "build", "--build-date", "2026-11-24") == 0
    m = _manifest(data, _latest(data))
    b = m["sources"]["brigham_mrf"]
    assert b["sha256"] == good["sha256"] and b["rate_rows"] == good["rate_rows"]
    assert b["fetched_at"] == good["fetched_at"]  # the old copy keeps its own fetched_at
    assert (
        b["fallback"]["used"] == "last_good"
        and "rate_rows fell" in b["fallback"]["rejected_because"]
    )
    assert "bidmc_mrf" in m["sources"]
    fb = [g for g in m["gates"] if g["gate"] == "fallback"]
    assert fb and fb[0]["status"] == "warn"


def test_pin_is_used_when_the_current_copy_fails(baseline, tmp_path):
    cfg, data, base = baseline
    good_sha = _manifest(data, base)["sources"]["brigham_mrf"]["sha256"]
    pin = {
        "source_id": "brigham_mrf",
        "sha256": good_sha,
        "reason": "test",
        "set_by": "t",
        "date": "2026-11-01",
    }
    cfg2 = _config(tmp_path / "c2", pins=[pin])
    # a fresh data dir that only shares the raw store (CI): no LATEST, no built files for good_sha
    ci = tmp_path / "ci"
    shutil.copytree(data / "raw", ci / "raw")
    _run(ci, cfg2, "fetch", "--import-dir", str(_imp(tmp_path, "shrunk", _shrunk())))
    _run(ci, cfg2, "stage")
    _run(ci, cfg2, "normalize")
    rc = _run(ci, cfg2, "build", "--build-date", "2026-11-24", "--baseline-manifest",
              str(data / "build" / base / "manifest.json"))  # fmt: skip
    assert rc == 0
    b = _manifest(ci, _latest(ci))["sources"]["brigham_mrf"]
    assert b["sha256"] == good_sha and b["fallback"]["used"] == "pin"  # materialized on demand


def test_no_good_copy_fails_the_build(tmp_path, baseline):
    """B2 with a CI baseline: the 97% shrink is caught, and nothing good is left to ship."""
    cfg, data, base = baseline
    fresh = tmp_path / "Y2"  # CI-like: nothing in the store but the shrunk file
    rc = _pipeline(fresh, cfg, _imp(tmp_path, "shrunk", _shrunk()), "2026-11-24",
                   "--baseline-manifest", str(data / "build" / base / "manifest.json"))  # fmt: skip
    assert rc == 1 and _latest(fresh) is None
    m = _manifest(fresh, sorted(p.name for p in (fresh / "build").iterdir())[0])
    fails = {(g["gate"], g["subject"]) for g in m["gates"] if g["status"] == "fail"}
    assert ("row_count", "brigham_mrf") in fails and ("fallback", "brigham_mrf") in fails


# ---------------------------------------------------------------- 3. atomic builds


def test_e_killed_rebuild_never_touches_the_live_build(baseline, monkeypatch):
    cfg, data, base = baseline
    live = data / "build" / base
    before = {p.name: p.stat().st_size for p in live.iterdir()}

    def boom(parquet, db):
        db.unlink(missing_ok=True)
        raise KeyboardInterrupt("simulated kill during sqlite step")

    monkeypatch.setattr(build_mod, "_sqlite", boom)
    gates_cfg = yaml.safe_load((cfg / "gates.yaml").read_text())
    with pytest.raises(KeyboardInterrupt):
        build_mod.run_build(
            Paths.resolve(data), load_sources(cfg), gates_cfg, date(2026, 10, 24), config_dir=cfg
        )
    assert {p.name: p.stat().st_size for p in live.iterdir()} == before
    assert _latest(data) == base
    assert not [p for p in (data / "build").iterdir() if p.name.startswith(".tmp-")]
    monkeypatch.undo()
    res = build_mod.run_build(
        Paths.resolve(data), load_sources(cfg), gates_cfg, date(2026, 10, 24), config_dir=cfg
    )
    assert res.ok and res.build_id == f"{base}-2"  # same inputs, same day: a new id, not in place


def test_g_empty_or_unknown_latest_is_rejected(baseline, capsys):
    cfg, data, base = baseline
    for bad in ("", "\n", "../etc", "20261024-deadbeef"):
        (data / "build" / "LATEST").write_text(bad)
        assert build_mod.latest_build(Paths.resolve(data)) is None
        assert _run(data, cfg, "report") == 1
    assert "no build to report on" in capsys.readouterr().out


# ---------------------------------------------------------------- 4. row-count baseline


def test_b2_fresh_dir_without_baseline_fails_unless_first_build(tmp_path):
    cfg = _config(tmp_path)
    fresh = tmp_path / "Y"
    assert _pipeline(fresh, cfg, _imp(tmp_path, "shrunk", _shrunk()), "2026-11-24") == 1
    assert _latest(fresh) is None
    assert _run(fresh, cfg, "build", "--build-date", "2026-11-24", "--first-build") == 0


# ---------------------------------------------------------------- 5. stage survives a malformed file


def test_c_header_cut_is_a_stage_error_not_a_crash(baseline, tmp_path, capsys):
    cfg, data, base = baseline
    imp = _imp(tmp_path, "cut", (BROKEN / "brigham_11102_cut_in_header.csv").read_bytes())
    _run(data, cfg, "fetch", "--import-dir", str(imp))
    assert _run(data, cfg, "stage", "--allow-shrink", "--force") == 1  # returns, does not raise
    out = capsys.readouterr().out
    assert "FAIL   brigham_mrf: StageError" in out and "STAGED bidmc_mrf" in out
    spec = load_sources(cfg).get("brigham_mrf")
    with pytest.raises(stage_mod.StageError, match="truncated"):
        stage_mod.stage_file(
            spec, BROKEN / "brigham_11102_cut_in_header.csv", "0" * 64, tmp_path / "s.parquet"
        )
    assert not (tmp_path / "s.parquet.partial").exists()
    # and the build still ships brigham from its last good copy
    _run(data, cfg, "normalize")
    assert _run(data, cfg, "build", "--build-date", "2026-12-24") == 0
    b = _manifest(data, _latest(data))["sources"]["brigham_mrf"]
    assert b["fallback"]["used"] == "last_good"


# ---------------------------------------------------------------- 6. truncation signals


def test_c2_mid_row_cut_fails_the_last_row_check(tmp_path):
    spec = load_sources(_config(tmp_path)).get("brigham_mrf")
    with pytest.raises(stage_mod.StageError, match="last data row has 2 of 28 columns"):
        stage_mod.stage_file(
            spec, BROKEN / "brigham_11102_cut_mid_row.csv", "0" * 64, tmp_path / "s.parquet"
        )
    assert not (tmp_path / "s.parquet").exists()


def test_size_drop_fails_stage_unless_allowed(baseline, tmp_path, capsys):
    cfg, data, base = baseline
    _run(data, cfg, "fetch", "--import-dir", str(_imp(tmp_path, "shrunk", _shrunk())))
    assert _run(data, cfg, "stage") == 1
    out = capsys.readouterr().out
    assert "brigham_mrf: file is" in out and "smaller than the previous copy" in out
    assert _run(data, cfg, "stage", "--allow-shrink") == 0


def test_size_drop_error_thresholds():
    assert stage_mod.size_drop_error("s", 100, None, 50) is None
    assert stage_mod.size_drop_error("s", 60, 100, 50) is None
    assert stage_mod.size_drop_error("s", 120, 100, 50) is None
    assert "40%" not in (stage_mod.size_drop_error("s", 40, 100, 50) or "")
    assert "60% smaller" in (stage_mod.size_drop_error("s", 40, 100, 50) or "")
