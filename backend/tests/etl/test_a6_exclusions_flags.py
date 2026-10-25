"""A6: O's outlier-audit fixes at the source (exclusions, TiC flags), the new care-path areas,
per-site service areas and MGB ASO's product. Examples are the audit's own source rows."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from app.etl.config import CONFIG_DIR, load_codes
from app.etl.normalize import source_exclusion
from app.etl.tic import flags as flags_mod
from app.etl.tic.networks import get_network
from app.etl.tic.normalize import TIC_RATE_ROW_SCHEMA
from app.sites import build as sites_build

REPO = CONFIG_DIR.parents[1]


def _hrow(**kw):
    base = dict(row_kind="payer_rate", description="", methodology="fee_schedule",
                methodology_raw="fee schedule", plan_raw="", amount=100.0, gross=200.0,
                gross_rule="same_row", amount_method="stated", additional_generic_notes="",
                additional_payer_notes="")  # fmt: skip
    return {**base, **kw}


# ------------------------------------------------------------------ hospital exclusions


def test_not_dollars_cha_colonoscopy():
    # CHA 2efdf1cef584 line 187058: $5.04 facility fee on a $3,510.55 colonoscopy
    assert source_exclusion(_hrow(amount=5.04, gross=3510.55)) == "not_dollars"
    assert source_exclusion(_hrow(amount=35.11, gross=3510.55)) == ""  # 1.0001% is a price
    # a % row turned into dollars is not a "stated dollar"; a joined gross is not the row's own
    assert source_exclusion(_hrow(amount=5.04, gross=3510.55, amount_method="derived_pct_x_gross")) == ""
    assert source_exclusion(_hrow(amount=5.04, gross=3510.55, gross_rule="joined_code_setting")) == ""


def test_chargemaster_as_rate_needs_both_tests():
    # Tufts d16771049bc4 line 1210827: MEDICARE 608.00 == gross, "No contract line matched"
    hit = _hrow(amount=608.0, gross=608.0, methodology="other", methodology_raw="other",
                additional_generic_notes="No contract line matched")  # fmt: skip
    assert source_exclusion(hit) == "chargemaster_as_rate"
    assert source_exclusion({**hit, "additional_generic_notes": ""}) == ""  # CHA: equal, no text
    assert source_exclusion({**hit, "amount": 425.6}) == ""


@pytest.mark.parametrize(
    "kw",
    [
        {"description": "HC PER DIEM PAIN TREATMENT"},  # Children's, carries CPT 99215
        {"methodology": "case_rate", "methodology_raw": "case rate"},  # BMC / CHA CSV rows
        {"methodology": "per_diem", "methodology_raw": "per diem"},
        {"description": "OBSERVATION HALF-DAY"},
    ],
)
def test_per_diem_half_day_case_rate_are_not_line_prices(kw):
    assert source_exclusion(_hrow(**kw)) == "per_diem_or_case_rate"


def test_chargemaster_rows_are_never_source_excluded():
    assert source_exclusion(_hrow(row_kind="chargemaster", amount=None)) == ""


# ------------------------------------------------------------------ TiC flags


def _tic(rid, code, amount, *, tin="111111111", grp=1, bc="professional", pos="11", tt="ein"):
    r = {f.name: None for f in TIC_RATE_ROW_SCHEMA}
    r.update(row_id=rid, code=code, modifiers="", billing_class=bc, amount=amount,
             tic_tin_value=tin, tic_tin_type=tt, tic_provider_group_id=grp, tic_group_ordinal=0,
             tic_rate_group_ordinal=0, tic_service_codes=pos, tic_negotiated_type="negotiated",
             excluded=False, ambiguous_multi_rate=False)  # fmt: skip
    return r


def _run(tmp: Path, rows, groups) -> Path:
    pq.write_table(pa.Table.from_pylist(rows, TIC_RATE_ROW_SCHEMA), tmp / "rate_row.parquet")
    g = [{"provider_group_id": k, "group_ordinal": 0, "npis": v} for k, v in groups.items()]
    pq.write_table(pa.Table.from_pylist(g), tmp / "groups.parquet")
    return tmp


UNITS = {"00811": 4, "00812": 3, "00813": 5, "00731": 5}


def test_anesthesia_per_unit_mgb_synergy(tmp_path):
    # MGB INN_COMMERCIAL_HMO in_network[572]: "20.9800" on 00811, 00812 and 00813
    rows = [_tic(f"a{c}", c, 20.98) for c in ("00811", "00812", "00813")]
    rows += [_tic("b1", "00811", 900.0, tin="222222222"), _tic("b2", "00731", 900.0, tin="222222222")]
    d = _run(tmp_path, rows, {1: ["1111111112"]})
    got, counts, _ = flags_mod.compute(d, UNITS, {})
    # 00811 (4) and 00731 (5) differ too, so TIN 2's one amount on both is per unit as well
    assert {k for k, v in got.items() if "anesthesia_per_unit" in v} == {
        "a00811", "a00812", "a00813", "b1", "b2"}  # fmt: skip
    got2, _, _ = flags_mod.compute(d, {**UNITS, "00731": 4}, {})
    assert "b1" not in got2  # same base units -> could be one case price: not flagged


def test_institutional_on_physician_npi(tmp_path):
    rows = [
        _tic("phys", "45378", 81.06, grp=1, bc="facility"),  # one NPI, NPPES: a person
        _tic("hosp", "45378", 4136.0, grp=2, bc="facility", tin="333333333"),  # one org NPI
        _tic("pro", "45378", 141.0, grp=1),  # professional rows are never flagged
    ]
    d = _run(tmp_path, rows, {1: ["1234567893"], 2: ["1306849450"]})
    types = {"1234567893": {"type": "NPI-1"}, "1306849450": {"type": "NPI-2", "taxonomy": "282N00000X",
                                                         "physician_group": False}}  # fmt: skip
    got, counts, singles = flags_mod.compute(d, UNITS, types)
    assert got == {"phys": {"institutional_on_physician_npi"}}
    assert singles == {"1234567893", "1306849450"}


def test_same_npi_same_pos_duplicate_prices(tmp_path):
    # Aetna PPO 11102 "Metrowest Physician Services": $254.73 and $123.69, same NPIs, same POS
    rows = [_tic("r146", "11102", 254.73, grp=146), _tic("r147", "11102", 123.69, grp=147),
            _tic("other_pos", "11102", 99.0, grp=148, pos="22"),
            _tic("same_amt", "11104", 50.0, grp=146), _tic("same_amt2", "11104", 50.0, grp=147)]  # fmt: skip
    npis = ["1234567893", "1306849450"]
    d = _run(tmp_path, rows, {146: npis, 147: list(reversed(npis)), 148: npis})
    st = flags_mod.apply(d, UNITS, {})
    assert flags_mod.load_flags(d) == {"r146": ["same_npi_pos_multi_rate"],
                                       "r147": ["same_npi_pos_multi_rate"]}  # fmt: skip
    amb = {r["row_id"]: r["ambiguous_multi_rate"] for r in pq.read_table(d / "rate_row.parquet").to_pylist()}
    assert amb == {"r146": True, "r147": True, "other_pos": False, "same_amt": False, "same_amt2": False}
    assert st["by_flag"]["same_npi_pos_multi_rate"] == 2


def test_committed_npi_types_are_typed_from_nppes():
    doc = yaml.safe_load((CONFIG_DIR / flags_mod.NPI_TYPES_FILE).read_text())
    assert "npiregistry.cms.hhs.gov" in doc["source"] and doc["npis"]
    for n, rec in doc["npis"].items():
        assert len(n) == 10 and rec["type"] in ("NPI-1", "NPI-2", "not_found")


# ------------------------------------------------------------------ config


def test_mgb_aso_has_a_product():
    assert get_network("tic_mgb_hp_mgb_aso").product == "PPO"


def test_new_path_areas_and_lab_codes():
    cfg = yaml.safe_load((CONFIG_DIR / "codes.yaml").read_text())
    assert cfg["path_area_domains"]["gi_abdomen"] == "gi"
    assert cfg["path_area_domains"]["skin_rash"] == "derm"
    codes = load_codes()
    for c in ("99203 99213 99204 81003 81025 85025 80053 76700 76705 74177 87220 11104 11102 "
              "88305").split():  # fmt: skip
        assert c in codes.codes and codes.description(c)


# ------------------------------------------------------------------ sites: per-site areas


@pytest.mark.parametrize(
    "name,areas",
    [
        ("BOSTON DERMATOLOGY AND LASER CENTER LLC", ["skin"]),
        ("Mass General Brigham Orthopedics and Sports Medicine Clinic", ["ortho"]),
        ("NEEDHAM GASTROENTEROLOGY ASSOCIATES PC", ["gi"]),
        ("ATRIUS HEALTH INC", []),  # a multi-specialty group: the CMS counts decide
    ],
)
def test_name_areas(name, areas):
    assert sites_build.name_areas(name) == areas


def test_registry_areas_follow_the_site_not_the_address():
    sites = {s["id"]: s for s in yaml.safe_load((REPO / "data/sites/sites.yaml").read_text())["sites"]}
    assert sites["boston_dermatology_and_laser_center_llc_boston"]["service_areas"] == ["skin"]
    nebh = sites["new_england_baptist_surgery_center_llc_dedham"]
    assert nebh["service_areas"] == ["ortho"]
    assert "endoscopy" not in {o["service"] for o in nebh["offered"]}
    # no skin-only site is admitted to an orthopedic path
    for s in sites.values():
        if "DERMATOLOG" in s["name"].upper():
            assert "ortho" not in s["service_areas"], s["id"]
