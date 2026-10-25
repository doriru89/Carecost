"""TiC pipeline on real slices (tests/fixtures/tic, cut by scripts/etl/cut_tic_fixtures.py).

Covers: row conservation (prices, provider groups, normalized rows), provider_references
resolution, percentage vs dollar negotiated_type, modifiers, the per-payer visit-code map, TIN /
NPI matching (UHC "MVNE 1" = AFC), and index + range reads == the full stream.
"""

from __future__ import annotations

import gzip
import io
import json
import random
import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml
from pydantic import ValidationError

from app.etl.config import Paths
from app.etl.contracts import RateRow
from app.etl.tic.index import load_index
from app.etl.tic.networks import TicNetwork, get_network, load_visit_map, target_codes
from app.etl.tic.normalize import CORE, normalize_network
from app.etl.tic.ranged import verify_against_stream
from app.etl.tic.run import FetchInfo, file_chunks, run_pass
from app.etl.tic.scan import ScanError, TargetItem, scan
from app.etl.tic.stage import TicStageError
from app.etl.tic.targets import Targets, load_targets
from app.etl.tic.zran import InflatePass, file_fetcher, read_raw_range

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tic"
MAN = yaml.safe_load((FIX / "MANIFEST.yaml").read_text())["fixtures"]
AFC = "272343207"


def _net(name: str) -> TicNetwork:
    m = MAN[name]
    n = get_network(m["source_id"])
    return TicNetwork(
        **{**n.__dict__, "url": f"https://fixture.invalid/{name}", "container": m["container"]}
    )


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict[str, tuple[TicNetwork, dict, Path]]:
    paths = Paths(tmp_path_factory.mktemp("tic"))
    out = {}
    for name in MAN:
        net = _net(name)
        rr = run_pass(net, file_chunks(FIX / name), FetchInfo(url=net.url, fetched_at="2026-10-24T23:11:27Z"),
                      paths, target_codes())  # fmt: skip
        run = rr.__dict__
        normalize_network(Path(rr.out_dir), net, run, load_targets())
        out[name] = (net, run, Path(rr.out_dir))
    return out


def _rr(runs, name):
    return pq.read_table(runs[name][2] / "rate_row.parquet").to_pylist()


def test_manifest_sha_matches_fixture_files():
    import hashlib

    for name, m in MAN.items():
        assert hashlib.sha256((FIX / name).read_bytes()).hexdigest() == m["fixture_sha256"]


# ---------------------------------------------------------------- conservation


@pytest.mark.parametrize("name", sorted(MAN))
def test_row_conservation(runs, name):
    _net_, run, d = runs[name]
    st = run["stage"]
    assert st["prices_parsed"] == st["independent_prices"] > 0
    assert st["groups_with_tin"] == st["independent_groups"] > 0
    prices = pq.read_table(d / "prices.parquet").num_rows
    assert prices == st["price_rows"] == st["prices_parsed"] + st["empty_rate_groups"]
    nm = json.loads((d / "rate_row.stats.json").read_text())
    assert nm["rate_rows"] + sum(nm["placeholders_dropped"].values()) == nm["expected_rows"]
    # the first in_network item is not a target code: it is in the item map but not staged
    idx = load_index(d)
    assert idx.items[0].billing_code not in target_codes()
    assert len(idx.items) == MAN[name]["in_network_items"]


def test_stage_fails_loudly_when_counts_disagree(tmp_path):
    from app.etl.tic.scan import ScanResult
    from app.etl.tic.stage import Stager

    doc = json.loads(gzip.decompress((FIX / "mgb_hmo_slice.json.gz").read_bytes()))
    st = Stager(tmp_path, "x", "0" * 64)
    with pytest.raises(TicStageError, match="independent"):
        st.finish(
            ScanResult(provider_references=doc["provider_references"], independent_groups=10**6)
        )
    assert not list(tmp_path.glob("*.parquet"))  # nothing half-written


# ---------------------------------------------------------------- provider_references


def test_provider_references_resolve_to_tins(runs):
    for name in MAN:
        nm = json.loads((runs[name][2] / "rate_row.stats.json").read_text())
        assert nm["unresolved_ref_ids"] == 0
    rows = _rr(runs, "bcbs_hmo_blue_slice.json.gz")
    afc = [
        r
        for r in rows
        if r["entity_id"] == f"tin:{AFC}" and r["code"] == "99203" and not r["modifiers"]
    ]
    assert afc and {r["amount"] for r in afc} == {135.61}
    assert all(r["tic_tin_type"] == "ein" and r["tic_tin_value"] == "27-2343207" for r in afc)
    for r in rows:
        RateRow(**r)  # D30: the tic_* columns are contract fields
    with pytest.raises(ValidationError, match="insurer_tic row needs"):
        RateRow(**{k: r[k] for k in CORE})  # a TiC row without its TiC fields is rejected


def test_inline_provider_groups_and_pretty_json(tmp_path):
    doc = {"reporting_entity_name": "T", "last_updated_on": "2026-10-01", "version": "2.0.0",
           "provider_references": [{"provider_group_id": 1, "provider_groups": [
               {"npi": [1234567893], "tin": {"type": "ein", "value": "27-2343207"}}]}],
           "in_network": [
               {"negotiation_arrangement": "ffs", "name": "x", "billing_code_type": "CPT",
                "billing_code": "99999", "description": "skip me",
                "negotiated_rates": [{"provider_references": [1], "negotiated_prices": [
                    {"negotiated_type": "negotiated", "negotiated_rate": 1.5, "expiration_date": "9999-12-31",
                     "billing_class": "professional", "service_code": ["11"]}]}]},
               {"negotiation_arrangement": "ffs", "name": "v", "billing_code_type": "CPT",
                "billing_code": "99213", "description": "visit",
                "negotiated_rates": [
                    {"provider_groups": [{"npi": [1987654321], "tin": {"type": "npi", "value": "1987654321"}}],
                     "negotiated_prices": [{"negotiated_type": "fee schedule", "negotiated_rate": 72.69,
                                            "expiration_date": "9999-12-31", "billing_class": "professional",
                                            "service_code": ["11", "02"], "billing_code_modifier": ["25", "AS"]}]}]}]}  # fmt: skip
    p = tmp_path / "t.json.gz"
    p.write_bytes(gzip.compress(json.dumps(doc, indent=3).encode()))
    net = TicNetwork(
        **{**get_network("tic_uhc_choice_hmo_560").__dict__, "url": "https://x/t.json.gz"}
    )
    rr = run_pass(
        net, file_chunks(p), FetchInfo(url="u", fetched_at="t"), Paths(tmp_path), {"99213"}
    )
    t = Targets(tins={"1987654321": {""}})
    normalize_network(Path(rr.out_dir), net, rr.__dict__, t)
    (row,) = pq.read_table(Path(rr.out_dir) / "rate_row.parquet").to_pylist()
    assert row["entity_id"] == "npi:1987654321" and row["tic_provider_group_id"] < 0
    assert row["modifiers"] == "25|AS" and row["tic_service_codes"] == "02|11"
    assert row["amount"] == 72.69 and row["methodology"] == "fee_schedule"


def test_provider_references_after_in_network_fail_loudly():
    doc = b'{"version":"2.0.0","in_network":[{"negotiation_arrangement":"ffs","billing_code":"99213","negotiated_rates":[]}],"provider_references":[]}'
    with pytest.raises(ScanError, match="after in_network"):
        list(scan(InflatePass([gzip.compress(doc)], "gzip"), {"99213"}))


# ---------------------------------------------------------------- negotiated_type / modifiers


def test_percentage_vs_dollar(runs):
    rows = _rr(runs, "bcbs_hmo_blue_slice.json.gz")
    pct = [r for r in rows if r["tic_negotiated_type"] == "percentage"]
    dol = [r for r in rows if r["tic_negotiated_type"] == "fee schedule"]
    assert pct and dol
    for r in pct:
        assert r["dollar_basis"] == "pct_of_charges" and r["amount"] is None
        assert r["negotiated_pct"] is not None and r["negotiated_dollar"] is None
        assert r["methodology"] == "percent_of_total_billed_charges"
    for r in dol:
        assert r["dollar_basis"] == "dollar" and r["amount"] == r["negotiated_dollar"]
        assert r["methodology"] == "fee_schedule" and r["amount_method"] == "stated"


def test_modifiers_are_their_own_rows(runs):
    rows = _rr(runs, "bcbs_hmo_blue_slice.json.gz")
    afc_99213 = {
        (r["modifiers"], r["amount"])
        for r in rows
        if r["entity_id"] == f"tin:{AFC}" and r["code"] == "99213"
    }
    mods = {m for m, _ in afc_99213}
    assert {"56", "78"} <= mods  # BCBS Oct 2026: AFC 99213 only with -56 / -78 (insurer-tic.md)
    staged = pq.read_table(runs["bcbs_hmo_blue_slice.json.gz"][2] / "prices.parquet").to_pylist()
    assert any(p["billing_code_modifier"] for p in staged if p["billing_code"] == "73030")


# ---------------------------------------------------------------- visit codes per payer


def test_visit_code_map_shapes():
    vm = load_visit_map()
    assert vm.visit_codes("AETNA") == ("global_code", ["S9083"])
    assert vm.visit_codes("MGB_HP")[0] == "flat_visit"
    shape, codes = vm.visit_codes("HARVARD_PILGRIM")
    assert shape == "per_code_by_pos" and "99213" in codes
    assert vm.visit_codes("UHC")[0] == "per_code" and vm.visit_codes("BCBS_MA")[0] == "per_code"
    assert vm.all_codes <= target_codes()
    assert vm.pos_bucket(["11", "20"]) == "non_facility" and vm.pos_bucket(["22"]) == "facility"


def test_visit_map_finds_a_price_for_every_payer_fixture(runs):
    vm = load_visit_map()
    expect = {
        "aetna_ppo_slice.json.gz": {"S9083": {173.0}},
        "mgb_hmo_slice.json.gz": {"99203": {175.89}, "99213": {175.89}},
    }
    for name, (net, _run, _d) in runs.items():
        shape, codes = vm.visit_codes(net.payer_id)
        rows = [
            r
            for r in _rr(runs, name)
            if r["entity_id"] == f"tin:{AFC}" and r["code"] in codes and r["amount"]
        ]
        assert rows, f"{name}: no AFC visit price under the {shape} map"
        for code, amounts in expect.get(name, {}).items():
            assert amounts <= {r["amount"] for r in rows if r["code"] == code}


def test_hp_visit_rates_differ_by_place_of_service(runs):
    vm = load_visit_map()
    rows = [
        r
        for r in _rr(runs, "hphc_a008_slice.zip")
        if r["entity_id"] == f"tin:{AFC}" and r["code"] == "99203" and not r["modifiers"]
    ]
    by = {vm.pos_bucket(r["tic_service_codes"].split("|")): r["amount"] for r in rows}
    assert by["non_facility"] == 140.91 and by["facility"] == 85.66  # insurer-tic.md


# ---------------------------------------------------------------- TIN / NPI matching


def test_uhc_afc_is_matched_by_tin_not_name(runs):
    rows = _rr(runs, "uhc_choice_hmo_slice.json.gz")
    afc = [r for r in rows if r["entity_id"] == f"tin:{AFC}"]
    assert afc and {r["tic_business_name"] for r in afc} == {"MVNE 1"}
    assert {
        r["amount"]
        for r in afc
        if r["code"] == "99213" and not r["modifiers"] and "11" in r["tic_service_codes"].split("|")
    } == {72.69}


def test_npi_first_collects_every_tin_an_npi_bills_under(runs):
    d = runs["uhc_choice_hmo_slice.json.gz"][2]
    groups = pq.read_table(d / "groups.parquet").to_pylist()
    afc_npis = {n for g in groups if g["tin_digits"] == AFC for n in g["npis"]}
    tins_with_afc_npis = {g["tin_digits"] for g in groups if set(g["npis"]) & afc_npis}
    t = Targets(npis={n: {"GB_TEST"} for n in afc_npis})  # NPIs only, no TIN
    assert all(
        t.match(g["tin_digits"], g["npis"]) == "npi" for g in groups if set(g["npis"]) & afc_npis
    )
    assert AFC in tins_with_afc_npis
    matched = {g["tin_digits"] for g in groups if t.match(g["tin_digits"], g["npis"])}
    assert matched == tins_with_afc_npis
    assert t.sites_for(AFC, sorted(afc_npis)) == {"GB_TEST"}


def test_name_alone_never_matches():
    t = Targets(tins={AFC: {""}})
    assert t.match("999999999", ["1111111111"]) == ""
    assert t.match(AFC, []) == "tin"


# ---------------------------------------------------------------- index + range == full stream


@pytest.mark.parametrize("name", sorted(MAN))
def test_index_range_reads_equal_full_stream(runs, name, tmp_path):
    d = runs[name][2]
    idx = load_index(d)
    rep = verify_against_stream(
        d, idx, target_codes(), file_fetcher(str(FIX / name)), tmp_path / "v"
    )
    assert rep["ok"] and rep["price_rows_range"] == rep["price_rows_stream"] > 0
    sub = verify_against_stream(d, idx, {"99213"}, file_fetcher(str(FIX / name)), tmp_path / "v2")
    assert sub["ok"]


def _reblock(raw: bytes, member: int = 40_000, block: int = 3_000) -> bytes:
    """Re-compress real fixture bytes as several gzip members with many non-byte-aligned deflate
    block boundaries (Z_BLOCK flushes), to exercise checkpoints, inflatePrime and members."""
    import struct
    import zlib

    out = b""
    for m in range(0, len(raw), member):
        part = raw[m : m + member]
        c = zlib.compressobj(6, zlib.DEFLATED, -15)
        body = b"".join(
            c.compress(part[i : i + block]) + c.flush(zlib.Z_BLOCK)
            for i in range(0, len(part), block)
        )
        body += c.flush()
        out += (
            b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
            + body
            + struct.pack("<II", zlib.crc32(part), len(part))
        )
    return out


def test_checkpoints_inflate_prime_and_member_boundaries(tmp_path):
    raw = gzip.decompress((FIX / "bcbs_hmo_blue_slice.json.gz").read_bytes())
    data = _reblock(raw)
    p = InflatePass(
        [data[i : i + 7000] for i in range(0, len(data), 7000)], "gzip", span=4096, coalesce=1
    )
    assert b"".join(c for _o, c in p) == raw
    assert p.stats.members > 2 and len(p.checkpoints) > 20
    assert any(c.bits for c in p.checkpoints)  # non-byte-aligned resume points (inflatePrime)
    f = tmp_path / "re.gz"
    f.write_bytes(data)
    rnd = random.Random(7)
    for _ in range(40):
        a = rnd.randrange(0, len(raw) - 1)
        b = min(len(raw), a + rnd.randrange(1, 60_000))  # often crosses a member boundary
        assert (
            read_raw_range(p.checkpoints, a, b, file_fetcher(str(f)), "gzip", len(data), step=3000)
            == raw[a:b]
        )


def test_zip_member_inflates_like_zipfile():
    data = (FIX / "hphc_a008_slice.zip").read_bytes()
    p = InflatePass(
        [data[i : i + 5000] for i in range(0, len(data), 5000)], "zip", span=1 << 16, coalesce=1
    )
    raw = b"".join(c for _o, c in p)
    z = zipfile.ZipFile(io.BytesIO(data))
    assert raw == z.read(z.namelist()[0]) and p.stats.zip_member.endswith(".json")
    for a, b in ((0, 100), (len(raw) // 2, len(raw) // 2 + 70_000), (len(raw) - 50, len(raw))):
        assert (
            read_raw_range(
                p.checkpoints,
                a,
                b,
                file_fetcher(str(FIX / "hphc_a008_slice.zip")),
                "zip",
                len(data),
            )
            == raw[a:b]
        )


def test_corrupt_gzip_fails_crc():
    from app.etl.tic.zran import InflateError

    g = bytearray(gzip.compress(b'{"a":1}' * 1000))
    g[-8] ^= 0xFF  # CRC32 byte
    with pytest.raises(InflateError, match="CRC"):
        list(InflatePass([bytes(g)], "gzip"))


def test_scan_yields_items_in_file_order(runs):
    name = "uhc_choice_hmo_slice.json.gz"
    items = [
        x
        for x in scan(InflatePass(file_chunks(FIX / name), "gzip"), target_codes())
        if isinstance(x, TargetItem)
    ]
    codes = [i.ref.billing_code for i in items]
    assert codes == sorted(codes)  # UHC is sorted by billing_code
