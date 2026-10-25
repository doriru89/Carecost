"""Quote API + catalog contracts (wave 2.0). Contract models ONLY; the engine lives elsewhere.

Reuses ``Money`` / ``Gap`` / ``Cell`` / ``Provenance`` / ``SourceKind`` from ``app.etl.contracts``
(never redefined) and ``Freshness`` / ``BookingOption`` / ``PortalLink`` / ``Hours`` from
``app.sites.contracts``.

Request: how the person pays + a care path id (from chat) OR a manual list of codes (D3, skip AI),
optional site filter. No location (distance is computed in the browser) and no personal data.

Response: per site, a summary + a receipt. Receipt lines sit in one of four display tiers
(D8 gradient, not numbered sections): certain -> likely -> possible -> not_in_public_data.
Every price cell is a ``Cell`` (Money or a typed Gap). AI-suggested lines never count in a total.

Invariants are enforced here (model validators), so the engine cannot emit a receipt that breaks
them and the frontend can trust the shape:

* ``tier == not_in_public_data``  <=>  the cell is a "no number" Gap (not_published / not_loaded /
  no_source). percent_only and conflict carry information and stay in their likelihood tier.
* ``in_total`` only for certain/likely, offered, Money, non-AI, one-off lines whose doctor-fee
  rung (if any) is 1-6. Rungs 7-8 are reference only.
* Doctor-fee rung 6 (estimate) must carry its multiple; ``by_npi`` (D6) needs >= 2 distinct prices.
* ``Totals.likely`` is the exact sum of the lines listed in it; its ``includes_*`` flags and line
  counts are derived from those lines.
* Payment <-> price type (``PRICE_MATRIX``): a BCBS receipt carries only BCBS negotiated rates
  (or a rung-6 estimate), Medicare only Medicare, cash only cash prices. A gross charge is never a
  line price; it may only appear as ``list_price``, which is never summed.
* Sources are stored once per response (``QuoteResponse.sources``). A number's chip is its
  ``prov.source_id``; freshness is computed on ``as_of`` for each request.
* I7: sites are ordered by completeness first (fewest missing certain/likely lines), then price,
  so missing data never makes a site look cheaper.

``python -m app.api_contracts`` regenerates ``contracts/quote_api.schema.json`` and
``contracts/catalog.schema.json``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.etl.contracts import (
    Cell,
    Conflict,
    Method,
    Money,
    NotPublished,
    PercentOnly,
    PriceBasis,
    SourceKind,
    placeholders_allowed,
)
from app.sites.contracts import (
    CODE_RE,
    ID_RE,
    BillingType,
    BookingOption,
    Coordinates,
    Freshness,
    Hours,
    PortalLink,
    ServiceArea,
    SiteType,
    check_npi,
)

PAYER_ID_RE = r"^[A-Z][A-Z0-9_]*$"  # data/etl/payer_aliases.yaml `payers:` keys (BCBS_MA ...)
PATH_ID_RE = r"^[a-z0-9_]+_v[0-9]+$"  # care_paths.CarePath.id
QUESTION_ID_RE = r"^Q[0-9]+$"
ANSWER_RE = r"^[a-z0-9_]{1,40}$"

# Request size bounds (security review F4: a 20 MB `answers` validated before).
MAX_ANSWER_KEYS = 20
MAX_VALUES_PER_ANSWER = 8
MAX_SERVICE_CODES = 40
MAX_SITE_IDS = 500

Answers = Annotated[
    dict[str, Annotated[list[str], Field(max_length=MAX_VALUES_PER_ANSWER)]],
    Field(max_length=MAX_ANSWER_KEYS),
]


def check_answers(answers: dict[str, list[str]]) -> None:
    for q, vals in answers.items():
        if not re.match(QUESTION_ID_RE, q) or not all(re.match(ANSWER_RE, v) for v in vals):
            raise ValueError(f"answers must be question ids -> answer values, got {q!r}")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- payment


class InsurancePayment(_Strict):
    kind: Literal["insurance"]
    payer_id: str = Field(pattern=PAYER_ID_RE, description="payer_aliases.yaml id, e.g. BCBS_MA")
    product: str = Field(
        pattern=r"^[A-Z]+$", description="payer_aliases.yaml `products`: HMO, PPO, POS, EPO ..."
    )
    network: str | None = Field(
        pattern=ID_RE,
        description="Optional named network inside the product (TiC network id), e.g. hmo_blue",
    )


class MedicarePayment(_Strict):
    """Traditional Medicare (FFS). Medicare Advantage is an InsurancePayment (e.g. HUMANA)."""

    kind: Literal["medicare"]


class MassHealthPayment(_Strict):
    """MassHealth fee-for-service rates. ACO / MCO plans may pay differently (shown as a note)."""

    kind: Literal["masshealth"]


class CashPayment(_Strict):
    kind: Literal["cash"]


Payment = Annotated[
    Union[InsurancePayment, MedicarePayment, MassHealthPayment, CashPayment],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- request


PickedBy = Literal["person", "assistant"]
"""Who chose the services: the person (D3 manual picker, or a care path) or the assistant
(P5: the LLM pointed at catalog services). Assistant picks are shown, labelled, never summed."""


class QuoteRequest(_Strict):
    payment: Payment
    care_path_id: str | None = Field(pattern=PATH_ID_RE)
    answers: Answers = Field(
        description="Chip answers keyed by questions.yaml id (Q14 -> referral layer, tier "
        "modifiers). Ids and values only; never free text.",
    )
    service_codes: list[str] = Field(
        max_length=MAX_SERVICE_CODES,
        description="D3 manual picker: CPT/HCPCS codes from the catalog",
    )
    picked_by: PickedBy
    site_ids: list[str] | None = Field(
        max_length=MAX_SITE_IDS,
        description="Only these sites; None = every site that offers the services",
    )

    @model_validator(mode="after")
    def _one_of(self) -> QuoteRequest:
        if (self.care_path_id is None) == (not self.service_codes):
            raise ValueError("give exactly one of care_path_id or service_codes")
        if self.picked_by == "assistant" and self.care_path_id is not None:
            raise ValueError("assistant picks are catalog services, never a care path quote")
        for c in self.service_codes:
            if not re.match(CODE_RE, c):
                raise ValueError(f"bad service code {c!r}")
        check_answers(self.answers)
        for s in self.site_ids or []:
            if not re.match(ID_RE, s):
                raise ValueError(f"bad site id {s!r}")
        return self


# --------------------------------------------------------------------------- receipt line parts


CertaintyTier = Literal["certain", "likely", "possible", "not_in_public_data"]
"""D8 display gradient: solid -> lighter -> faint + dashed -> warning colour."""

Likelihood = Literal["certain", "likely", "possible", "rare"]
"""The care path's likelihood_tier for the step (care_paths.models.Tier); rare displays as possible."""

BillComponent = Literal["facility", "professional", "drug", "supply", "unknown"]

NO_NUMBER_GAPS = ("not_published", "not_loaded", "no_source")

LadderExplanation = Literal[
    "fee.rung_1_npi",
    "fee.rung_2_group",
    "fee.rung_3_hospital_file",
    "fee.rung_4_masshealth",
    "fee.rung_5_medicare",
    "fee.rung_6_estimate",
    "fee.rung_7_medicare_reference",
    "fee.rung_8_chia_badge",
    "fee.self_pay_no_source",
]
"""One fixed copy key per doctor-fee rung (plan §2.4). Copy lives with the glossary; AI cannot edit it."""

RUNG_EXPLANATION: dict[int, str] = {
    1: "fee.rung_1_npi",
    2: "fee.rung_2_group",
    3: "fee.rung_3_hospital_file",
    4: "fee.rung_4_masshealth",
    5: "fee.rung_5_medicare",
    6: "fee.rung_6_estimate",
    7: "fee.rung_7_medicare_reference",
    8: "fee.rung_8_chia_badge",
}

ExcludedReason = Literal[
    "possible_tier",
    "ai_suggested",
    "no_dollar_amount",  # cell is a Gap (incl. percent_only)
    "conflict",  # two sources disagree; both shown, neither summed
    "not_offered_here",
    "repeats",  # per visit / per 15 minutes: count is unknown
    "reference_only",  # doctor-fee rung 7 or 8
]

TierBasis = Literal["guideline", "plan_rule", "our_judgment", "picked"]
"""P11: what the line's likelihood rests on, so the gradient does not look like data.
guideline: a guideline rating (ACR / AAOS / USPSTF / ACG). plan_rule: an insurance rule (HMO
referral). our_judgment: our own reading (the visit itself, a step implied by another).
picked: no care path; the person or the assistant picked the service."""

GUIDELINE_RATINGS = frozenset(
    {
        "UA",
        "MBA",
        "UNA",
        "aaos_strong",
        "aaos_moderate",
        "aaos_limited",
        "aaos_consensus",
        "uspstf_A",
        "uspstf_B",
        "uspstf_C",
        "uspstf_D",
        "uspstf_I",
        "acg_strong",
        "acg_conditional",
    }
)


def tier_basis_for_rating(rating: str) -> TierBasis:
    """care_paths Step.appropriateness.rating -> TierBasis (the engine and the tests use this)."""
    if rating in GUIDELINE_RATINGS:
        return "guideline"
    if rating == "plan_rule":
        return "plan_rule"
    if rating in ("standard_of_care", "implied_by_parent"):
        return "our_judgment"
    raise ValueError(f"unknown appropriateness rating {rating!r}")


class SourceInfo(_Strict):
    """One source, stored once per response (P2). Every number points at it by
    ``prov.source_id``; that is its chip. The chip copy key is ``source.<source_kind>``."""

    source_kind: SourceKind
    publisher: str = Field(
        description="Who published it, e.g. 'Mount Auburn Hospital', 'BCBS MA', 'CMS'"
    )
    freshness: Freshness = Field(
        description="Both sides, computed on the response's as_of: (a) publisher late to "
        "refresh, (b) stale on our side"
    )


def _check_sources(sources: dict[str, SourceInfo], as_of: date) -> None:
    for sid, info in sources.items():
        if not re.match(ID_RE, sid):
            raise ValueError(f"bad source id {sid!r}")
        if info.freshness != info.freshness.at(as_of):
            raise ValueError(f"source {sid}: freshness is not what its inputs give on {as_of}")


class NpiPrice(_Strict):
    npi: str = Field(pattern=r"^[0-9]{10}$")

    @field_validator("npi")
    @classmethod
    def _npi(cls, v: str, info: ValidationInfo) -> str:
        return check_npi(v, placeholders_ok=placeholders_allowed(info))

    display_name: str | None = Field(
        default=None, description="Public NPPES name; None when only an NPI block is known"
    )
    money: Money


class Multiple(_Strict):
    """Rung 6: Medicare x the same group's own typical multiple (>= 5 matched codes, D5)."""

    low: float = Field(gt=0)
    high: float = Field(gt=0)
    n_codes: int = Field(ge=5)
    payer_id: str = Field(pattern=PAYER_ID_RE)


class ChiaBadge(_Strict):
    """Rung 8: ordering only, no dollars (CHIA relative price)."""

    payer_id: str = Field(pattern=PAYER_ID_RE)
    band: Literal["top_quarter", "above_median", "below_median", "bottom_quarter"]
    report_year: int


class DoctorFee(_Strict):
    """Present on professional lines priced by the 8-rung ladder (plan §2.4, D5, D6)."""

    rung: int | None = Field(ge=1, le=8, description="None only for self-pay (no public source)")
    explanation_key: LadderExplanation
    group_name: str | None = Field(default=None, description="Physician group, e.g. 'MGPO'")
    group_tin: str | None = Field(default=None, pattern=r"^[0-9]{2}-[0-9]{7}$")
    npi_count: int | None = Field(default=None, ge=1)
    multiple: Multiple | None = None
    chia_badge: ChiaBadge | None = None
    by_npi: list[NpiPrice] | None = Field(
        default=None, description="D6: per doctor when the NPI is known and prices differ"
    )

    @model_validator(mode="after")
    def _rules(self) -> DoctorFee:
        if self.rung is None:
            if self.explanation_key != "fee.self_pay_no_source":
                raise ValueError("rung None is only for fee.self_pay_no_source")
        elif self.explanation_key != RUNG_EXPLANATION[self.rung]:
            raise ValueError(f"rung {self.rung} needs {RUNG_EXPLANATION[self.rung]}")
        if (self.rung == 6) != (self.multiple is not None):
            raise ValueError("rung 6 (estimate) needs its multiple, and only rung 6 has one")
        if self.rung == 8 and self.chia_badge is None:
            raise ValueError("rung 8 needs chia_badge")
        if self.by_npi is not None:
            prices = {(p.money.low, p.money.high) for p in self.by_npi}
            if len(prices) < 2:
                raise ValueError("by_npi only when prices differ (D6); else show the range")
        return self


class ElsewhereOption(_Strict):
    """A site that does offer a service this site does not. The browser picks the nearest."""

    site_id: str = Field(pattern=ID_RE)
    site_name: str
    lat: float
    lon: float
    cell: Cell


class LearnMore(_Strict):
    label: str
    url: str


class ReceiptLine(_Strict):
    line_id: str = Field(pattern=ID_RE)
    tier: CertaintyTier
    likelihood: Likelihood
    step_id: str | None = Field(default=None, pattern=ID_RE, description="care path step")
    codes: list[str] = Field(min_length=1, description="technical detail only, never the label")
    modifier: str | None = Field(default=None, pattern=r"^[0-9A-Z]{2}$")
    plain_name: str = Field(description="Primary label (D8)")
    technical_name: str = Field(description="Small text (D8), e.g. 'Shoulder X-ray'")
    why: str | None = Field(description="One sentence, from the care path; None on manual picks")
    glossary_keys: list[str] = Field(default_factory=list)
    component: BillComponent
    component_confirmed: bool = Field(
        description="False when the price file does not say facility vs professional (e.g. CHA)"
    )
    unit: Literal["once", "per_visit", "per_15_minutes"] = "once"
    availability: Literal["offered", "not_offered", "unknown"] = "offered"
    cell: Cell | None = Field(description="None only when availability == not_offered")
    list_price: Money | None = Field(
        default=None,
        description="The gross charge (chargemaster list price), shown on its own row and never "
        "summed. Never the line's price: almost nobody pays it.",
    )
    tier_basis: TierBasis
    doctor_fee: DoctorFee | None = None
    ai_suggested: bool = False
    in_total: bool
    elsewhere: list[ElsewhereOption] = Field(
        default_factory=list, description="Cheapest sites that offer it, when not offered here"
    )
    learn_more: list[LearnMore] = Field(default_factory=list)

    @model_validator(mode="after")
    def _invariants(self) -> ReceiptLine:
        kind = None if self.cell is None else self.cell.kind
        if self.availability == "not_offered":
            if self.cell is not None or not self.elsewhere:
                raise ValueError(f"{self.line_id}: not_offered needs cell=None and elsewhere")
        elif self.cell is None:
            raise ValueError(f"{self.line_id}: every offered line needs a Cell (Money or Gap)")
        if self.cell is not None:
            no_number = kind in NO_NUMBER_GAPS
            if (self.tier == "not_in_public_data") != no_number:
                raise ValueError(
                    f"{self.line_id}: tier not_in_public_data <=> cell is {NO_NUMBER_GAPS}"
                )
            if self.tier != "not_in_public_data":
                expected = "possible" if self.likelihood == "rare" else self.likelihood
                if self.tier != expected:
                    raise ValueError(f"{self.line_id}: tier {self.tier} != likelihood {expected}")
        for m in _line_moneys(self):
            if m.basis == PriceBasis.gross:
                raise ValueError(f"{self.line_id}: a gross charge is only ever list_price")
            if (m.basis == PriceBasis.estimate) != (
                m.prov.method == Method.estimate_medicare_multiple
            ):
                raise ValueError(f"{self.line_id}: basis estimate <=> estimate_medicare_multiple")
        if self.list_price is not None and self.list_price.basis != PriceBasis.gross:
            raise ValueError(f"{self.line_id}: list_price is the gross charge")
        if (self.step_id is None) != (self.tier_basis == "picked"):
            raise ValueError(f"{self.line_id}: tier_basis picked <=> no care path step")
        if self.ai_suggested and self.in_total:
            raise ValueError(f"{self.line_id}: AI-suggested lines never count in a total")
        if self.in_total:
            if self.tier not in ("certain", "likely") or kind != "money" or self.unit != "once":
                raise ValueError(f"{self.line_id}: in_total needs certain/likely + Money + once")
            if self.doctor_fee is not None and (self.doctor_fee.rung or 0) not in range(1, 7):
                raise ValueError(f"{self.line_id}: doctor-fee rungs 7-8 are reference only")
        if self.doctor_fee is not None and self.doctor_fee.rung == 6:
            if (
                not isinstance(self.cell, Money)
                or self.cell.prov.method != Method.estimate_medicare_multiple
            ):
                raise ValueError(f"{self.line_id}: rung 6 Money must be estimate_medicare_multiple")
        return self


def _line_moneys(ln: ReceiptLine) -> Iterator[Money]:
    """Every Money a line prices with (cell, both sides of a conflict, elsewhere cells)."""
    cells = [ln.cell, *(e.cell for e in ln.elsewhere)]
    for c in cells:
        if isinstance(c, Money):
            yield c
        elif isinstance(c, Conflict):
            yield c.a
            yield c.b


# --------------------------------------------------------------------------- totals


class SummedAmount(_Strict):
    """A sum of line Money values. Not a ``Money``: a sum has no single Provenance; each part's
    provenance stays on its line (``line_ids``)."""

    low: float = Field(ge=0)
    high: float = Field(ge=0)
    line_ids: list[str] = Field(min_length=1)
    includes_estimate: bool = Field(
        description="Derived: a rung-6 estimate (estimate_medicare_multiple) is in the sum"
    )
    includes_late_source: bool = Field(
        description="Derived: a summed price's source is late to refresh (publisher side)"
    )
    includes_stale_source: bool = Field(
        description="Derived: we are behind on refreshing a summed price's source (our side)"
    )


class ExcludedLine(_Strict):
    line_id: str
    reason: ExcludedReason


class YouPay(_Strict):
    """What the person actually owes depends on their plan; we say how, never guess the number."""

    kind: Literal[
        "deductible_then_coinsurance",  # commercial: until the deductible is met, the full amount
        "copay_or_deductible",  # commercial: a flat copay or the deductible, depending on the plan
        "medicare_20_percent",
        "masshealth_small_or_no_copay",
        "cash_full_amount",
    ]
    note_key: str = Field(pattern=r"^youpay\.[a-z0-9_]+$")
    portal_label: str | None = None
    portal_url: str | None = Field(default=None, description="Insurer member portal, e.g. MyBlue")


YOU_PAY_BY_PAYMENT: dict[str, set[str]] = {
    "insurance": {"deductible_then_coinsurance", "copay_or_deductible"},
    "medicare": {"medicare_20_percent"},
    "masshealth": {"masshealth_small_or_no_copay"},
    "cash": {"cash_full_amount"},
}


class Totals(_Strict):
    likely: SummedAmount | None = Field(
        description="certain + likely Money lines with in_total; None when nothing can be summed. "
        "Shown as what the care is billed at (you plus your plan), not as what you owe."
    )
    complete: bool = Field(
        description="False when a certain/likely line has no dollar amount (the total is a floor)"
    )
    missing: int = Field(
        ge=0,
        description="Derived (I7): certain/likely, non-AI lines here that are not in the total, "
        "plus certain/likely steps another site in this quote lists and this site does not",
    )
    excluded: list[ExcludedLine]
    you_pay: YouPay


class Receipt(_Strict):
    lines: list[ReceiptLine]
    totals: Totals

    @model_validator(mode="after")
    def _totals_match_lines(self) -> Receipt:
        ids = [ln.line_id for ln in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate line_id in receipt")
        by_id = {ln.line_id: ln for ln in self.lines}
        summed = [ln for ln in self.lines if ln.in_total]
        t = self.totals.likely
        if t is None:
            if summed:
                raise ValueError("lines marked in_total but totals.likely is None")
        else:
            if sorted(t.line_ids) != sorted(ln.line_id for ln in summed):
                raise ValueError("totals.likely.line_ids must be exactly the in_total lines")
            cells = [ln.cell for ln in summed if isinstance(ln.cell, Money)]
            low = round(sum(c.low for c in cells), 2)
            high = round(sum(c.high for c in cells), 2)
            if (round(t.low, 2), round(t.high, 2)) != (low, high):
                raise ValueError(f"totals.likely {t.low}-{t.high} != sum of lines {low}-{high}")
            est = any(c.prov.method == Method.estimate_medicare_multiple for c in cells)
            if t.includes_estimate != est:
                raise ValueError(f"totals.likely.includes_estimate must be {est}")

        excluded = {e.line_id for e in self.totals.excluded}
        if not excluded <= set(by_id):
            raise ValueError("totals.excluded names an unknown line")
        missing = {ln.line_id for ln in self.lines if not ln.in_total} - excluded
        if missing:
            raise ValueError(f"lines neither in the total nor excluded: {sorted(missing)}")
        partial = any(
            ln.likelihood in ("certain", "likely")
            and ln.availability != "not_offered"
            and not ln.in_total
            and not ln.ai_suggested
            for ln in self.lines
        )
        if self.totals.complete == partial:
            raise ValueError(
                "totals.complete must be False exactly when a certain/likely line is missing"
            )
        return self


# --------------------------------------------------------------------------- other payers


class PayerPoint(_Strict):
    payer_id: str | None = Field(
        pattern=PAYER_ID_RE, description="None when the file's payer is not mapped to a registry id"
    )
    label: str = Field(description="Payer + plan as shown, e.g. 'Harvard Pilgrim · self-insured'")
    product: str | None = None
    money: Money


class OtherPayerRange(_Strict):
    """Range bar (PriceRangeBar.tsx): same service, same site, every payer we have + cash."""

    line_id: str
    code: str = Field(pattern=CODE_RE)
    points: list[PayerPoint] = Field(min_length=1)
    cash: Cell | None = Field(description="Self-pay price at this site if known; None = not asked")
    yours: Literal["in_points", "not_in_points"] = Field(
        description="Whether the person's own payer is one of the points"
    )


# --------------------------------------------------------------------------- site + response


class SiteSummary(_Strict):
    site_id: str = Field(pattern=ID_RE)
    name: str
    site_type: SiteType
    system_id: str | None
    coords: Coordinates
    address_line: str
    phone: str | None
    billing_type: BillingType
    booking: list[BookingOption]
    portal_links: list[PortalLink]
    hours: Hours | None
    hours_label: Literal["live_by_operator", "posted_hours", "may_close_early", "unknown"]
    price_label: Literal["price_file", "posted_price", "price_on_request", "mixed"]
    price_source_id: str = Field(
        pattern=ID_RE,
        description="The site's own price source (its hospital MRF or posted page); its freshness "
        "is QuoteResponse.sources[price_source_id]",
    )
    listing_status: Literal["web_verified", "multi_registry"] = Field(
        description="registry_only sites are never quoted (to-verify queue, D27)"
    )
    service_areas: list[ServiceArea]


class SiteQuote(_Strict):
    site: SiteSummary
    receipt: Receipt
    other_payers: list[OtherPayerRange] = Field(default_factory=list)


class OurDataResponse(_Strict):
    """Future /our-data page: every registered source, both sides, so Austin can tell 'we forgot
    to update' (stale_on_our_side) from 'the publisher did not publish' (late_to_refresh)."""

    as_of: date
    sources: dict[str, SourceInfo]

    @model_validator(mode="after")
    def _fresh(self) -> OurDataResponse:
        _check_sources(self.sources, self.as_of)
        return self


class DataVersion(_Strict):
    """Shown in 'Sources & dates'. Lets the UI say how old the whole answer is."""

    build_id: str = Field(description="ETL build id, e.g. 20261024-1cb8089d")
    build_date: date
    tic_release: str | None = Field(description="e.g. tic-2026-10; None = TiC not loaded yet")
    sites_version: int
    care_paths_version: str | None


class CarePathRef(_Strict):
    id: str = Field(pattern=PATH_ID_RE)
    version: str
    title: str
    review_status: Literal["pending_austin", "changes_requested", "approved"] = Field(
        description="Not 'approved' -> the UI shows a draft banner"
    )


PRICE_MATRIX: dict[str, frozenset[tuple[str, str]]] = {
    "insurance": frozenset(
        {
            ("hospital_mrf", "negotiated"),
            ("insurer_tic", "negotiated"),
            ("medicare_pfs", "estimate"),  # rung 6: Medicare x the same payer's own multiple
        }
    ),
    "medicare": frozenset(
        {
            ("medicare_pfs", "fee_schedule"),
            ("medicare_opps", "fee_schedule"),
            ("medicare_asc", "fee_schedule"),
            ("hospital_mrf", "negotiated"),  # the hospital file's own Medicare row (E4)
        }
    ),
    "masshealth": frozenset({("masshealth_fs", "fee_schedule"), ("hospital_mrf", "negotiated")}),
    "cash": frozenset({("hospital_mrf", "discounted_cash"), ("clinic_posted", "posted_self_pay")}),
}
"""Payment -> the (source_kind, basis) pairs a line may be priced with (challenger F1). Rung 7
(Medicare reference) is checked separately: it is shown, never summed."""

RUNGS_BY_PAYMENT: dict[str, set[int | None]] = {
    "insurance": {1, 2, 3, 6, 7, 8},
    "medicare": {5},
    "masshealth": {4, 7, 8},
    "cash": {None},
}
REFERENCE_PAIR = ("medicare_pfs", "fee_schedule")  # rung 7


def _payer_of(
    payment: InsurancePayment | MedicarePayment | MassHealthPayment | CashPayment,
) -> str | None:
    if isinstance(payment, InsurancePayment):
        return payment.payer_id
    return {"medicare": "MEDICARE", "masshealth": "MASSHEALTH"}.get(payment.kind)


def _all_moneys(sq: SiteQuote) -> Iterator[Money]:
    for ln in sq.receipt.lines:
        yield from _line_moneys(ln)
        if ln.list_price is not None:
            yield ln.list_price
        if ln.doctor_fee and ln.doctor_fee.by_npi:
            yield from (p.money for p in ln.doctor_fee.by_npi)
    for o in sq.other_payers:
        yield from (p.money for p in o.points)
        if isinstance(o.cash, Money):
            yield o.cash


def _searched(sq: SiteQuote) -> Iterator[str]:
    for ln in sq.receipt.lines:
        for c in [ln.cell, *(e.cell for e in ln.elsewhere)]:
            if isinstance(c, (NotPublished, PercentOnly)):
                yield c.searched.source_id


def rank_key(sq: SiteQuote) -> tuple[int, float]:
    """I7: completeness band first (missing certain/likely lines), then price. A site that is
    missing a number never sorts above an otherwise identical site that has it."""
    t = sq.receipt.totals
    return (t.missing, t.likely.low if t.likely else math.inf)


def _expected(ln: ReceiptLine) -> bool:
    return ln.likelihood in ("certain", "likely") and not ln.ai_suggested


def _step_key(ln: ReceiptLine) -> str:
    """A care path step, or the codes of a manual pick. Sites bill a step in different lines
    (an office visit is one global fee; a hospital clinic bills facility + doctor)."""
    return ln.step_id or ",".join(ln.codes)


def missing_for(sq: SiteQuote, expected_steps: set[str]) -> int:
    lines = sq.receipt.lines
    unpriced = sum(1 for ln in lines if _expected(ln) and not ln.in_total)
    absent = expected_steps - {_step_key(ln) for ln in lines}
    return unpriced + len(absent)


class QuoteResponse(_Strict):
    payment: Payment
    care_path: CarePathRef | None
    service_codes: list[str]
    picked_by: PickedBy
    as_of: date = Field(description="The day freshness was computed for (per request, not build)")
    data_version: DataVersion
    sources: dict[str, SourceInfo] = Field(
        description="Every source behind a number or a 'not published' claim in this response, "
        "stored once (P2); lines point here by prov.source_id / searched.source_id"
    )
    sites: list[SiteQuote] = Field(description="Ordered by rank_key (I7)")
    sites_without_service: list[str] = Field(
        default_factory=list, description="Sites filtered out because they offer none of it"
    )
    notices: list[
        Literal[
            "care_path_draft",
            "tic_not_loaded",
            "late_to_refresh_sources",
            "stale_on_our_side_sources",
            "masshealth_aco_may_differ",
            "medicare_advantage_is_insurance",
        ]
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rules(self) -> QuoteResponse:
        ids = [s.site.site_id for s in self.sites]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate site in quote")
        _check_sources(self.sources, self.as_of)
        self._check_source_refs()
        self._check_payment_matrix()
        self._check_totals_flags()
        self._check_ranking()
        f = [s.freshness for s in self.sources.values()]
        if any(x.late_to_refresh for x in f) != ("late_to_refresh_sources" in self.notices):
            raise ValueError("notice late_to_refresh_sources <=> some source is late (publisher)")
        if any(x.stale_on_our_side for x in f) != ("stale_on_our_side_sources" in self.notices):
            raise ValueError("notice stale_on_our_side_sources <=> we are behind on some source")
        tic = any(s.source_kind == SourceKind.insurer_tic for s in self.sources.values())
        if tic and self.data_version.tic_release is None:
            raise ValueError("a TiC price needs data_version.tic_release")
        if (self.data_version.tic_release is None) != ("tic_not_loaded" in self.notices):
            raise ValueError("notice tic_not_loaded <=> data_version.tic_release is None")
        if self.picked_by == "assistant":
            if self.care_path is not None:
                raise ValueError("assistant picks are catalog services, never a care path")
            if not all(ln.ai_suggested for sq in self.sites for ln in sq.receipt.lines):
                raise ValueError("every line the assistant picked is ai_suggested")
        return self

    def _check_source_refs(self) -> None:
        used: set[str] = set()
        for sq in self.sites:
            used.add(sq.site.price_source_id)
            used.update(_searched(sq))
            for m in _all_moneys(sq):
                info = self.sources.get(m.prov.source_id)
                if info is None:
                    raise ValueError(f"{m.prov.row_ref}: source {m.prov.source_id} not in sources")
                if info.source_kind != m.prov.source_kind:
                    raise ValueError(
                        f"{m.prov.row_ref}: says {m.prov.source_kind} but source "
                        f"{m.prov.source_id} is {info.source_kind}"
                    )
                used.add(m.prov.source_id)
        if used != set(self.sources):
            missing, extra = sorted(used - set(self.sources)), sorted(set(self.sources) - used)
            raise ValueError(
                f"sources must be exactly the ones used: missing {missing}, unused {extra}"
            )

    def _check_payment_matrix(self) -> None:
        kind = self.payment.kind
        payer = _payer_of(self.payment)
        allowed = PRICE_MATRIX[kind]
        for sq in self.sites:
            if sq.receipt.totals.you_pay.kind not in YOU_PAY_BY_PAYMENT[kind]:
                raise ValueError(
                    f"{sq.site.site_id}: you_pay {sq.receipt.totals.you_pay.kind} is not for {kind}"
                )
            for ln in sq.receipt.lines:
                fee = ln.doctor_fee
                rung = fee.rung if fee else None
                if fee is not None and rung not in RUNGS_BY_PAYMENT[kind]:
                    raise ValueError(f"{ln.line_id}: doctor-fee rung {rung} is not for {kind}")
                if fee and fee.multiple and fee.multiple.payer_id != payer:
                    raise ValueError(f"{ln.line_id}: rung 6 multiple must be {payer}'s own")
                for m in _line_moneys(ln):
                    pair = (m.prov.source_kind.value, m.basis.value)
                    if rung == 7:
                        if pair != REFERENCE_PAIR:
                            raise ValueError(f"{ln.line_id}: rung 7 is the Medicare reference")
                        continue
                    if pair not in allowed:
                        raise ValueError(f"{ln.line_id}: {pair} is not a {kind} price")
                    if m.basis == PriceBasis.negotiated and m.prov.payer_id != payer:
                        raise ValueError(
                            f"{ln.line_id}: {m.prov.row_ref} is {m.prov.payer_id}'s rate, "
                            f"not {payer}'s"
                        )

    def _check_totals_flags(self) -> None:
        for sq in self.sites:
            t = sq.receipt.totals.likely
            if t is None:
                continue
            fresh = [
                self.sources[ln.cell.prov.source_id].freshness
                for ln in sq.receipt.lines
                if ln.in_total and isinstance(ln.cell, Money)
            ]
            late = any(f.late_to_refresh for f in fresh)
            stale = any(f.stale_on_our_side for f in fresh)
            if (t.includes_late_source, t.includes_stale_source) != (late, stale):
                raise ValueError(
                    f"{sq.site.site_id}: includes_late_source / includes_stale_source must be "
                    f"{late} / {stale} (derived from the summed lines)"
                )

    def _check_ranking(self) -> None:
        steps = {_step_key(ln) for sq in self.sites for ln in sq.receipt.lines if _expected(ln)}
        for sq in self.sites:
            want = missing_for(sq, steps)
            if sq.receipt.totals.missing != want:
                raise ValueError(
                    f"{sq.site.site_id}: totals.missing must be {want} (unpriced certain/likely "
                    "lines + steps this site does not list), so skipping a line cannot help rank"
                )
        keys = [rank_key(sq) for sq in self.sites]
        if keys != sorted(keys):
            raise ValueError("sites must be ordered by rank_key: completeness band, then price")


# --------------------------------------------------------------------------- catalog (D3)


class CatalogCode(_Strict):
    code: str = Field(pattern=CODE_RE)
    role: Literal["primary", "alternative", "add_on", "drug", "guidance"]
    description: str = Field(description="Our own short words (no AMA descriptor text)")


class CatalogService(_Strict):
    service_id: str = Field(pattern=ID_RE)
    plain_name: str
    technical_name: str
    kind: Literal[
        "referral",
        "visit",
        "imaging",
        "procedure",
        "lab",
        "anesthesia",
        "therapy",
        "medication",
        "supply",
    ]
    areas: list[ServiceArea] = Field(min_length=1)
    codes: list[CatalogCode] = Field(min_length=1)
    care_paths: list[str] = Field(description="care path ids that include this service")
    glossary_keys: list[str] = Field(default_factory=list)


class CatalogPath(_Strict):
    id: str = Field(pattern=PATH_ID_RE)
    title: str
    area: str = Field(description="care_paths Scope.area, e.g. msk_shoulder")
    review_status: Literal["pending_austin", "changes_requested", "approved"]


class Catalog(_Strict):
    version: str
    care_paths: list[CatalogPath]
    services: list[CatalogService]

    @model_validator(mode="after")
    def _refs(self) -> Catalog:
        known = {p.id for p in self.care_paths}
        sids = [s.service_id for s in self.services]
        if len(sids) != len(set(sids)):
            raise ValueError("duplicate service_id")
        for s in self.services:
            bad = set(s.care_paths) - known
            if bad:
                raise ValueError(f"{s.service_id}: unknown care paths {sorted(bad)}")
        return self
