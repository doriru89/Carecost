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
* ``in_total`` only for certain/likely, offered, Money, non-AI, one-off, not-unusual lines whose
  doctor-fee rung (if any) is 1-6. Rungs 7-8 are reference only. A line whose availability is not
  ``offered`` is never summed (C3 R2: a row in an insurer file is not evidence a site does it).
* An estimate (basis ``estimate``, method ``estimate_peer_range``, doctor-fee rung 6) is the
  p25-p75 of the same line's real prices at >= 5 billing groups of the same kind of site, same
  payer; it carries its ``PeerRange``; ``by_npi`` (D6) needs >= 2 distinct prices.
* ``Totals.likely`` is the exact sum of the lines listed in it; its ``includes_*`` flags and line
  counts are derived from those lines.
* Payment <-> price type (``PRICE_MATRIX``): a BCBS receipt carries only BCBS negotiated rates
  (or an estimate built from BCBS rates), Medicare only Medicare, cash only self-pay prices. A gross charge is never a
  line price; it may only appear as ``list_price``, which is never summed.
* Sources are stored once per response (``QuoteResponse.sources``). A number's chip is its
  ``prov.source_id``; freshness is computed on ``as_of`` for each request.
* I7 (C3): with a point (``near``) or named sites, sites are ordered by ``missing`` (expected steps
  with no figure) then the ``comparable`` figure, in which estimates and steps done elsewhere enter
  as the neutral peer median, so missing data never makes a site look cheaper and more data never
  makes it look dearer. With no point (P7) they are grouped by kind of site and ordered by distance
  from Boston City Hall: no "best value" claim.

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
DEFAULT_MAX_SITES = 12
MAX_SITES = 50
DEFAULT_FULL_RECEIPTS = 12

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


class Near(_Strict):
    """Where to look from (C2, 208 sites). The browser sends the point the person chose; it is
    used only to pick the closest sites and is never stored or logged."""

    lat: float = Field(ge=41.0, le=43.5, description="Greater Boston scope guard (as Coordinates)")
    lon: float = Field(ge=-72.5, le=-69.5)


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
        description="Only these sites; None = every site that offers the services. A children-only "
        "site is quoted only when named here (D27)",
    )
    near: Near | None = Field(
        default=None,
        description="C2: quote the max_sites sites closest to this point (straight-line distance), "
        "ranked (I7). None (P7) = every admitted site, grouped by kind of site and ordered by "
        "distance from Boston City Hall",
    )
    max_sites: int = Field(
        default=DEFAULT_MAX_SITES,
        ge=1,
        le=MAX_SITES,
        description="With `near`: at most this many (the closest) sites. Ignored without `near`",
    )
    full_receipts: int = Field(
        default=DEFAULT_FULL_RECEIPTS,
        ge=0,
        le=MAX_SITES,
        description="C3: without `near` and `site_ids`, the first N sites carry their full receipt; "
        "the rest carry the summary (headline + steps) and are fetched by `site_ids`",
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
    "availability_unknown",  # C3 R2: no evidence this site does it (never summed)
    "unusual",  # C3 P8: outside 1/3x-3x of the peer median (being checked)
]

PriceNote = Literal[
    "price.national_unadjusted",
    "price.anesthesia_base_units_only",
    "price.group_consistently_higher",
    "price.group_consistently_lower",
]
"""Fixed explanation keys for how a line's number was made (copy lives with the glossary).
national_unadjusted: a Medicare OPPS / ASC national rate; a Boston facility is paid this times a
wage adjustment we have not loaded. anesthesia_base_units_only: the anesthesia fee's base units
only; the time units depend on the case and are not included. group_consistently_higher /
lower (Austin 2026-10-25, O contract_level): outside 1/3x-3x of its peers, but the same group is
>= 2x (<= 0.5x) its peers on >= 5 other codes in the same network: its contract, summed, with
"This group's prices are consistently higher (lower) than similar places here"."""

SiteKind = Literal["urgent_care", "office", "hospital_outpatient", "ambulatory_surgery_center"]
"""X2: the kind of site a peer set is drawn from (engine.yaml: urgent care by site_type, else by
the effective billing type). An urgent care is never estimated from hospitals and vice versa (P5)."""

KIND_ORDER: dict[str, int] = {
    "urgent_care": 0, "office": 1, "hospital_outpatient": 2, "ambulatory_surgery_center": 3,
}  # fmt: skip
"""P7: the order of the kind groups in a no-location list."""

PeerScope = Literal["same_kind", "same_system"]

AvailabilityReason = Literal["insurer_lists_rate", "no_evidence", "site_says_not_offered"]
"""Why a line is not ``offered`` (C3 R1, P6). insurer_lists_rate: "Your insurer lists a rate for
this group, but this place doesn't say it offers this. Call to check." no_evidence: nothing says
this place does it. site_says_not_offered: the site's own page says it does not (site facts)."""

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


class PeerRange(_Strict):
    """C3 (R4, P4, P5, X2): the same line's (or step's) real prices at other sites of the same
    kind, under the same payer and plan product, one value per distinct billing group (TIN).
    low / high = p25 / p75 (nearest rank, so each end is a real price); median = the neutral
    figure ranking uses, so an estimate can neither help nor hurt a site."""

    low: float = Field(ge=0)
    high: float = Field(ge=0)
    median: float = Field(ge=0)
    n_groups: int = Field(ge=1, description="distinct billing groups (TINs / files) behind it")
    kind: SiteKind | None = Field(description="kind of the peer sites; None = every kind (P4)")
    scope: PeerScope = Field(description="same_system: the site's own health system's groups")
    payer_id: str | None = Field(
        pattern=PAYER_ID_RE, description="whose rates; None for self-pay / fee schedules"
    )

    @model_validator(mode="after")
    def _order(self) -> PeerRange:
        if not self.low <= self.median <= self.high:
            raise ValueError("PeerRange needs low <= median <= high")
        return self


class UnusualPrice(_Strict):
    """C3 P8: a price more than 3x or less than 1/3x the same line's peer median (same payer,
    same kind of site). Rows outside the band are set aside (shown, never summed); when every row
    is outside, the whole line is unusual and not summed: "price looks unusual, being checked"."""

    peer_median: float = Field(gt=0)
    n_groups: int = Field(ge=1)
    whole_line: bool
    set_aside: list[Money] = Field(
        default_factory=list, description="the rows left out of the line's range (cited)"
    )


class AnesthesiaTime(_Strict):
    """C3 item 12: 'with typical time, about $Y'. Anesthesia is paid (base units + minutes / 15)
    x a conversion factor; the summed line has the base units only. Never summed."""

    minutes: float = Field(gt=0)
    base_units: float = Field(gt=0)
    low: float = Field(ge=0)
    high: float = Field(ge=0)
    source: str = Field(description="the public CMS file the typical minutes come from")


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
    availability_reason: AvailabilityReason | None = Field(
        default=None, description="C3 P6: why the line is not offered; None exactly when offered"
    )
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
    price_notes: list[PriceNote] = Field(
        default_factory=list,
        description="C2: fixed copy keys that explain how the line's number was made (e.g. a "
        "Medicare national rate not adjusted for Boston wages). Empty = nothing to add",
    )
    estimate: PeerRange | None = Field(
        default=None,
        description="C3 (P5): the peer range behind an estimated cell (basis estimate); None "
        "otherwise",
    )
    unusual: UnusualPrice | None = Field(
        default=None, description="C3 (P8): rows outside 1/3x-3x of the peer median"
    )
    anesthesia_time: AnesthesiaTime | None = Field(
        default=None, description="C3: the anesthesia fee with a typical time (never summed)"
    )
    chain_price_from: str | None = Field(
        default=None,
        pattern=ID_RE,
        description="C3 R12: the price is the chain's posted self-pay price, published on this "
        "site's page (it applies at every location of the chain)",
    )
    at: Literal["this_site", "your_primary_care"] = Field(
        default="this_site",
        description="Where this part of the care happens. your_primary_care: an HMO referral visit "
        "happens at the person's own primary care office, not at this site; the price is a range "
        "over the primary care groups we have, never this site's (P1 problem 15)",
    )

    @model_validator(mode="after")
    def _invariants(self) -> ReceiptLine:
        kind = None if self.cell is None else self.cell.kind
        if (self.availability == "offered") != (self.availability_reason is None):
            raise ValueError(f"{self.line_id}: availability_reason exactly when not offered")
        if self.availability == "not_offered":
            if self.cell is not None:
                raise ValueError(f"{self.line_id}: not_offered needs cell=None")
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
            if (m.basis == PriceBasis.estimate) != (m.prov.method == Method.estimate_peer_range):
                raise ValueError(f"{self.line_id}: basis estimate <=> estimate_peer_range")
        if self.list_price is not None and self.list_price.basis != PriceBasis.gross:
            raise ValueError(f"{self.line_id}: list_price is the gross charge")
        if (self.step_id is None) != (self.tier_basis == "picked"):
            raise ValueError(f"{self.line_id}: tier_basis picked <=> no care path step")
        if self.ai_suggested and self.in_total:
            raise ValueError(f"{self.line_id}: AI-suggested lines never count in a total")
        estimated = isinstance(self.cell, Money) and self.cell.basis == PriceBasis.estimate
        if estimated != (self.estimate is not None):
            raise ValueError(f"{self.line_id}: an estimated cell <=> its PeerRange")
        if self.estimate is not None and isinstance(self.cell, Money) and (
            (self.cell.low, self.cell.high) != (self.estimate.low, self.estimate.high)
        ):  # fmt: skip
            raise ValueError(f"{self.line_id}: the estimate is the peer range's p25-p75")
        if self.in_total:
            if self.tier not in ("certain", "likely") or kind != "money" or self.unit != "once":
                raise ValueError(f"{self.line_id}: in_total needs certain/likely + Money + once")
            if self.availability != "offered":
                raise ValueError(f"{self.line_id}: only an offered line is summed (R2)")
            if self.unusual is not None and self.unusual.whole_line:
                raise ValueError(f"{self.line_id}: an unusual price is never summed (P8)")
            if self.doctor_fee is not None and (self.doctor_fee.rung or 0) not in range(1, 7):
                raise ValueError(f"{self.line_id}: doctor-fee rungs 7-8 are reference only")
        if "price.national_unadjusted" in self.price_notes and not (
            isinstance(self.cell, Money)
            and self.cell.prov.source_kind in (SourceKind.medicare_opps, SourceKind.medicare_asc)
        ):
            raise ValueError(f"{self.line_id}: national_unadjusted is a Medicare OPPS / ASC rate")
        if self.doctor_fee is not None and (self.doctor_fee.rung == 6) != estimated:
            raise ValueError(f"{self.line_id}: doctor-fee rung 6 <=> an estimated cell")
        return self


def _line_moneys(ln: ReceiptLine) -> Iterator[Money]:
    """Every Money a line prices with (cell, both sides of a conflict, elsewhere cells, rows an
    unusual check set aside)."""
    cells = [ln.cell, *(e.cell for e in ln.elsewhere)]
    for c in cells:
        if isinstance(c, Money):
            yield c
        elif isinstance(c, Conflict):
            yield c.a
            yield c.b
    if ln.unusual is not None:
        yield from ln.unusual.set_aside


# --------------------------------------------------------------------------- totals


class SummedAmount(_Strict):
    """A sum of line Money values. Not a ``Money``: a sum has no single Provenance; each part's
    provenance stays on its line (``line_ids``)."""

    low: float = Field(ge=0)
    high: float = Field(ge=0)
    line_ids: list[str] = Field(min_length=1)
    includes_estimate: bool = Field(
        description="Derived: a peer estimate (estimate_peer_range) is in the sum"
    )
    includes_late_source: bool = Field(
        description="Derived: a summed price's source is late to refresh (publisher side)"
    )
    includes_stale_source: bool = Field(
        description="Derived: we are behind on refreshing a summed price's source (our side)"
    )


class MightAdd(_Strict):
    low: float = Field(ge=0)
    high: float = Field(ge=0)
    step_keys: list[str] = Field(min_length=1)


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
        description="Derived (I7, C3): expected (certain/likely, non-AI) steps with no figure here "
        "(no own price, no estimate, no 'elsewhere' range) although some admitted site has a price "
        "for that step: one per step, not per line. A step nobody has a price for is not counted "
        "(it is the same everywhere). Counted over every admitted site, never over the response",
    )
    excluded: list[ExcludedLine]
    you_pay: YouPay
    comparable: float | None = Field(
        default=None,
        description="C3 (P1, P4): the ranking figure: this site's real prices (each line's median "
        "row) plus estimates and steps done elsewhere at their neutral peer median; steps with no "
        "figure are left out (they count in `missing`). None when no step has a figure",
    )
    real_steps: int = Field(
        default=0, ge=0, description="C3: expected steps priced from this site's own real prices"
    )
    might_add: MightAdd | None = Field(
        default=None,
        description="C3 (P9): possible steps this site offers, 'might add $X-$Y' (X = the "
        "cheapest one, Y = all of them); never in `likely`",
    )


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
            est = any(c.prov.method == Method.estimate_peer_range for c in cells)
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


class DataNotice(_Strict):
    """One entry of data/etl/data_quality_notices.yaml (written by people, never by the AI)."""

    id: str = Field(pattern=ID_RE)
    kind: str = Field(pattern=ID_RE, description="e.g. content_changed_date_unchanged")
    source_id: str = Field(pattern=ID_RE)
    observed: date
    detail: str
    effect: str | None = None


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
    price_source_id: str | None = Field(
        pattern=ID_RE,
        description="The site's own price source (its hospital MRF or posted page); its freshness "
        "is QuoteResponse.sources[price_source_id]. None = the site has its own price source but "
        "we do not read it yet (e.g. a clinic's self-pay page): its lines are not_loaded "
        "(P1 problem 9)",
    )
    listing_status: Literal["web_verified", "multi_registry"] = Field(
        description="registry_only sites are never quoted (to-verify queue, D27)"
    )
    service_areas: list[ServiceArea]
    kind: SiteKind = Field(description="X2 / P7: the kind of site (engine.yaml kind_by_billing)")
    chain_id: str | None = Field(
        default=None, pattern=ID_RE, description="C3 R12: the chain whose posted prices apply here"
    )
    children_only: bool = Field(default=False, description="Pediatric-only site (D27)")
    data_notices: list[DataNotice] = Field(
        default_factory=list,
        description="C2: data-quality notices about this site's own price file "
        "(data/etl/data_quality_notices.yaml), e.g. its content changed but its date did not",
    )


StepFigure = Literal["own", "estimate", "elsewhere", "none"]
"""C3: what a step's figure on this site rests on. own: every line is this site's real price;
estimate: at least one line is a peer estimate; elsewhere: this site has no evidence it does the
step, the figure is the p25-p75 at sites that do (P4); none: no figure."""


class StepSummary(_Strict):
    """C3 (P3, item 10): one step at one site, so the map can show one selected service's price.
    low / high: the step's summed lines here (own / estimate) or the elsewhere range."""

    key: str = Field(description="care path step id, or the codes of a manual pick")
    step_id: str | None = Field(default=None, pattern=ID_RE)
    likelihood: Likelihood
    availability: Literal["offered", "not_offered", "unknown"]
    figure: StepFigure
    low: float | None = Field(ge=0)
    high: float | None = Field(ge=0)
    rank_value: float | None = Field(
        ge=0, description="the neutral figure in `comparable` (None: not counted)"
    )
    estimated: bool
    unusual: bool = Field(description="a line of the step was set aside as unusual (P8)")
    in_total: bool = Field(description="the step's lines are in totals.likely")
    missing: bool = Field(description="counted in totals.missing")
    line_ids: list[str]
    elsewhere: PeerRange | None = Field(
        default=None, description="P4: the step's price at sites that do it (same payer)"
    )

    @model_validator(mode="after")
    def _shape(self) -> StepSummary:
        if (self.low is None) != (self.high is None) or (
            self.low is not None and self.high is not None and self.low > self.high
        ):  # fmt: skip
            raise ValueError(f"{self.key}: low <= high, both or neither")
        if (self.figure == "none") != (self.low is None):
            raise ValueError(f"{self.key}: a step has low/high exactly when it has a figure")
        if (self.figure == "elsewhere") != (self.elsewhere is not None and self.low is not None
                                            and self.availability != "offered"):  # fmt: skip
            raise ValueError(f"{self.key}: an elsewhere figure is a not-offered step's range")
        if self.missing and self.figure != "none":
            raise ValueError(f"{self.key}: a step with a figure is not missing")
        if self.in_total and self.availability != "offered":
            raise ValueError(f"{self.key}: only an offered step is summed")
        return self


class Headline(_Strict):
    """C3 (item 9): what a list row shows without the full receipt (receipt.totals when it is
    present, copied)."""

    likely_low: float | None = Field(ge=0)
    likely_high: float | None = Field(ge=0)
    includes_estimate: bool
    complete: bool
    missing: int = Field(ge=0)
    comparable: float | None = Field(ge=0)
    real_steps: int = Field(ge=0)
    might_add: MightAdd | None = None


class SiteQuote(_Strict):
    site: SiteSummary
    headline: Headline
    steps: list[StepSummary] = Field(
        default_factory=list, description="C3 (P3): one per step of the quote, in path order"
    )
    distance_km: float | None = Field(
        default=None,
        ge=0,
        description="From the request's point, or from Boston City Hall when there is none (P7)",
    )
    receipt: Receipt | None = Field(
        description="C3: None for a site past `full_receipts` in a no-location list; ask for it "
        "with `site_ids`"
    )
    other_payers: list[OtherPayerRange] = Field(default_factory=list)

    @model_validator(mode="after")
    def _headline(self) -> SiteQuote:
        keys = [st.key for st in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.site.site_id}: duplicate step key")
        if self.headline.missing != sum(1 for st in self.steps if st.missing):
            raise ValueError(f"{self.site.site_id}: headline.missing = the missing steps")
        if self.receipt is None:
            if self.other_payers:
                raise ValueError(f"{self.site.site_id}: other_payers come with the receipt")
            return self
        t = self.receipt.totals
        want = Headline(
            likely_low=t.likely.low if t.likely else None,
            likely_high=t.likely.high if t.likely else None,
            includes_estimate=bool(t.likely and t.likely.includes_estimate),
            complete=t.complete, missing=t.missing, comparable=t.comparable,
            real_steps=t.real_steps, might_add=t.might_add,
        )  # fmt: skip
        if self.headline != want:
            raise ValueError(f"{self.site.site_id}: headline must copy receipt.totals")
        ids = {ln.line_id for ln in self.receipt.lines}
        for st in self.steps:
            if not set(st.line_ids) <= ids:
                raise ValueError(f"{self.site.site_id}: step {st.key} names an unknown line")
        return self


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
            ("insurer_tic", "estimate"),  # C3 rung 6: the same payer's rates at peer sites
            ("hospital_mrf", "estimate"),
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
    "cash": frozenset({
        ("hospital_mrf", "discounted_cash"), ("clinic_posted", "posted_self_pay"),
        ("hospital_mrf", "estimate"), ("clinic_posted", "estimate"),  # peers' self-pay prices
    }),
}  # fmt: skip
"""Payment -> the (source_kind, basis) pairs a line may be priced with (challenger F1). Rung 7
(Medicare reference) is checked separately: it is shown, never summed."""

RUNGS_BY_PAYMENT: dict[str, set[int | None]] = {
    "insurance": {1, 2, 3, 6, 7, 8},
    "medicare": {5},
    "masshealth": {4, 7, 8},
    "cash": {None, 6},
}
REFERENCE_PAIR = ("medicare_pfs", "fee_schedule")  # rung 7


def _payer_of(
    payment: InsurancePayment | MedicarePayment | MassHealthPayment | CashPayment,
) -> str | None:
    if isinstance(payment, InsurancePayment):
        return payment.payer_id
    return {"medicare": "MEDICARE", "masshealth": "MASSHEALTH"}.get(payment.kind)


def _all_moneys(sq: SiteQuote) -> Iterator[Money]:
    if sq.receipt is None:
        return
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
    for ln in sq.receipt.lines if sq.receipt else []:
        for c in [ln.cell, *(e.cell for e in ln.elsewhere)]:
            if isinstance(c, (NotPublished, PercentOnly)):
                yield c.searched.source_id


def rank_key(sq: SiteQuote) -> tuple[int, float]:
    """I7 (C3): missing steps first, then the comparable figure (own real prices + estimates and
    elsewhere steps at the neutral peer median). A site missing a step never sorts above an
    otherwise identical site that has it."""
    h = sq.headline
    return (h.missing, h.comparable if h.comparable is not None else math.inf)


def kind_distance_key(sq: SiteQuote) -> tuple[int, float]:
    """P7: no location -> grouped by kind of site, then distance from Boston City Hall."""
    return (KIND_ORDER[sq.site.kind], sq.distance_km if sq.distance_km is not None else math.inf)


def _expected(ln: ReceiptLine) -> bool:
    """A line the quote expects a number for: certain / likely and not AI-suggested. An HMO
    referral line (at: your_primary_care) counts too: it is the same at every site, so it never
    changes the order, and leaving it out would let a dropped referral price lift one site (I7)."""
    return ln.likelihood in ("certain", "likely") and not ln.ai_suggested


def _step_key(ln: ReceiptLine) -> str:
    """A care path step, or the codes of a manual pick. Sites bill a step in different lines
    (an office visit is one global fee; a hospital clinic bills facility + doctor)."""
    return ln.step_id or ",".join(ln.codes)


def missing_for(sq: SiteQuote) -> int:
    """I7 ``missing`` (C3): the expected steps flagged missing (one per step, not per line)."""
    return sum(1 for st in sq.steps if st.missing)


Ordering = Literal["rank", "kind_then_distance"]


class ChainSpread(_Strict):
    """C3 R12: within one chain, the same line under the same payer differs by more than the
    engine.yaml limit (1.5x): flagged for review, both ends named."""

    chain_id: str = Field(pattern=ID_RE)
    key: str = Field(description="step key / component / code / modifier")
    low_site_id: str = Field(pattern=ID_RE)
    low: float = Field(ge=0)
    high_site_id: str = Field(pattern=ID_RE)
    high: float = Field(ge=0)
    ratio: float = Field(gt=1)


class LocalLabel(_Strict):
    en: str
    zh: str


class QuoteResponse(_Strict):
    payment: Payment
    payment_label: LocalLabel = Field(
        description="P2: how the payment is named to a person; cash is 'Self-pay (no insurance)'"
    )
    care_path: CarePathRef | None
    service_codes: list[str]
    picked_by: PickedBy
    as_of: date = Field(description="The day freshness was computed for (per request, not build)")
    data_version: DataVersion
    sources: dict[str, SourceInfo] = Field(
        description="Every source behind a number or a 'not published' claim in this response, "
        "stored once (P2); lines point here by prov.source_id / searched.source_id"
    )
    sites: list[SiteQuote] = Field(
        description="ordering rank: by rank_key (I7); kind_then_distance: by kind_distance_key (P7)"
    )
    ordering: Ordering = Field(
        default="rank", description="C3 P7: rank with a point or named sites, else by kind"
    )
    origin: Near | None = Field(
        default=None, description="where distance_km is measured from (the point, or City Hall)"
    )
    chain_spreads: list[ChainSpread] = Field(
        default_factory=list, description="C3 R12: same chain, same line, prices > 1.5x apart"
    )
    sites_without_service: list[str] = Field(
        default_factory=list, description="Sites filtered out because they offer none of it"
    )
    copy_keys: list[Literal["copy.not_a_diagnosis", "copy.when_to_see_a_doctor"]] = Field(
        default_factory=list,
        description="D33: a quote reached from a care path carries both fixed lines (common causes, "
        "not a diagnosis; when to see a doctor); a manual pick carries none (P1 problem 13)",
    )
    notices: list[
        Literal[
            "care_path_draft",
            "tic_not_loaded",
            "late_to_refresh_sources",
            "stale_on_our_side_sources",
            "masshealth_aco_may_differ",
            "medicare_advantage_is_insurance",
            "chain_price_spread",
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
        want_copy = ["copy.not_a_diagnosis", "copy.when_to_see_a_doctor"] if self.care_path else []
        if self.copy_keys != want_copy:
            raise ValueError(f"copy_keys must be {want_copy} (D33)")
        if bool(self.chain_spreads) != ("chain_price_spread" in self.notices):
            raise ValueError("notice chain_price_spread <=> chain_spreads")
        if self.picked_by == "assistant":
            if self.care_path is not None:
                raise ValueError("assistant picks are catalog services, never a care path")
            if not all(ln.ai_suggested for sq in self.sites if sq.receipt
                       for ln in sq.receipt.lines):  # fmt: skip
                raise ValueError("every line the assistant picked is ai_suggested")
        return self

    def _check_source_refs(self) -> None:
        used: set[str] = set()
        for sq in self.sites:
            if sq.site.price_source_id is not None:
                used.add(sq.site.price_source_id)
            if sq.receipt is None:
                continue
            used.update(_searched(sq))
            for m in _all_moneys(sq):
                for p in m.provs():
                    info = self.sources.get(p.source_id)
                    if info is None:
                        raise ValueError(f"{p.row_ref}: source {p.source_id} not in sources")
                    if info.source_kind != p.source_kind:
                        raise ValueError(
                            f"{p.row_ref}: says {p.source_kind} but source "
                            f"{p.source_id} is {info.source_kind}"
                        )
                    used.add(p.source_id)
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
            if sq.receipt is None:
                continue
            if sq.receipt.totals.you_pay.kind not in YOU_PAY_BY_PAYMENT[kind]:
                raise ValueError(
                    f"{sq.site.site_id}: you_pay {sq.receipt.totals.you_pay.kind} is not for {kind}"
                )
            for ln in sq.receipt.lines:
                fee = ln.doctor_fee
                rung = fee.rung if fee else None
                if fee is not None and rung not in RUNGS_BY_PAYMENT[kind]:
                    raise ValueError(f"{ln.line_id}: doctor-fee rung {rung} is not for {kind}")
                if ln.estimate is not None and ln.estimate.payer_id != payer:
                    raise ValueError(
                        f"{ln.line_id}: an estimate must be built from {payer}'s rates"
                    )
                for m in _line_moneys(ln):
                    pair = (m.prov.source_kind.value, m.basis.value)
                    if rung == 7:
                        if pair != REFERENCE_PAIR:
                            raise ValueError(f"{ln.line_id}: rung 7 is the Medicare reference")
                        continue
                    if pair not in allowed:
                        raise ValueError(f"{ln.line_id}: {pair} is not a {kind} price")
                    for p in m.provs():
                        if m.basis in (PriceBasis.negotiated, PriceBasis.estimate) and (
                            p.payer_id != payer
                        ):  # fmt: skip
                            raise ValueError(
                                f"{ln.line_id}: {p.row_ref} is {p.payer_id}'s rate, not {payer}'s"
                            )

    def _check_totals_flags(self) -> None:
        for sq in self.sites:
            t = sq.receipt.totals.likely if sq.receipt else None
            if t is None:
                continue
            fresh = [
                self.sources[p.source_id].freshness
                for ln in sq.receipt.lines
                if ln.in_total and isinstance(ln.cell, Money)
                for p in ln.cell.provs()
            ]
            late = any(f.late_to_refresh for f in fresh)
            stale = any(f.stale_on_our_side for f in fresh)
            if (t.includes_late_source, t.includes_stale_source) != (late, stale):
                raise ValueError(
                    f"{sq.site.site_id}: includes_late_source / includes_stale_source must be "
                    f"{late} / {stale} (derived from the summed lines)"
                )

    def _check_ranking(self) -> None:
        for sq in self.sites:
            want = missing_for(sq)
            if sq.headline.missing != want:
                raise ValueError(
                    f"{sq.site.site_id}: totals.missing must be {want} (the expected steps with "
                    "no figure), so skipping a line cannot help rank"
                )
            if self.origin is not None and sq.distance_km is None:
                raise ValueError(f"{sq.site.site_id}: distance_km is measured from origin")
            for st in sq.steps:  # a missing step adds nothing to the ranking figure
                if st.missing and st.rank_value is not None:
                    raise ValueError(f"{sq.site.site_id}: missing step {st.key} has a rank value")
        if self.ordering == "rank":
            keys = [rank_key(sq) for sq in self.sites]
            if keys != sorted(keys):
                raise ValueError("sites must be ordered by rank_key: missing steps, then price")
        else:
            if self.origin is None:
                raise ValueError("kind_then_distance needs its origin")
            keys2 = [kind_distance_key(sq) for sq in self.sites]
            if keys2 != sorted(keys2):
                raise ValueError("no-location sites are grouped by kind, then by distance (P7)")


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
