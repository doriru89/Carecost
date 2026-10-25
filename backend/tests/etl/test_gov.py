"""Government fee-schedule readers (app.etl.gov): PFS + anesthesia, OPPS, ASC, MassHealth.

Fixtures are small files built here in the published layouts (copied from the real 2026-10
files, a few rows each), so every rule runs in CI without the real downloads."""

from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

from app.etl import cli
from app.etl.config import CONFIG_DIR, SourceSpec, load_sources
from app.etl.contracts import Method, PriceBasis, RateRow
from app.etl.gov import masshealth, opps_asc, pfs
from app.etl.gov.browser import BrowserBlocked, check_landing
from app.etl.gov.cli import check_anchors
from app.etl.gov.common import GovReadError, fee_schedule_money, finish

SHA = "a" * 64
OCT = date(2026, 10, 1)

PPRRVU = """\
,,2026 National Physician Fee Schedule Relative Value File October Release,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
,,CPT codes and descriptions only are copyright 2026 American Medical Association.,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
,,RELEASED 08/26/2026,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
,,,,,,,,,,,,,,,,,,,,,,,,,,,,,NON-FACILITY,FACILITY,
,,,,NOT USED,,,,,,,,,,,,,,,,,,,,,,PHYSICIAN,,DIAGNOSTIC,PE USED,PE USED,MP USED
,,,,FOR,,,NON-FAC,,FACILITY,,,,,,,,,,,,,,,,,SUPERVISION OF,,IMAGING,FOR OPPS,FOR OPPS,FOR OPPS
,,,STATUS,MEDICARE,WORK,NON-FAC,NA,FACILITY,NA,MP,NON-FACILITY,FACILITY,PCTC,GLOB,PRE,INTRA,POST,MULT,BILAT,ASST,CO-,TEAM,PRIC,ENDO,CONV,DIAGNOSTIC,CALCULATION,FAMILY,PAYMENT,PAYMENT,PAYMENT
HCPCS,MOD,DESCRIPTION,CODE,PAYMENT,RVU,PE RVU,INDICATOR,PE RVU,INDICATOR,RVU,TOTAL,TOTAL,IND,DAYS,OP,OP,OP,PROC,SURG,SURG,SURG,SURG,IND,BASE,FACTOR,PROCEDURES,FLAG,INDICATOR,AMOUNT,AMOUNT,AMOUNT
0001F,,Heart failure composite,I,,0.00,0.00,,0.00,,0.00,0.00,0.00,9,XXX,0.00,0.00,0.00,9,9,9,9,9,9,,33.4009,09,0,99,0.00,0.00,0.00
73030,,X-ray exam of shoulder,A,,0.18,0.87,,0.87,NA,0.02,1.07,1.07,1,XXX,0.00,0.00,0.00,0,3,0,0,0,9,,33.4009,09,0,99,2.71,2.71,0.04
73030,26,X-ray exam of shoulder,A,,0.18,0.08,,0.08,,0.01,0.27,0.27,1,XXX,0.00,0.00,0.00,0,3,0,0,0,9,,33.4009,09,0,99,0.00,0.00,0.00
99203,,Office o/p new low 30 min,A,,1.60,1.76,,0.38,,0.16,3.52,2.14,0,XXX,0.00,0.00,0.00,0,0,0,0,0,9,,33.4009,09,0,99,0.00,0.00,0.00
99213,,Office o/p est low 20 min,A,,1.30,1.46,,0.33,,0.09,2.85,1.72,0,XXX,0.00,0.00,0.00,0,0,0,0,0,9,,33.4009,09,0,99,0.00,0.00,0.00
"""
GPCI = """\
ADDENDUM E. FINAL CY 2026 GEOGRAPHIC PRACTICE COST INDICES (GPCIs) BY STATE AND MEDICARE LOCALITY,,,,,,
,,,,,,
Medicare Administrative Contractor (MAC),State,Locality Number,Locality Name,2026 PW GPCI (with 1.0 Floor)***,2026 PE GPCI,2026 MP GPCI
10112,AL,00,ALABAMA,1.000,0.875,0.566
14212,MA,01,METROPOLITAN BOSTON,1.041,1.194,0.890
14212,MA,99,REST OF MASSACHUSETTS,1.016,1.053,0.797
"""
ANES = """\
Contractor,Locality,Locality Name,Qualifying APM National Anes CF (with 2.5% statutory increase) of 20.599835,Non-Qualifying APM National Anes CF (with 2.5% Statutory increase)  of 20.49754
10112 ,00 ,ALABAMA,19.63,19.53
14212 ,01 ,METROPOLITAN BOSTON,21.70,21.59
14212 ,99 ,REST OF MASSACHUSETTS,20.74,20.64
"""


def _zip(path: Path, files: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for n, c in files.items():
            zf.writestr(n, c if isinstance(c, bytes) else c.encode("latin-1"))
    return path


def _rvu_zip(tmp_path: Path, pprrvu: str = PPRRVU) -> Path:
    return _zip(
        tmp_path / "rvu26d.zip",
        {"PPRRVU2026_Oct_nonQPP.csv": pprrvu, "GPCI2026.csv": GPCI, "ANES2026.csv": ANES},
    )


def _find(rows, code, plan, entity="medicare_ma_01", mod=""):
    hits = [
        r for r in rows
        if r["code"] == code and r["plan_raw"] == plan and r["entity_id"] == entity and r["modifiers"] == mod
    ]  # fmt: skip
    assert len(hits) == 1, (code, plan, entity, mod, hits)
    return hits[0]


# --------------------------------------------------------------------------- PFS


def test_pfs_99213_boston_matches_the_hand_computed_anchor(tmp_path):
    """(1.30*1.041 + 1.46*1.194 + 0.09*0.890) * 33.4009 = 106.10 (docs/etl/gov_fee_schedules.md)."""
    res = pfs.read_pfs(_rvu_zip(tmp_path), source_id="cms_pfs_rvu26d", sha=SHA, effective=OCT)
    rows = finish(res.rows)
    r = _find(rows, "99213", "non_facility")
    assert r["amount"] == 106.10
    assert r["negotiated_algorithm"].startswith("(1.30*1.041 + 1.46*1.194 + 0.09*0.890) * 33.4009")
    assert _find(rows, "99213", "facility")["amount"] == 61.04
    # the hand-made Medicare fixture's 99203 numbers (plan §2.4) come out of the same formula
    assert _find(rows, "99203", "non_facility")["amount"] == 130.58
    assert _find(rows, "99203", "facility")["amount"] == 75.54
    assert _find(rows, "99213", "non_facility", "medicare_ma_99")["amount"] == round(
        (1.30 * 1.016 + 1.46 * 1.053 + 0.09 * 0.797) * 33.4009, 2
    )


def test_pfs_skips_na_settings_and_unpaid_status(tmp_path):
    res = pfs.read_pfs(_rvu_zip(tmp_path), source_id="cms_pfs_rvu26d", sha=SHA, effective=OCT)
    rows = finish(res.rows)
    assert not [r for r in rows if r["code"] == "0001F"]  # status I: counted, not priced
    assert res.counts["status_I_not_priced"] == 1
    # global 73030 has facility NA: billed as -26 (+ hospital TC) there, never as global
    assert not [
        r
        for r in rows
        if r["code"] == "73030" and r["modifiers"] == "" and r["plan_raw"] == "facility"
    ]
    assert _find(rows, "73030", "facility", mod="26")["amount"] == 9.75
    assert len({r["row_ref"] for r in rows}) == len(rows)
    for r in rows:
        RateRow(**r)
        assert r["payer_id"] == "MEDICARE" and r["source_date"] == OCT


def test_pfs_fails_loudly_on_a_changed_layout(tmp_path):
    with pytest.raises(GovReadError, match="RELEASED"):
        pfs.read_pfs(
            _rvu_zip(tmp_path, PPRRVU.replace("RELEASED 08/26/2026", "")),
            source_id="x", sha=SHA, effective=OCT,
        )  # fmt: skip
    with pytest.raises(GovReadError, match="header"):
        pfs.read_pfs(
            _rvu_zip(tmp_path, PPRRVU.replace("HCPCS,MOD,DESCRIPTION,CODE,PAYMENT,RVU,PE RVU", "HCPCS,MOD,DESC,CODE,PAYMENT,RVU,PE RVU")),
            source_id="x", sha=SHA, effective=OCT,
        )  # fmt: skip


def test_anesthesia_is_base_units_times_the_locality_cf(tmp_path):
    bu = _zip(
        tmp_path / "bu.zip",
        {
            "base.txt": "CODE\t2022\n\tBASE\n\tUNIT\n"
            + "".join(f"00{100 + i}\t{i % 9 + 3}\n" for i in range(250))
            + "00811\t4\n"
        },
    )
    res = pfs.read_anesthesia(
        bu, _rvu_zip(tmp_path), SHA, source_id="cms_anes", sha="b" * 64, effective=OCT
    )
    r = _find(finish(res.rows), "00811", "anesthesia_base")
    assert r["amount"] == 86.36  # 4 * 21.59
    assert "time units" in r["negotiated_algorithm"] and "not included" in r["negotiated_algorithm"]


# --------------------------------------------------------------------------- OPPS / ASC

OPPS_TXT = (
    "\tAddendum B.-- OPPS Payment by HCPCS Code for CY 2026\t\t\n"
    "HCPCS Code\tShort Descriptor\tSI\tAPC\tRelative Weight\tPayment Rate\tNational Unadjusted Copayment\t Minimum Unadjusted Copayment\n"
    "0001F\tHeart failure composite\tE1\t\t\t\t\t\n"
    "73030\tX-ray exam of shoulder\tQ1\t5521\t0.9726\t$88.91\t.\t$17.79\n"
    "99213\tOffice o/p est low 20 min\tB\t\t\t\t\t\n"
    "G0463\tHospital outpt clinic visit\tJ2\t5012\t1.4879\t$136.02\t.\t$27.21\n"
    '29827\tSho arthrs srg rt8tr cuf rpr\tJ1\t5114\t81.0959\t"$7,413.38"\t.\t"$1,482.68"\n'
)


def test_opps_reads_g0463_and_skips_unpriced(tmp_path):
    z = _zip(
        tmp_path / "o.zip",
        {"508-compliant-version-2026_October_Web_Addendum_B.10.14.26.txt": OPPS_TXT},
    )
    res = opps_asc.read_opps(z, source_id="cms_opps", sha=SHA, effective=OCT)
    rows = finish(res.rows)
    g = _find(rows, "G0463", "opps", "medicare_national")
    assert g["amount"] == 136.02 and g["component"] == "facility"
    assert (
        "APC 5012" in g["negotiated_algorithm"]
        and "wage index not applied" in g["negotiated_algorithm"]
    )
    assert _find(rows, "29827", "opps", "medicare_national")["amount"] == 7413.38
    assert res.counts["no_payment_rate"] == 2
    with pytest.raises(GovReadError, match="month"):
        opps_asc.read_opps(z, source_id="cms_opps", sha=SHA, effective=date(2026, 7, 1))


ASC_AA = (
    '﻿"Addendum AA -- ASC Covered Surgical Procedures for CY 2026",,,,,,\n,,,,,,\n'
    "HCPCS Code,,Short Descriptor,Subject to Multiple Procedure Discounting,October 2026 Payment Indicator,October 2026  Payment Weight  ,October 2026 Payment Rate \n"
    "0095T,,Rmvl artific disc addl crvcl,N,N1,,\n"
    "45378,,Diagnostic colonoscopy,Y,A2,9.0638,$510.49 \n"
    '29827,,Sho arthrs srg rt8tr cuf rpr,Y,A2,65.6144,"$3,695.53 "\n'
)
ASC_BB = (
    '﻿"Addendum BB -- ASC Covered Ancillary Services",,,,,,,\n,,,,,,,\n'
    "HCPCS Code,,Short Descriptor,Drug and Device Pass-Through Expiration during Calendar Year,October 2026 Payment Indicator,October 2026 Payment Weight  ,October 2026 Payment Rate ,October 2026 IRA-22 Adjusted Copayment1\n"
    "73030,,X-ray exam of shoulder,,N1,,,\n"
    "73221,,Mri joint upr extrem w/o dye,,Z2,2.3345,$131.48,\n"
)


def test_asc_reads_aa_and_bb(tmp_path):
    z = _zip(
        tmp_path / "a.zip",
        {
            "508-Version-Oct-2026-ASC-AA.csv": ASC_AA.encode(),
            "508-Version-Oct-2026-ASC-BB.csv": ASC_BB.encode(),
        },
    )
    res = opps_asc.read_asc(z, source_id="cms_asc", sha=SHA, effective=OCT)
    rows = finish(res.rows)
    assert _find(rows, "45378", "asc", "medicare_national")["amount"] == 510.49
    assert _find(rows, "29827", "asc", "medicare_national")["amount"] == 3695.53
    assert _find(rows, "73221", "asc", "medicare_national")["amount"] == 131.48
    assert res.counts == {"AA_lines": 3, "AA_rows": 2, "BB_lines": 2, "BB_rows": 1, "rows": 3}


# --------------------------------------------------------------------------- MassHealth

MH_TEXT = """\
          (2) Applicable Dates of Service. Rates contained in 101 CMR 316.00 apply for dates of service
          on or after October 1, 2026, except as otherwise noted.
(3) Maximum Unit Fee. The maximum allowable fee for anesthesia services under 101 CMR
316.00 is $19.90 per base anesthesia unit and $1.33 per one minute time anesthesia unit.
    (4) Procedure Codes; Fee Schedules.
        (a) Anesthesia Services – List of Procedure Codes and Base Anesthesia Units.
Code    Units   Description
00811       5
01630       5
         (b) Surgical Services – Fee Schedule.
Code    NFAC        FAC      Global      PC       TC   www.mass.gov/regulations/101-
11102   $79.70    $28.01      -      -        -
15650   $418.77    $306.54       -       -        -
        $1,103.7
15730              $687.23       -       -        -
           2
20610   $49.06    $33.26       -       -        -
29827     -         -       $802.13    -        -
88399      -        -         I.C.      -            -
14301
        $826.94   $649.90      -        -            -
  *
 21208   $1,288.8
                    $553.11         -          -          -
   *        7
S8415      -          -         $500          -          -
          (c) Surgical Services – Fee Schedule for Facial Feminization Surgery Services to Treat
          Gender Dysphoria.
Code      NFAC        FAC       Global         PC   TC
14301    $1,182.78   $929.56       -           -    -
"""
RAD_TEXT = """\
apply for dates of service on or after October 1, 2026, except as otherwise noted.
Code    NFAC   FAC   Global   PC   TC
73030    -      -     $27.31     $6.75     $20.56
Code        NFAC       FAC www.mass.gov/regulations/101-CMR-31700-medicine)
99407 SA    $58.08    $54.04
"""


def test_masshealth_reads_tables_repairs_wraps_and_skips_ffs():
    res = masshealth.read_masshealth(
        Path("101-cmr-316.pdf"),
        source_id="mh316",
        sha=SHA,
        regulation="101 CMR 316.00",
        text=MH_TEXT,
    )
    rows = finish(res.rows)
    assert res.effective_date == OCT
    assert _find(rows, "20610", "non_facility", "masshealth")["amount"] == 49.06
    assert _find(rows, "20610", "facility", "masshealth")["amount"] == 33.26
    assert _find(rows, "29827", "global", "masshealth")["amount"] == 802.13
    assert _find(rows, "15730", "non_facility", "masshealth")["amount"] == 1103.72  # wrapped amount
    assert _find(rows, "15730", "facility", "masshealth")["amount"] == 687.23
    r = _find(rows, "14301", "non_facility", "masshealth")  # stacked asterisk row (4)(b) ...
    assert r["amount"] == 826.94 and "asterisk" in r["additional_generic_notes"]
    assert _find(rows, "21208", "non_facility", "masshealth")["amount"] == 1288.87
    assert _find(rows, "S8415", "global", "masshealth")["amount"] == 500.0
    assert not [x for x in rows if x["code"] == "88399"]  # I.C. = individual consideration
    assert res.counts["skipped: Surgical Services – Fee Schedule for Facial Feminization Sur"] == 1
    a = _find(rows, "00811", "anesthesia_base", "masshealth")
    assert a["amount"] == 99.50 and "$1.33 per minute" in a["negotiated_algorithm"]
    for x in rows:
        assert x["payer_id"] == "MASSHEALTH" and x["line_of_business"] == "medicaid"


def test_masshealth_pc_tc_and_modifier_rows():
    rows = finish(
        masshealth.read_masshealth(
            Path("r.pdf"), source_id="mh", sha=SHA, regulation="r", text=RAD_TEXT
        ).rows
    )
    assert _find(rows, "73030", "professional", "masshealth", "26")["amount"] == 6.75
    assert _find(rows, "73030", "technical", "masshealth", "TC")["amount"] == 20.56
    assert _find(rows, "99407", "non_facility", "masshealth", "SA")["amount"] == 58.08


def test_masshealth_fails_on_many_unparsed_rows_and_missing_date():
    broken = RAD_TEXT + "".join(f"7{i:04d}   $1.00\n" for i in range(masshealth.MAX_UNPARSED + 1))
    with pytest.raises(GovReadError, match="did not parse"):
        masshealth.read_masshealth(
            Path("r.pdf"), source_id="mh", sha=SHA, regulation="r", text=broken
        )
    with pytest.raises(GovReadError, match="dates of service"):
        masshealth.read_masshealth(
            Path("r.pdf"), source_id="mh", sha=SHA, regulation="r", text=RAD_TEXT.replace("on or after", "from")
        )  # fmt: skip


# --------------------------------------------------------------------------- shared


def test_fee_schedule_money_is_basis_fee_schedule_and_never_a_payer_rate(tmp_path):
    rows = finish(
        pfs.read_pfs(_rvu_zip(tmp_path), source_id="cms_pfs_rvu26d", sha=SHA, effective=OCT).rows
    )
    m = fee_schedule_money(_find(rows, "99213", "non_facility"))
    assert m.basis == PriceBasis.fee_schedule and m.prov.method == Method.computed_fee_schedule
    assert m.prov.payer_id is None and m.low == m.high == 106.10
    z = _zip(
        tmp_path / "o.zip", {"508-compliant-version-2026_October_Web_Addendum_B.txt": OPPS_TXT}
    )
    g = _find(
        finish(opps_asc.read_opps(z, source_id="cms_opps", sha=SHA, effective=OCT).rows),
        "G0463",
        "opps",
        "medicare_national",
    )
    assert fee_schedule_money(g).prov.method == Method.stated


def test_anchor_gate(tmp_path):
    spec = load_sources().get("cms_pfs_rvu26d")
    rows = finish(
        pfs.read_pfs(_rvu_zip(tmp_path), source_id=spec.source_id, sha=SHA, effective=OCT).rows
    )
    anchors = yaml.safe_load((CONFIG_DIR / "gov_anchors.yaml").read_text())["anchors"]
    assert check_anchors(spec, SHA, rows, anchors) == []  # within tolerance on another file
    real = next(a for a in anchors if a["id"] == "pfs_99213_boston_office")
    bad = [{**real, "amount": 50.0}]
    assert "drifted" in check_anchors(spec, SHA, rows, bad)[0]
    assert (
        "missing" in check_anchors(spec, SHA, [r for r in rows if r["code"] != "99213"], [real])[0]
    )
    assert (
        "own file"
        in check_anchors(spec, SHA, rows, [{**real, "exact_sha256": SHA, "amount": 106.11}])[0]
    )


def test_government_sources_validate():
    gov = [s for s in load_sources().sources if s.is_gov_source]
    assert {s.format for s in gov} == {
        "cms_pfs_rvu_zip", "cms_anes_base_units_zip", "cms_opps_addendum_b_zip",
        "cms_asc_addenda_zip", "masshealth_regulation_pdf",
    }  # fmt: skip
    assert not any(s.is_rate_row_source for s in gov)
    opps = load_sources().get("cms_opps_addb_2026q4")
    assert opps.access == "manual" and opps.manual_filename
    for s in gov:
        assert s.effective_date and s.next_release
        if s.access == "browser":
            assert s.landing_url and s.landing_url.startswith("https://www.mass.gov/")


@pytest.mark.parametrize(
    "patch, msg",
    [
        ({"access": "browser", "landing_url": None}, "landing_url"),
        ({"access": "manual", "manual_filename": None}, "manual_filename"),
        ({"access": "manual", "manual_filename": "../x.zip"}, "bare file name"),
        ({"effective_date": None}, "effective_date"),
    ],
)
def test_gov_access_rules(patch, msg):
    base = yaml.safe_load((CONFIG_DIR / "sources.d" / "government.yaml").read_text())["sources"]
    mh = next(s for s in base if s["format"] == "masshealth_regulation_pdf")
    if patch.get("access") == "manual":
        mh = {**mh, "access": "manual"}
    with pytest.raises(ValueError, match=msg):
        SourceSpec.model_validate({**mh, **patch})


@pytest.mark.parametrize(
    "status, title, body",
    [
        (403, "Forbidden", ""),
        (200, "Just a moment... captcha", ""),
        (429, "x", "verify you are human"),
    ],
)
def test_browser_stops_on_403_or_challenge(status, title, body):
    with pytest.raises(BrowserBlocked):
        check_landing(status, title, body, "https://www.mass.gov/x")


def test_browser_accepts_a_normal_page():
    check_landing(
        200, "101 CMR 317.00: Rates for Medicine Services | Mass.gov", "", "https://www.mass.gov/x"
    )


def test_cli_gov_manual_fetch_and_build_end_to_end(tmp_path, capsys):
    """manual import -> store + manifest (D18 fields) -> RateRow parquet + manifest + LATEST."""
    cfg = tmp_path / "etl"
    (cfg / "sources.d").mkdir(parents=True)
    base = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())
    base["sources"] = []
    (cfg / "sources.yaml").write_text(yaml.safe_dump(base))
    gov = yaml.safe_load((CONFIG_DIR / "sources.d" / "government.yaml").read_text())
    gov["sources"] = [s for s in gov["sources"] if s["source_id"] == "cms_opps_addb_2026q4"]
    (cfg / "sources.d" / "government.yaml").write_text(yaml.safe_dump(gov))
    anchors = yaml.safe_load((CONFIG_DIR / "gov_anchors.yaml").read_text())
    (cfg / "gov_anchors.yaml").write_text(yaml.safe_dump(anchors))
    data = tmp_path / "data"
    (data / "raw" / "manual").mkdir(parents=True)
    _zip(
        data / "raw" / "manual" / gov["sources"][0]["manual_filename"],
        {"508-compliant-version-2026_October_Web_Addendum_B.10.14.26.txt": OPPS_TXT},
    )
    args = ["--data-dir", str(data), "--config-dir", str(cfg), "gov"]
    assert cli.main([*args, "fetch"]) == 0
    rec = json.loads((data / "raw" / "store" / "fetch_manifest.jsonl").read_text().splitlines()[-1])
    assert rec["method"] == "manual" and rec["fetched_at"] and "AMA" in rec["note"]
    assert cli.main([*args, "build", "--as-of", "2026-10-24"]) == 0
    latest = json.loads((data / "intermediate" / "gov" / "LATEST.json").read_text())
    e = latest["cms_opps_addb_2026q4"]
    t = pq.read_table(data / e["parquet"]).to_pylist()
    assert {r["code"] for r in t} == {"73030", "G0463", "29827"}
    m = json.loads((data / e["manifest"]).read_text())
    assert m["freshness_at_build"]["expected_by"] == "2027-01-01"
    assert m["freshness_at_build"]["late_to_refresh"] is False
    assert m["fetch"]["method"] == "manual"
    assert "GOV    cms_opps_addb_2026q4: 3 rows" in capsys.readouterr().out
