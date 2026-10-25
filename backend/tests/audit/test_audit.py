"""Outlier audit (stream O): peer medians, cause rules, fix simulation, backtest and tracing."""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import pytest

from app.audit.backtest import backtest
from app.audit.causes import Classifier, outlying
from app.audit.fixes import children_apart, drop_placeholders, main_contract, site_pos
from app.audit.peers import LineBuilder, Line, measure
from app.audit.trace import Tracer
from app.quote.registry import Registry
from app.quote.store import (
    RateStore,
    Row,
    SourceMeta,
    DataVersionInfo,
    make_row,
    store_from_extract,
)


def row(i: int, amount: float, *, code="99213", tin="t", src="tic_x", kind="insurer_tic",
        pos="11", bclass="professional", gross=None, pct=None, plan="", npi_set=0, lob="commercial",
        cash=None) -> Row:  # fmt: skip
    return make_row({
        "source_id": src, "source_kind": kind, "row_id": f"r{i}", "stage_row": i,
        "row_kind": "payer_rate", "code": code, "modifiers": "", "component": bclass,
        "billing_class": bclass, "setting": "both", "payer_id": "P", "product": "HMO",
        "line_of_business": lob, "plan_raw": plan, "amount": amount, "amount_method": "stated",
        "negotiated_pct": pct, "gross": gross, "tin": tin, "service_codes": pos,
        "npi_set": npi_set, "discounted_cash": cash,
    })  # fmt: skip


def line(group: str, *vals_rows, kind="office", code="99213", comp="professional", family="tic",
         sites=("s",)) -> Line:  # fmt: skip
    ln = Line(kind, code, "", comp, "P", "HMO", "tic_x", group, family)
    for v, r in vals_rows:
        ln.rows[r.uid] = (v, r)
    ln.sites = set(sites)
    return ln


def peers(n: int, value: float, code="99213", kind="office", start=1000) -> list[Line]:
    return [line(f"g{k}", (value, row(start + k, value, code=code, tin=f"g{k}")), code=code,
                 kind=kind) for k in range(n)]  # fmt: skip


# --------------------------------------------------------------------------- peers / measure


def test_measure_needs_five_other_groups_and_flags_3x() -> None:
    target = line("bad", (400.0, row(1, 400.0, tin="bad")))
    m = {x.line.group: x for x in measure([target, *peers(5, 100.0)])}
    assert m["bad"].peer_groups == 5 and m["bad"].peer_median == 100.0
    assert m["bad"].outlier == "high"
    assert not measure([target, *peers(4, 100.0)])  # 4 other groups: not measured


def test_measure_band_edges() -> None:
    at3 = line("edge", (300.0, row(1, 300.0, tin="edge")))
    low = line("low", (33.0, row(2, 33.0, tin="low")))
    out = {x.line.group: x.outlier for x in measure([at3, low, *peers(6, 100.0)])}
    assert out["edge"] is None  # exactly 3x is inside the band
    assert out["low"] == "low"  # 0.33x < 1/3


def test_line_builder_on_extract_follows_engine_rules() -> None:
    store = store_from_extract()
    reg = Registry.load()
    lines = LineBuilder(store, reg).build()
    assert lines
    for ln in lines:
        assert ln.kind in ("urgent_care", "office", "hospital_outpatient", "asc")
        for v, r in ln.rows.values():
            assert v is not None and v >= 0
            if ln.family == "tic" and ln.component == "facility":
                assert r.billing_class == "facility" and r.negotiated_type != "percentage"
            if ln.family == "mrf_cash":
                assert ln.payer == "SELF_PAY" and v == r.discounted_cash
            if ln.family == "tic":
                assert ln.network == r.source_id  # network level: one file per line
    # an office-billed site never carries a facility line (engine _site_lines)
    office = {s.id for s in reg.sites.values() if s.billing_type == "office_visit"}
    assert not [ln for ln in lines if ln.component == "facility" and ln.sites <= office]


# --------------------------------------------------------------------------- causes


def classify(target: Line, others: list[Line], quote: str = "", children=frozenset()):
    lines = [target, *others]
    ms = measure(lines)
    m = next(x for x in ms if x.line is target)
    assert m.outlier
    return Classifier(lines, ms, children).classify(m, quote)


def test_cause_placeholder_and_not_dollars() -> None:
    assert classify(line("z", (0.01, row(1, 0.01, tin="z"))), peers(5, 100.0)).cause == \
        "placeholder"  # fmt: skip
    r = row(1, 5.04, src="h", kind="hospital_mrf", gross=3510.55, code="45378")
    t = line("mrf:h", (5.04, r), kind="hospital_outpatient", code="45378", comp="facility",
             family="mrf")  # fmt: skip
    others = [line(f"mrf:o{k}", (1400.0, row(10 + k, 1400.0, src=f"o{k}", kind="hospital_mrf",
                                             code="45378")),
                   kind="hospital_outpatient", code="45378", comp="facility", family="mrf")
              for k in range(5)]  # fmt: skip
    assert classify(t, others).cause == "not_dollars"


def test_cause_chargemaster_and_per_diem() -> None:
    def hosp(v, gross):
        return line("mrf:h", (v, row(1, v, src="h", kind="hospital_mrf", gross=gross)),
                    kind="hospital_outpatient", comp="facility", family="mrf")  # fmt: skip

    def others():
        return [line(f"mrf:o{k}", (100.0, row(10 + k, 100.0, src=f"o{k}", kind="hospital_mrf")),
                     kind="hospital_outpatient", comp="facility", family="mrf")
                for k in range(5)]  # fmt: skip

    assert classify(hosp(608.0, 608.0), others()).cause == "chargemaster_as_rate"
    v = classify(hosp(2527.45, 4105.0), others(), quote='{"description":"HC PER DIEM PAIN"}')
    assert v.cause == "per_diem_or_case_rate"


def test_cause_pos_facility_rate_at_office() -> None:
    bad = row(1, 20.0, tin="x", pos="01|02|19|20|22")
    assert classify(line("x", (20.0, bad)), peers(5, 100.0)).cause == \
        "pos_facility_rate_at_office"  # fmt: skip


def test_cause_flat_rate_and_rate_group() -> None:
    fam = ["99212", "99213", "99214"]
    flat = [line("f", (400.0, row(i, 400.0, tin="f", code=c)), code=c) for i, c in enumerate(fam)]
    others = [p for c in fam for p in peers(5, 100.0, code=c, start=100 * (fam.index(c) + 1))]
    lines = flat + others
    ms = measure(lines)
    m = next(x for x in ms if x.line is flat[1])
    assert Classifier(lines, ms).classify(m).cause == "flat_rate"
    t = line("rg", (100.0, row(1, 100.0, tin="rg", npi_set=1)),
             (400.0, row(2, 400.0, tin="rg", npi_set=2)))  # fmt: skip
    assert classify(t, peers(5, 100.0)).cause == "rate_group_within_tin"
    twin = line("tw", (100.0, row(1, 100.0, tin="tw", npi_set=7)),
                (400.0, row(2, 400.0, tin="tw", npi_set=7)))  # fmt: skip
    assert classify(twin, peers(5, 100.0)).cause == "ambiguous_multi_rate"


def test_cause_contract_level_and_children() -> None:
    codes = ["11300", "11301", "11302", "11303", "11305", "11306"]
    hi = [line("c", (350.0 + i, row(i, 350.0 + i, tin="c", code=c)), code=c)
          for i, c in enumerate(codes)]  # fmt: skip
    others = [p for j, c in enumerate(codes)
              for p in peers(5, 100.0 + 10 * j, code=c, start=100 * (j + 1))]  # fmt: skip
    lines = hi + others
    ms = measure(lines)
    m = next(x for x in ms if x.line is hi[0])
    assert Classifier(lines, ms).classify(m).cause == "contract_level"
    assert Classifier(lines, ms, frozenset({"s"})).classify(m).cause == "children_only_contract"


def test_outlying_most_extreme_first() -> None:
    t = line("x", (500.0, row(1, 500.0, tin="x")), (900.0, row(2, 900.0, tin="x")))
    m = next(x for x in measure([t, *peers(5, 100.0)]) if x.line is t)
    assert [v for v, _ in outlying(m)] == [900.0, 500.0]


# --------------------------------------------------------------------------- fixes


def test_fixes() -> None:
    store = RateStore(rows=[], sources={}, version=DataVersionInfo("b", "2026-10-24", None),
                      npi_sets={1: ("a",), 2: ("a", "b", "c")})  # fmt: skip
    ph = line("p", (0.5, row(1, 0.5, tin="p")), (90.0, row(2, 90.0, tin="p")))
    assert [v for v, _ in drop_placeholders([ph], store)[0].rows.values()] == [90.0]
    office = line("o", (20.0, row(1, 20.0, tin="o", pos="19|20|22")),
                  (90.0, row(2, 90.0, tin="o", pos="11")))  # fmt: skip
    assert [v for v, _ in site_pos([office], store)[0].rows.values()] == [90.0]
    uc = line("u", (20.0, row(1, 20.0, tin="u", pos="19|20|22")),
              (90.0, row(2, 90.0, tin="u", pos="11")), kind="urgent_care")  # fmt: skip
    assert [v for v, _ in site_pos([uc], store)[0].rows.values()] == [20.0]
    assert site_pos([uc], store, kinds=("office",))[0] is uc
    mc = line("m", (20.0, row(1, 20.0, tin="m", npi_set=1)), (90.0, row(2, 90.0, tin="m",
                                                                        npi_set=2)))  # fmt: skip
    assert [v for v, _ in main_contract([mc], store)[0].rows.values()] == [90.0]
    ch = children_apart([line("k", (1.0, row(1, 1.0)), sites=("kid",))], store,
                        children_only=frozenset({"kid"}))  # fmt: skip
    assert ch[0].kind == "office:children"


# --------------------------------------------------------------------------- backtest


def test_backtest_modes() -> None:
    lines = []
    for k in range(6):  # system A prices at 100, system B at 300, both office
        sys_id = "a" if k < 3 else "b"
        v = 100.0 if sys_id == "a" else 300.0
        ln = line(f"g{k}", (v, row(k, v, tin=f"g{k}")))
        ln.systems = {sys_id}
        lines.append(ln)
    for k in range(6, 9):  # independents at 200
        lines.append(line(f"g{k}", (200.0, row(k, 200.0, tin=f"g{k}"))))
    bt = backtest(lines)["office"]
    assert bt["lines"] == 9 and bt["coverage"] == 1.0
    # system peers (2 others per system) are < 3: the system mode falls back to same_kind
    assert bt["where_system_peers_used"]["n"] == 0
    for k in range(9, 11):  # one more member each: now 3 other system groups
        sys_id = "a" if k == 9 else "b"
        v = 100.0 if sys_id == "a" else 300.0
        ln = line(f"g{k}", (v, row(k, v, tin=f"g{k}")))
        ln.systems = {sys_id}
        lines.append(ln)
    bt = backtest(lines)["office"]
    used = bt["where_system_peers_used"]
    assert used["n"] == 8
    assert used["same_system"]["median_ape"] == 0.0 < used["same_kind"]["median_ape"]


# --------------------------------------------------------------------------- tracing


def _meta(sid: str, file: str, sha: str) -> SourceMeta:
    return SourceMeta(sid, "hospital_mrf", "H", file, sha, None, None, "2026-10-25",
                      "hospital_mrf_365_days", "hospital_monthly")  # fmt: skip


@pytest.fixture()
def tiny_store(tmp_path: Path) -> tuple[RateStore, Path, Path]:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    raw, staging = tmp_path / "raw", tmp_path / "staging"
    # tall CSV: 3 header lines, stage_row n on physical line n + 4
    (raw / "hc").mkdir(parents=True)
    lines = ["hospital_name,last_updated_on", "H,2026-04-01",
             "description,code|1,code|1|type,payer_name,plan_name,standard_charge|negotiated_dollar",
             "Visit,99213,CPT,AETNA,HB AETNA,10.00", "Visit,99213,CPT,BCBS,HB BCBS PPO,612.50"]  # fmt: skip
    (raw / "hc" / "c.csv").write_bytes("\n".join(lines).encode("cp1252") + b"\n")
    # JSON v3, zipped, with a BOM
    (raw / "hj").mkdir()
    doc = {"standard_charge_information": [
        {"description": "X", "code_information": [{"code": "11111", "type": "CPT"}],
         "standard_charges": [{"payers_information": []}]},
        {"description": "HC PER DIEM PAIN TREATMENT",
         "code_information": [{"code": "99215", "type": "CPT"}],
         "standard_charges": [{"setting": "outpatient", "gross_charge": 4105.0,
                               "payers_information": [
                                   {"payer_name": "U", "plan_name": "Other", "standard_charge_dollar": 1.0},
                                   {"payer_name": "U", "plan_name": "All", "standard_charge_dollar": 3429.73}]}]}]}  # fmt: skip
    with zipfile.ZipFile(raw / "hj" / "j.zip", "w") as z:
        z.writestr("j.json", b"\xef\xbb\xbf" + json.dumps(doc).encode())
    for sid, recs in (("hc", [{"stage_row": 1, "item_ordinal": 1, "payer_name": "BCBS",
                               "plan_name": "HB BCBS PPO"}]),
                      ("hj", [{"stage_row": 7, "item_ordinal": 1, "payer_name": "U",
                               "plan_name": "All"}])):  # fmt: skip
        (staging / sid).mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(recs), staging / sid / f"{sid}sha.parquet")
    store = RateStore(rows=[], sources={"hc": _meta("hc", "c.csv", "hcsha"),
                                        "hj": _meta("hj", "j.zip", "hjsha")},
                      version=DataVersionInfo("b", "2026-10-24", None))  # fmt: skip
    return store, raw, staging


def test_trace_hospital_csv_and_json(tiny_store) -> None:
    store, raw, staging = tiny_store
    a = row(1, 612.5, src="hc", kind="hospital_mrf")
    b = row(7, 3429.73, src="hj", kind="hospital_mrf", code="99215")
    tr = Tracer(store, raw, staging, raw).trace_all([a, b])
    assert tr[a.uid].verified == "raw_line" and tr[a.uid].pointer.endswith("line 5")
    assert tr[a.uid].quote == "Visit,99213,CPT,BCBS,HB BCBS PPO,612.50"
    assert tr[b.uid].verified == "raw_json"
    assert "standard_charge_information[1].standard_charges[0].payers_information[1]" in \
        tr[b.uid].pointer  # fmt: skip
    assert "PER DIEM" in tr[b.uid].quote


def test_committed_outputs_agree() -> None:
    """data/audit/outliers.csv and summary.json come from the same run."""
    root = Path(__file__).resolve().parents[3] / "data" / "audit"
    if not (root / "summary.json").exists():
        pytest.skip("no committed audit run")
    s = json.loads((root / "summary.json").read_text())
    with (root / "outliers.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == s["outliers"]
    assert sum(s["causes"].values()) == s["outliers"]
    for c, n in s["causes"].items():
        assert sum(1 for r in rows if r["cause"] == c) == n
    assert all(r["source_pointer"] for r in rows)
    assert sum(1 for r in rows if r["trace"] == "not_found") == s["trace_status"].get(
        "not_found", 0
    )


# --------------------------------------------------------------------------- A7


def test_cause_flat_visit_rate_tufts_convenientmd_shape() -> None:
    """Tufts Direct pays ConvenientMD $125 on 99203/99204/99213/99214/81003/81025: the lab line
    at $125 is one amount per visit, not a 25x lab price."""
    codes = ["99203", "99204", "99213", "99214", "81003", "81025"]
    flat = [line("cmd", (125.0, row(i, 125.0, tin="cmd", code=c)), code=c, kind="urgent_care")
            for i, c in enumerate(codes)]  # fmt: skip
    others = [p for j, c in enumerate(codes)
              for p in peers(5, 5.0 if c.startswith("81") else 120.0, code=c, kind="urgent_care",
                             start=100 * (j + 1))]  # fmt: skip
    lines = flat + others
    ms = measure(lines)
    m = next(x for x in ms if x.line is flat[4])  # 81003
    assert m.outlier == "high"
    v = Classifier(lines, ms).classify(m)
    assert v.cause == "flat_visit_rate"
    assert "99203" in v.detail and "81025" in v.detail


def test_flat_visit_rate_needs_a_visit_code_and_three_codes() -> None:
    def verdict(codes: list[str]) -> str:
        flat = [line("g", (125.0, row(i, 125.0, tin="g", code=c)), code=c)
                for i, c in enumerate(codes)]  # fmt: skip
        others = [p for j, c in enumerate(codes)
                  for p in peers(5, 5.0, code=c, start=100 * (j + 1))]  # fmt: skip
        lines = flat + others
        ms = measure(lines)
        return Classifier(lines, ms).classify(next(x for x in ms if x.line is flat[-1])).cause

    assert verdict(["81025", "85025", "81003"]) != "flat_visit_rate"  # no visit code
    assert verdict(["99213", "81003"]) != "flat_visit_rate"  # two codes can be chance
    assert verdict(["99051", "S9088", "81003"]) != "flat_visit_rate"  # add-ons are not visits
    assert verdict(["99213", "99214", "99051"]) != "flat_visit_rate"  # ... nor non-visit items
    assert verdict(["99213", "99214", "81003"]) == "flat_visit_rate"


def test_anesthesia_base_units_cite_the_cy2022_file() -> None:
    import inspect

    from app.audit import causes

    src = inspect.getsource(causes)
    assert "ANES2026.csv): 00811" not in src
    assert "CY2022" in src and causes.ANES_BASE_UNITS == {"00811": 4, "00812": 3, "00813": 5}


def test_one_contract_in_many_network_files_counts_once() -> None:
    from app.audit.__main__ import contract_key, distinct
    from app.audit.causes import Verdict

    ms = []
    for k in range(15):  # the same HPHC contract copied into 15 network files
        t = Line("office", "99213", "", "professional", "HPHC", "HMO", f"tic_hp_{k}", "bad",
                 "tic")  # fmt: skip
        t.rows["u"] = (400.0, row(1, 400.0, tin="bad", src=f"tic_hp_{k}"))
        ps = []
        for j in range(5):
            p = Line("office", "99213", "", "professional", "HPHC", "HMO", f"tic_hp_{k}",
                     f"g{j}", "tic")  # fmt: skip
            p.rows[f"p{j}"] = (100.0, row(100 + j, 100.0, tin=f"g{j}", src=f"tic_hp_{k}"))
            ps.append(p)
        ms += [x for x in measure([t, *ps]) if x.line is t]
    other = line("bad", (40.0, row(9, 40.0, tin="bad")))  # another amount: another contract
    ms += [x for x in measure([other, *peers(5, 400.0)]) if x.line is other]
    assert len(ms) == 16 and len({contract_key(m) for m in ms}) == 2
    d = distinct(ms, [Verdict("unexplained", "")] * 16)
    assert (d["outlier_rows"], d["outlier_contracts"]) == (16, 2)
    assert (d["unexplained_rows"], d["unexplained_contracts"]) == (16, 2)


def test_flat_visit_rate_is_not_read_into_a_hospital_file() -> None:
    """CHA Cigna: 58.3% of the same $195 charge on 99213 / 97161 / 97162 is not a visit rate."""
    codes = ["99213", "97162", "97161"]

    def hosp(g, v, c, i):
        return line(g, (v, row(i, v, src=g, kind="hospital_mrf", code=c)),
                    kind="hospital_outpatient", code=c, comp="facility", family="mrf")  # fmt: skip

    flat = [hosp("mrf:cha", 113.69, c, i) for i, c in enumerate(codes)]
    others = [hosp(f"mrf:o{k}", 400.0, c, 100 * (j + 1) + k)
              for j, c in enumerate(codes) for k in range(5)]  # fmt: skip
    lines = flat + others
    ms = measure(lines)
    m = next(x for x in ms if x.line is flat[-1])
    assert Classifier(lines, ms).classify(m).cause != "flat_visit_rate"
