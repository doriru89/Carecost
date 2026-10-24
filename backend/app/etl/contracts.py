"""Data contracts shared by the ETL, the quote engine and the UI.

* ``SourceKind``  - where a number came from (the hover text in the UI keys off this).
* ``Provenance``  - source file *basename*, sha256, source date, method, row ref.
* ``Money``       - a dollar amount (``low == high`` for a point value) + provenance.
* ``Gap``         - closed discriminated union of the five reasons a number is missing.
* ``Cell``        - ``Money | Gap``: the only thing allowed to fill a price cell.
* ``RateRow``     - one negotiated-rate fact. Never collapsed: natural key + ``nk_ordinal``.

``python -m app.etl.contracts [out_dir]`` writes the JSON Schemas to ``contracts/``.
A test fails when the committed schemas drift from these models.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


class StrEnum(str, Enum):
    """``enum.StrEnum`` is 3.11+; this keeps the JSON values plain strings."""

    def __str__(self) -> str:
        return str(self.value)


class SourceKind(StrEnum):
    hospital_mrf = "hospital_mrf"
    insurer_tic = "insurer_tic"
    medicare_pfs = "medicare_pfs"
    medicare_opps = "medicare_opps"
    medicare_asc = "medicare_asc"
    masshealth_fs = "masshealth_fs"
    clinic_posted = "clinic_posted"
    chia_rp = "chia_rp"
    estimate = "estimate"
    ai_potential = "ai_potential"


class Method(StrEnum):
    """How the number in a ``Money`` was obtained."""

    stated = "stated"  # copied as published
    derived_pct_x_gross = "derived_pct_x_gross"  # negotiated % x the same line's gross charge
    computed_fee_schedule = "computed_fee_schedule"  # e.g. RVU x GPCI x CF (Medicare PFS)
    estimate_medicare_multiple = "estimate_medicare_multiple"  # ladder step 6
    ai_drafted = "ai_drafted"  # offline AI draft reviewed by Austin (never in totals)


class PriceBasis(StrEnum):
    """What the amount *is* (as opposed to how we got it)."""

    negotiated = "negotiated"
    gross = "gross"
    discounted_cash = "discounted_cash"
    min_negotiated = "min_negotiated"
    max_negotiated = "max_negotiated"
    median_allowed = "median_allowed"
    fee_schedule = "fee_schedule"
    posted_self_pay = "posted_self_pay"
    estimate = "estimate"


class DollarBasis(StrEnum):
    """How the contract defines the price (CMS v3 standard_charge fields)."""

    dollar = "dollar"
    pct_of_charges = "pct_of_charges"
    algorithm = "algorithm"
    none = "none"


class AmountMethod(StrEnum):
    stated = "stated"
    derived_pct_x_gross = "derived_pct_x_gross"
    none = "none"


class Setting(StrEnum):
    inpatient = "inpatient"
    outpatient = "outpatient"
    both = "both"
    unknown = "unknown"


class BillingClass(StrEnum):
    facility = "facility"
    professional = "professional"
    unknown = "unknown"


class Component(StrEnum):
    """Which part of the bill a line is. From the revenue code (096x-098x = professional),
    else the file's billing_class, else unknown (CHA: no RC and no billing_class)."""

    facility = "facility"
    professional = "professional"
    unknown = "unknown"


class Methodology(StrEnum):
    fee_schedule = "fee_schedule"
    percent_of_total_billed_charges = "percent_of_total_billed_charges"
    per_diem = "per_diem"
    case_rate = "case_rate"
    other = "other"
    unknown = "unknown"


class LineOfBusiness(StrEnum):
    commercial = "commercial"
    connector = "connector"  # MA Health Connector / QHP / ConnectorCare
    medicare = "medicare"  # traditional Medicare (FFS)
    medicare_advantage = "medicare_advantage"
    medicaid = "medicaid"  # MassHealth FFS
    medicaid_managed = "medicaid_managed"  # MassHealth ACO / MCO
    dual = "dual"  # SCO / One Care / PACE
    other_government = "other_government"  # Tricare, VA, HSN, corrections
    unknown = "unknown"


_BASENAME_RE = re.compile(r"^[^/\\]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _check_basename(v: str) -> str:
    if not v or not _BASENAME_RE.match(v) or v in (".", "..") or v.startswith(".."):
        raise ValueError(f"source_file must be a bare basename, got {v!r}")
    return v


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: SourceKind
    source_file: str = Field(description="Basename only; never an absolute or relative path.")
    source_sha256: str
    source_date: date | None = Field(description="The file's own last_updated_on (ISO).")
    method: Method
    row_ref: str = Field(description="<source_id>:<sha256[:12]>:<staged row ordinal>")

    @field_validator("source_file")
    @classmethod
    def _v_file(cls, v: str) -> str:
        return _check_basename(v)

    @field_validator("source_sha256")
    @classmethod
    def _v_sha(cls, v: str) -> str:
        if not _SHA_RE.match(v):
            raise ValueError("source_sha256 must be 64 lowercase hex chars")
        return v


class Money(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["money"] = "money"
    low: float = Field(ge=0)
    high: float = Field(ge=0)
    basis: PriceBasis
    prov: Provenance

    @model_validator(mode="after")
    def _low_le_high(self) -> Money:
        if self.low > self.high:
            raise ValueError("Money.low must be <= Money.high")
        return self

    @classmethod
    def point(cls, amount: float, *, basis: PriceBasis | str, prov: Provenance) -> Money:
        return cls(low=amount, high=amount, basis=PriceBasis(basis), prov=prov)


class GapKind(StrEnum):
    not_published = "not_published"
    not_loaded = "not_loaded"
    no_source = "no_source"
    percent_only = "percent_only"
    conflict = "conflict"


class _GapBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NotPublished(_GapBase):
    """The source type exists but this provider did not list this item (in dollars)."""

    kind: Literal["not_published"] = "not_published"
    what: str
    ask: str


class NotLoaded(_GapBase):
    """A source exists and we have not imported it yet (e.g. UHC TiC)."""

    kind: Literal["not_loaded"] = "not_loaded"
    what: str
    eta: str | None = None


class NoSource(_GapBase):
    """No public source exists at all (e.g. self-pay physician fee)."""

    kind: Literal["no_source"] = "no_source"
    what: str
    ask: str


class PercentOnly(_GapBase):
    """Only 'X% of charges' is published and the base charge is not."""

    kind: Literal["percent_only"] = "percent_only"
    pct: float = Field(ge=0)
    of: str


class Conflict(_GapBase):
    """Two sources disagree; both numbers are shown."""

    kind: Literal["conflict"] = "conflict"
    a: Money
    b: Money


Gap = Annotated[
    Union[NotPublished, NotLoaded, NoSource, PercentOnly, Conflict], Field(discriminator="kind")
]
Cell = Annotated[
    Union[Money, NotPublished, NotLoaded, NoSource, PercentOnly, Conflict],
    Field(discriminator="kind"),
]

# One fixed glossary key (copy + "what to do next") per Gap kind. AI may not add kinds or edit copy.
GAP_GLOSSARY: dict[str, str] = {
    "not_published": "gap.not_published",
    "not_loaded": "gap.not_loaded",
    "no_source": "gap.no_source",
    "percent_only": "gap.percent_only",
    "conflict": "gap.conflict",
}


class RateRow(BaseModel):
    """One negotiated-rate fact from a hospital MRF line (or later, a TiC price).

    Natural key (never collapsed): entity_id x code_type x code x modifiers x billing_class x
    setting x component x rev_code x payer_raw x plan_raw x methodology x cdm_code x description,
    then ``nk_ordinal`` (0, 1, 2 ... in file order) separates rows that the source itself
    leaves identical (``ambiguous_multi_rate``).
    """

    model_config = ConfigDict(extra="forbid")

    row_id: str = Field(description="<nk_hash>:<nk_ordinal>; unique per build")
    nk_hash: str
    nk_ordinal: int = Field(ge=0)

    source_id: str
    source_kind: SourceKind
    entity_id: str
    row_kind: Literal["payer_rate", "chargemaster"] = Field(
        description="payer_rate: payer-specific line; chargemaster: gross/cash line with no payer"
    )
    billing_npis: str = Field(description="'|'-joined type_2_npi values as read from the file")

    code_type: str
    code: str
    modifiers: str = Field(description="sorted, '|'-joined; '' when none")
    rev_code: str
    cdm_code: str
    description: str

    setting: Setting
    billing_class: BillingClass
    component: Component
    component_rule: Literal["rev_code", "billing_class", "none"]

    payer_raw: str
    plan_raw: str
    payer_id: str | None
    line_of_business: LineOfBusiness
    product: str = Field(
        description="HMO / PPO / POS / INDEMNITY / ... parsed from the plan, or ''"
    )

    methodology: Methodology
    methodology_raw: str
    dollar_basis: DollarBasis
    negotiated_dollar: float | None
    negotiated_pct: float | None
    negotiated_algorithm: str
    amount: float | None = Field(description="Resolved dollar amount, see amount_method")
    amount_method: AmountMethod

    gross: float | None
    gross_rule: Literal["same_row", "joined_code_setting", "ambiguous", "none"]
    discounted_cash: float | None
    min_negotiated: float | None
    max_negotiated: float | None
    median_amount: float | None
    p10_amount: float | None
    p90_amount: float | None
    allowed_count: str

    above_gross: bool
    ambiguous_multi_rate: bool
    payer_plan_mismatch: bool
    excluded: bool = Field(description="True -> never part of a consumer price")
    exclude_reason: str = Field(description="'' or one of payer_aliases.yaml exclusion reasons")

    additional_generic_notes: str
    additional_payer_notes: str

    source_file: str
    source_sha256: str
    source_date: date | None
    stage_row: int = Field(ge=0)
    row_ref: str

    @field_validator("source_file")
    @classmethod
    def _v_file(cls, v: str) -> str:
        return _check_basename(v)

    def provenance(self) -> Provenance:
        method = (
            Method.derived_pct_x_gross
            if self.amount_method == AmountMethod.derived_pct_x_gross
            else Method.stated
        )
        return Provenance(
            source_kind=self.source_kind,
            source_file=self.source_file,
            source_sha256=self.source_sha256,
            source_date=self.source_date,
            method=method,
            row_ref=self.row_ref,
        )

    def to_cell(self) -> Money | NotPublished | PercentOnly:
        """Every rate row renders as Money or a typed Gap, never as None."""
        if self.row_kind == "chargemaster":
            if self.discounted_cash is not None:
                return Money.point(
                    self.discounted_cash, basis=PriceBasis.discounted_cash, prov=self.provenance()
                )
            if self.gross is not None:
                return Money.point(self.gross, basis=PriceBasis.gross, prov=self.provenance())
            return NotPublished(
                what="a self-pay price for this line",
                ask="Ask the hospital for its discounted cash price or a Good Faith Estimate.",
            )
        if self.amount is not None:
            return Money.point(self.amount, basis=PriceBasis.negotiated, prov=self.provenance())
        if self.negotiated_pct is not None:
            return PercentOnly(pct=self.negotiated_pct, of="gross charges")
        return NotPublished(
            what="a dollar amount (the contract is a formula)",
            ask="Ask the hospital billing office for a Good Faith Estimate.",
        )


SCHEMA_MODELS: dict[str, Any] = {
    "source_kind.schema.json": SourceKind,
    "provenance.schema.json": Provenance,
    "money.schema.json": Money,
    "gap.schema.json": Gap,
    "cell.schema.json": Cell,
    "rate_row.schema.json": RateRow,
}


def json_schemas() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, model in SCHEMA_MODELS.items():
        schema = TypeAdapter(model).json_schema()
        schema["$id"] = f"https://carecost.local/contracts/{name}"
        out[name] = schema
    return out


def write_schemas(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in json_schemas().items():
        p = out_dir / name
        p.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        written.append(p)
    return written


if __name__ == "__main__":  # pragma: no cover
    default = Path(__file__).resolve().parents[3] / "contracts"
    for p in write_schemas(Path(sys.argv[1]) if len(sys.argv) > 1 else default):
        print(p)
