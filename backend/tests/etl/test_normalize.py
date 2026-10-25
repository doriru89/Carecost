"""normalize: staged leaves -> rate_row (never collapsed). Golden fixtures are real rows."""

from __future__ import annotations

import re
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

from app.etl import normalize, stage
from app.etl.config import load_codes, load_sources
from app.etl.contracts import Money, NotPublished, PercentOnly, RateRow

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mrf"
MANIFEST = yaml.safe_load((FIX / "MANIFEST.yaml").read_text())


def run(tmp_path: Path, source_id: str, fixture: str):
    spec = load_sources().get(source_id).model_copy(update={"container": "plain"})
    sha = MANIFEST["fixtures"][fixture]["source_sha256"]
    sres = stage.stage_file(spec, FIX / fixture, sha, tmp_path / "staged.parquet")
    nres = normalize.normalize_file(
        spec, tmp_path / "staged.parquet", sres, tmp_path / "rr.parquet"
    )
    rows = [RateRow(**r) for r in pq.read_table(tmp_path / "rr.parquet").to_pylist()]
    return sres, nres, rows


# Golden 1 -- the anchor: patient pays BOTH lines; old ETL kept one of them.
def test_brigham_11102_aetna_hmo_facility_plus_professional(tmp_path):
    _, _, rows = run(tmp_path, "brigham_mrf", "brigham_11102.csv")
    hmo = [r for r in rows if r.plan_raw == "HB AMC AETNA HMO"]
    by_comp = {r.component.value: r for r in hmo}
    assert set(by_comp) == {"facility", "professional"} and len(hmo) == 2
    fac, pro = by_comp["facility"], by_comp["professional"]
    assert (fac.rev_code, fac.amount) == ("0761", 417.40)
    assert (pro.rev_code, pro.amount) == ("0983", 115.17)
    assert round(fac.amount + pro.amount, 2) == 532.57
    assert fac.payer_id == "AETNA" and fac.line_of_business == "commercial" and fac.product == "HMO"
    assert fac.dollar_basis == "pct_of_charges" and fac.amount_method == "stated"
    assert fac.methodology == "percent_of_total_billed_charges"
    assert fac.gross == 598.0 and fac.gross_rule == "same_row"
    assert fac.nk_hash != pro.nk_hash


# Golden 2 -- BIDMC 73030: payer item joined to the chargemaster item on (code, setting).
def test_bidmc_73030_payer_rates_and_joined_gross(tmp_path):
    _, _, rows = run(tmp_path, "bidmc_mrf", "bidmc_73030.json")
    rates = [r for r in rows if r.row_kind == "payer_rate"]
    assert len(rates) == 6
    bcbs = next(r for r in rates if (r.payer_raw, r.plan_raw) == ("Bcbs", "Hmo"))
    assert bcbs.amount == 110.42 and bcbs.methodology == "fee_schedule"
    assert bcbs.payer_id == "BCBS_MA" and bcbs.setting == "outpatient"
    assert bcbs.component == "facility" and bcbs.component_rule == "billing_class"
    assert (bcbs.gross, bcbs.gross_rule) == (395.0, "joined_code_setting")
    cdm = [r for r in rows if r.row_kind == "chargemaster"]
    assert (
        len(cdm) == 1 and cdm[0].rev_code == "0320" and cdm[0].billing_class == "facility"
    )  # 'facillity'
    assert isinstance(cdm[0].to_cell(), Money) and cdm[0].to_cell().basis == "discounted_cash"


# Golden 3 -- Franciscan wide: every payer|plan group becomes its own rate row.
def test_franciscan_wide_rows_resolve_payers(tmp_path):
    sres, nres, rows = run(tmp_path, "franciscan_mrf", "franciscan_99213.csv")
    assert nres.target_leaves == sres.staged_rows  # every line in the fixture carries 99213
    rates = [r for r in rows if r.row_kind == "payer_rate"]
    assert {r.payer_id for r in rates} >= {
        "AETNA",
        "BCBS_MA",
        "HARVARD_PILGRIM",
        "TUFTS_HP",
        "MASSHEALTH",
    }
    oos = [r for r in rates if r.plan_raw.endswith("Out of State")]
    assert oos and all(r.excluded and r.exclude_reason == "out_of_state" for r in oos)
    assert all(r.methodology_raw for r in rates if r.amount is not None)


# Golden 4 -- the source itself is ambiguous: three Unicare GIC rates, identical attributes.
def test_bidmc_99213_unicare_gic_three_rates_survive_flagged(tmp_path):
    _, _, rows = run(tmp_path, "bidmc_mrf", "bidmc_99213.json")
    gic = [
        r
        for r in rows
        if r.plan_raw == "Gic Wellpoint All Commercial Plans" and r.payer_raw == "Unicare"
    ]
    assert sorted(r.amount for r in gic) == [31.0, 97.74, 110.38]
    assert len({r.nk_hash for r in gic}) == 1
    assert sorted(r.nk_ordinal for r in gic) == [0, 1, 2]
    assert all(r.ambiguous_multi_rate for r in gic)
    assert len({r.row_id for r in rows}) == len(rows)
    # the same file also lists MassHealth ACO twice ($84.11 / $71.49); BCBS once each
    mh = [r for r in rows if r.payer_raw == "Masshealth"]
    assert len(mh) == 2 and all(r.ambiguous_multi_rate for r in mh)
    bcbs = [r for r in rows if r.payer_raw == "Bcbs"]
    assert len(bcbs) == 2 and not any(r.ambiguous_multi_rate for r in bcbs)


# Golden 5 -- CHA catch-all contract is kept but excluded from consumer prices.
def test_cha_catch_all_flagged_and_component_unknown(tmp_path):
    _, nres, rows = run(tmp_path, "cha_mrf", "cha_45378.csv")
    catch = [r for r in rows if r.plan_raw == "CHA HB CATCH-ALL CONTRACT"]
    assert catch and all(r.excluded for r in catch)
    assert {r.exclude_reason for r in catch} >= {"catch_all", "dental"}
    assert all(
        r.component == "unknown" and r.component_rule == "none" for r in rows
    )  # CHA has no RC
    medicaid = [r for r in rows if r.payer_id == "MASSHEALTH"]
    assert medicaid, "MassHealth rows must be imported (D4)"
    # A6 (O audit): the fixture's one MassHealth row is $4.44 on a $3,510.55 gross, the row O
    # traced as `not_dollars` (CHA line 187058): imported, but never a price
    std = [r for r in medicaid if r.plan_raw == "CHA HB MEDICAID-STANDARD"]
    assert std and all(r.excluded and r.exclude_reason == "not_dollars" for r in std)


# Golden 6 -- row conservation through normalize: every target leaf is a row or a counted drop.
@pytest.mark.parametrize(
    "sid, fx",
    [
        ("brigham_mrf", "brigham_11102.csv"),
        ("cha_mrf", "cha_45378.csv"),
        ("bidmc_mrf", "bidmc_99213.json"),
        ("franciscan_mrf", "franciscan_99213.csv"),
    ],
)
def test_normalize_conserves_rows(tmp_path, sid, fx):
    _, nres, rows = run(tmp_path, sid, fx)
    assert nres.target_leaves == len(rows) + sum(nres.placeholders_dropped.values())
    assert nres.rate_rows == len(rows)


# Golden 7 -- provenance on every row: basename only, sha, ISO date, row ref.
@pytest.mark.parametrize(
    "sid, fx",
    [
        ("brigham_mrf", "brigham_11102.csv"),
        ("bidmc_mrf", "bidmc_73030.json"),
        ("franciscan_mrf", "franciscan_99213.csv"),
        ("cha_mrf", "cha_45378.csv"),
    ],
)
def test_every_row_has_basename_provenance(tmp_path, sid, fx):
    _, _, rows = run(tmp_path, sid, fx)
    sha = MANIFEST["fixtures"][fx]["source_sha256"]
    for r in rows:
        assert "/" not in r.source_file and ".." not in r.source_file and "\\" not in r.source_file
        assert r.source_sha256 == sha
        assert r.source_date is not None
        assert re.fullmatch(rf"{sid}:{sha[:12]}:\d+", r.row_ref)


def test_every_row_renders_as_money_or_gap(tmp_path):
    """I1: a price cell is Money or a typed Gap, never empty."""
    for sid, fx in [
        ("brigham_mrf", "brigham_11102.csv"),
        ("bidmc_mrf", "bidmc_99213.json"),
        ("cha_mrf", "cha_45378.csv"),
        ("franciscan_mrf", "franciscan_99213.csv"),
    ]:
        _, _, rows = run(tmp_path, sid, fx)
        for r in rows:
            assert isinstance(r.to_cell(), (Money, NotPublished, PercentOnly))


# --- unit rules (synthetic inputs; the rules, not the data) -------------------------------------


def _leaf(**kw):
    base = {f: "" for f in stage.VALUE_FIELDS}
    base.update(payer_name="AETNA [1001]", plan_name="HB AMC AETNA HMO", setting="outpatient")
    base.update(kw)
    return base


def test_pct_only_derives_dollar_only_when_gross_is_present():
    r = normalize.resolve_amount(_leaf(negotiated_percentage="69.8", gross="598.00"), gross=598.0)
    assert r == (417.40, "derived_pct_x_gross", "pct_of_charges")
    r = normalize.resolve_amount(_leaf(negotiated_percentage="69.8"), gross=None)
    assert r == (None, "none", "pct_of_charges")
    r = normalize.resolve_amount(_leaf(negotiated_algorithm="APC Price"), gross=None)
    assert r == (None, "none", "algorithm")


@pytest.mark.parametrize(
    "rc, comp",
    [
        ("0761", "facility"),
        ("0983", "professional"),
        ("0960", "professional"),
        ("0989", "professional"),
        ("0510", "facility"),
        ("0990", "facility"),
    ],
)
def test_revenue_code_to_component(rc, comp):
    assert normalize.component_for([{"code": rc, "type": "RC"}], "", load_codes()) == (
        comp,
        "rev_code",
    )


def test_billing_class_typo_and_methodology_canonical():
    assert normalize.canonical_billing_class("facillity") == "facility"
    assert normalize.canonical_methodology("percent of total billed charges") == (
        "percent_of_total_billed_charges"
    )
    assert normalize.canonical_methodology("") == "unknown"
    assert normalize.canonical_methodology("APC rate") == "other"


@pytest.mark.parametrize("amt", ["0.01", "1", "1.00", "0"])
def test_placeholder_amounts(amt):
    assert normalize.is_placeholder(float(amt))
    assert not normalize.is_placeholder(4.44)
