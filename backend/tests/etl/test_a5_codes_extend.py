"""A5: codes from care paths (R9), ``tic extend`` (range read of added codes), NPI placeholders
(R10), CMS physician time."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

from app.etl import path_codes
from app.etl.config import CONFIG_DIR, Paths, load_codes
from app.etl.gov import physician_time
from app.etl.npi import clean_npis, count, is_valid_npi
from app.etl.tic.extend import clean_groups, extend_network
from app.etl.tic.networks import TicNetwork, get_network, load_visit_map, target_codes
from app.etl.tic.normalize import normalize_network
from app.etl.tic.run import FetchInfo, file_chunks, run_pass
from app.etl.tic.stage import Stager
from app.etl.tic.targets import load_targets

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tic"
MAN = yaml.safe_load((FIX / "MANIFEST.yaml").read_text())["fixtures"]
PATHS_DIR = CONFIG_DIR.parent / "care_paths" / "paths"


# ---------------------------------------------------------------- R9: codes from care paths


def test_committed_path_codes_are_in_sync_with_the_care_paths():
    """CI gate: a care-path code missing from extraction fails here (re-run `codes sync`)."""
    assert path_codes.check() == []


def test_every_care_path_code_is_extracted():
    from app.care_paths.loader import load_paths

    want = {c for p in load_paths().values() for st in p.steps for c in st.all_codes()}
    codes = load_codes().codes
    assert want <= codes
    assert want <= target_codes()
    # the ones the wave-2 review found missing
    assert {
        "43235",
        "00731",
        "73610",
        "73562",
        "73721",
        "72100",
        "72148",
        "11602",
        "G0121",
    } <= codes


def _cfg(tmp: Path, paths_from: Path = PATHS_DIR) -> tuple[Path, Path]:
    cfg = tmp / "etl"
    shutil.copytree(CONFIG_DIR, cfg)
    pdir = tmp / "paths"
    shutil.copytree(paths_from, pdir)
    return cfg, pdir


def test_a_new_path_code_fails_the_check_until_sync(tmp_path):
    cfg, pdir = _cfg(tmp_path)
    f = pdir / "knee_chronic_v1.yaml"
    f.write_text(f.read_text().replace("code: '73560'", "code: '73565'", 1))
    probs = path_codes.check(pdir, cfg)
    assert any(p.startswith("73565 ") and "missing from extraction" in p for p in probs)
    path_codes.sync(pdir, cfg)
    assert path_codes.check(pdir, cfg) == []
    load_codes.cache_clear()
    assert "73565" in load_codes(cfg).codes
    assert load_codes(cfg).domains_for("73565") == ["ortho"]
    assert load_codes(cfg).description("73565") == ""  # descriptions stay hand-written only


def test_unmapped_area_fails_loudly(tmp_path):
    cfg, pdir = _cfg(tmp_path)
    f = cfg / "codes.yaml"
    f.write_text(f.read_text().replace("  gi_upper: gi\n", "", 1))
    with pytest.raises(path_codes.PathCodesError, match="gi_upper"):
        path_codes.check(pdir, cfg)


def test_generated_file_quotes_every_code():
    text = (CONFIG_DIR / "path_codes.yaml").read_text()
    assert '"00811":' in text and "\n  00811:" not in text


def test_check_data_flags_runs_cut_before_r9(tmp_path):
    d = tmp_path / "intermediate" / "tic" / "tic_x"
    (d / "abc").mkdir(parents=True)
    (d / "CURRENT").write_text("abc\n")
    (d / "abc" / "run.json").write_text(json.dumps({"source_sha256": "abc"}))
    probs = path_codes.check_data(Paths(tmp_path), {"73610"})
    assert probs and "cut before R9" in probs[0]
    (d / "abc" / "run.json").write_text(json.dumps({"target_codes": ["73030"]}))
    assert "73610" in path_codes.check_data(Paths(tmp_path), {"73610", "73030"})[0]


# ---------------------------------------------------------------- tic extend


def _net(name: str) -> TicNetwork:
    m = MAN[name]
    n = get_network(m["source_id"])
    return TicNetwork(
        **{**n.__dict__, "url": f"https://fixture.invalid/{name}", "container": m["container"]}
    )


def _rows(p: Path) -> list[dict]:
    return pq.read_table(p).to_pylist()


@pytest.mark.parametrize("name", ["bcbs_hmo_blue_slice.json.gz", "hphc_a008_slice.zip"])
def test_extend_reads_only_the_added_code_and_equals_a_full_run(tmp_path, name):
    net, fx = _net(name), FIX / name
    full = run_pass(net, file_chunks(fx), FetchInfo(url=net.url, fetched_at="2026-10-24T23:11:27Z"),
                    Paths(tmp_path / "full"), target_codes())  # fmt: skip
    staged_codes = {r["billing_code"] for r in _rows(Path(full.out_dir) / "items.parquet")}
    added = sorted(staged_codes - set(load_visit_map().all_codes))[:1] or sorted(staged_codes)[:1]
    old_codes = target_codes() - set(added)
    part = run_pass(net, file_chunks(fx), FetchInfo(url=net.url, fetched_at="2026-10-24T23:11:27Z"),
                    Paths(tmp_path / "part"), old_codes)  # fmt: skip
    d = Path(part.out_dir)
    before = {r["stage_row"]: r for r in _rows(d / "prices.parquet")}
    e = extend_network(net, d, target_codes(), legacy=set(), allowed=[], local_copy=fx)
    assert e["codes_in_file"] == added and e["how"] == "local_copy" and e["items"] >= 1
    after = _rows(d / "prices.parquet")
    # every row already cited keeps its stage_row
    assert {r["stage_row"]: r for r in after if r["stage_row"] in before} == before
    assert min(r["stage_row"] for r in after if r["stage_row"] not in before) == max(before) + 1
    # same rows as the full pass, modulo numbering
    key = lambda r: json.dumps({k: v for k, v in r.items() if k != "stage_row"}, sort_keys=True)  # noqa: E731
    assert sorted(map(key, after)) == sorted(map(key, _rows(Path(full.out_dir) / "prices.parquet")))
    run = json.loads((d / "run.json").read_text())
    assert (
        run["target_codes"] == sorted(target_codes())
        and run["extends"][-1]["codes_in_file"] == added
    )
    a = normalize_network(d, net, run, load_targets())
    b = normalize_network(Path(full.out_dir), net, full.__dict__, load_targets())
    assert a.rate_rows == b.rate_rows and a.codes == b.codes
    # a second extend is a no-op
    e2 = extend_network(net, d, target_codes(), legacy=set(), allowed=[], local_copy=fx)
    assert e2["items"] == 0 and e2["codes_in_file"] == []


def test_extend_refuses_a_changed_file(tmp_path):
    net, fx = _net("bcbs_hmo_blue_slice.json.gz"), FIX / "bcbs_hmo_blue_slice.json.gz"
    part = run_pass(net, file_chunks(fx), FetchInfo(url=net.url, fetched_at="x"),
                    Paths(tmp_path), {"99203"})  # fmt: skip
    other = tmp_path / "other.json.gz"
    other.write_bytes((FIX / "uhc_choice_hmo_slice.json.gz").read_bytes())
    with pytest.raises(Exception):  # noqa: B017 - re-read of a staged item fails on another file
        extend_network(net, Path(part.out_dir), {"99203", "73030"}, legacy=set(), allowed=[],
                       local_copy=other)  # fmt: skip
    assert json.loads((Path(part.out_dir) / "run.json").read_text())["target_codes"] == ["99203"]


# ---------------------------------------------------------------- R10: NPI placeholders


def test_npi_check_digit():
    assert is_valid_npi("1234567893")  # CMS's published example
    assert not is_valid_npi("1234567890")
    assert not is_valid_npi("0") and not is_valid_npi("") and not is_valid_npi("12345678")
    kept, bad = clean_npis(["1234567893", "0", "0", "9999999999"])
    assert kept == ["1234567893"] and bad == ["0", "0", "9999999999"]
    assert count(bad) == {"0": 2, "bad_check_digit": 1}


def test_stager_drops_placeholder_npis_and_counts_them(tmp_path):
    from app.etl.tic.scan import ScanResult

    st = Stager(tmp_path, "tic_x", "f" * 64)
    res = ScanResult(
        provider_references=[{"provider_group_id": 1, "provider_groups": [
            {"npi": [0, 1234567893], "tin": {"type": "ein", "value": "272343207"}}]}],
        independent_groups=1,
    )  # fmt: skip
    stats = st.finish(res)
    g = _rows(tmp_path / "groups.parquet")[0]
    assert g["npis"] == ["1234567893"] and g["n_npi"] == 1
    assert json.loads(g["extra"])["dropped_npis"] == ["0"]
    assert stats.npi_placeholders_dropped == {"0": 1}


def test_clean_groups_rewrites_already_staged_rows(tmp_path):
    import pyarrow as pa

    from app.etl.tic.stage import GROUP_SCHEMA

    row = dict(source_id="s", source_sha256="h", provider_group_id=1, group_ordinal=0,
               network_name=[], tin_type="ein", tin_value="1", tin_digits="1", business_name="",
               npis=["0", "1234567893"], n_npi=2, location="", inline=False, extra="")  # fmt: skip
    t, dropped = clean_groups(pa.Table.from_pylist([row], GROUP_SCHEMA))
    r = t.to_pylist()[0]
    assert r["npis"] == ["1234567893"] and r["n_npi"] == 1 and dropped == {"0": 1}


# ---------------------------------------------------------------- CMS physician time


def _ptime_zip(rows: list[str]) -> bytes:
    head = ("cpt_code,Pre_Evaluation_Time,Pre_Positioning_time,Pre_Service_Scrub_Dress_Wait_tim,"
            "Median_Intra_Service_Time,Immediate_post_Service_time,Total_time")  # fmt: skip
    filler = [f"{90000 + i},0,0,0,1,0,1" for i in range(5000)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CY 2026 Efficiency Adjusted Work Times.csv", "\n".join([head, *rows, *filler]))
    return buf.getvalue()


def test_physician_time_reads_anesthesia_and_procedure_times():
    data = _ptime_zip(["00812,0,0,0,0,0,52.31", "45378,14,3,5,25,15,62"])
    doc = physician_time.build(data, {"00812", "45378", "J3301"}, "2026-10-25T00:00:00+00:00", None)
    assert doc["times"]["00812"] == {"kind": "anesthesia", "typical_anesthesia_min": 52.31}
    assert doc["times"]["45378"]["intra_service_min"] == 25.0
    assert doc["not_in_file"] == ["J3301"] and len(doc["source"]["sha256"]) == 64


def test_committed_physician_time_covers_the_anesthesia_steps():
    doc = yaml.safe_load((CONFIG_DIR / "physician_time.yaml").read_text())
    assert doc["source"]["publisher"] == "CMS" and doc["source"]["sha256"]
    for c in ("00731", "00811", "00812"):
        assert doc["times"][c]["typical_anesthesia_min"] > 0
