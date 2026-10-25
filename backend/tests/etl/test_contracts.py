"""Contracts: SourceKind, Money, Gap, Provenance, RateRow and the exported JSON Schema."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from app.etl import contracts as c

REPO = Path(__file__).resolve().parents[3]


def _prov(**kw):
    base = dict(
        source_id="brigham_mrf",
        source_kind="hospital_mrf",
        source_file="042312909_Brigham-and-Womens-Hospital_StandardCharges.zip",
        source_sha256="a" * 64,
        source_date=date(2026, 3, 27),
        method="stated",
        row_ref="brigham_mrf:aaaaaaaaaaaa:17",
    )
    base.update(kw)
    return c.Provenance(**base)


def test_source_kind_enum_is_exactly_the_plan_list():
    assert [k.value for k in c.SourceKind] == [
        "hospital_mrf",
        "insurer_tic",
        "medicare_pfs",
        "medicare_opps",
        "medicare_asc",
        "masshealth_fs",
        "clinic_posted",
        "chia_rp",
    ]
    # AI never produces dollars: no AI source kind and no AI method exist (P5 / review F1)
    assert "ai_drafted" not in {m.value for m in c.Method}


def test_provenance_row_ref_must_name_its_own_file():
    """The chip is derived from prov.source_id, so the row_ref must cite that same file."""
    _prov()
    with pytest.raises(ValidationError, match="must start with"):
        _prov(row_ref="mtauburn_mrf:aaaaaaaaaaaa:17")  # another hospital's row
    with pytest.raises(ValidationError, match="must start with"):
        _prov(row_ref="brigham_mrf:bbbbbbbbbbbb:17")  # another version of the file


def test_placeholder_sha_needs_the_fixture_context():
    zero = "0" * 64
    with pytest.raises(ValidationError, match="placeholder"):
        _prov(source_sha256=zero, row_ref="brigham_mrf:000000000000:1")
    c.Provenance.model_validate(
        dict(
            source_id="brigham_mrf",
            source_kind="hospital_mrf",
            source_file="x.zip",
            source_sha256=zero,
            source_date=None,
            method="stated",
            row_ref="brigham_mrf:000000000000:1",
        ),
        context={"allow_placeholders": True},
    )


@pytest.mark.parametrize(
    "bad",
    [
        "/Users/austin/carecost/data/raw/x.zip",
        "../data/raw/x.zip",
        "raw/x.zip",
        "C:\\raw\\x.zip",
        "",
    ],
)
def test_provenance_rejects_anything_but_a_basename(bad):
    with pytest.raises(ValidationError):
        _prov(source_file=bad)


def test_provenance_rejects_bad_sha_and_unknown_method():
    with pytest.raises(ValidationError):
        _prov(source_sha256="xyz")
    with pytest.raises(ValidationError):
        _prov(method="vibes")


def test_money_low_le_high_and_point_constructor():
    m = c.Money.point(532.57, basis="negotiated", prov=_prov())
    assert m.kind == "money" and m.low == m.high == 532.57
    with pytest.raises(ValidationError):
        c.Money(low=10, high=5, basis="negotiated", prov=_prov())
    with pytest.raises(ValidationError):
        c.Money(low=-1, high=5, basis="negotiated", prov=_prov())


def test_gap_union_is_closed_and_discriminated():
    ta = TypeAdapter(c.Gap)
    assert {k.value for k in c.GapKind} == {
        "not_published",
        "not_loaded",
        "no_source",
        "percent_only",
        "conflict",
    }
    searched = {"source_id": "franciscan_mrf", "source_sha256": "f" * 64}
    g = ta.validate_python(
        {"kind": "percent_only", "pct": 69.8, "of": "gross charges", "searched": searched}
    )
    assert isinstance(g, c.PercentOnly)
    with pytest.raises(ValidationError):
        ta.validate_python({"kind": "made_up", "what": "x"})
    # a "not published" claim must say which file was searched
    with pytest.raises(ValidationError, match="searched"):
        ta.validate_python({"kind": "not_published", "what": "x", "ask": "y"})


def test_every_gap_kind_has_fixed_glossary_copy():
    assert set(c.GAP_GLOSSARY) == {k.value for k in c.GapKind}
    assert all(v.startswith("gap.") for v in c.GAP_GLOSSARY.values())


def test_cell_is_money_or_gap_only():
    ta = TypeAdapter(c.Cell)
    m = c.Money.point(1.0, basis="gross", prov=_prov())
    assert isinstance(ta.validate_python(m.model_dump()), c.Money)
    conflict = {"kind": "conflict", "a": m.model_dump(), "b": m.model_dump()}
    assert isinstance(ta.validate_python(conflict), c.Conflict)


def test_exported_schemas_match_committed_contracts():
    """contracts/*.schema.json are generated; drift fails CI."""
    from app.api_contracts import SPECS as API_CONTRACTS
    from app.care_paths.schema_export import CONTRACT_FILE as CARE_PATH_CONTRACT

    generated = c.json_schemas()
    committed_dir = REPO / "contracts"
    # Every committed schema has exactly one generator: the ETL contracts, the care-path exporter
    # or the wave-2 API contracts (app.api_contracts).
    other_generators = {CARE_PATH_CONTRACT.name, *API_CONTRACTS}
    assert set(generated) | other_generators == {
        p.name for p in committed_dir.glob("*.schema.json")
    }
    for name, schema in generated.items():
        committed = json.loads((committed_dir / name).read_text())
        assert committed == schema, f"{name} is stale: run python -m app.etl.contracts"


def test_rate_row_schema_has_natural_key_and_provenance_fields():
    fields = set(c.RateRow.model_fields)
    nk = {
        "entity_id",
        "code_type",
        "code",
        "modifiers",
        "billing_class",
        "setting",
        "component",
        "payer_raw",
        "plan_raw",
        "methodology",
        "nk_ordinal",
    }
    prov = {"source_file", "source_sha256", "source_date", "row_ref"}
    assert nk <= fields and prov <= fields
