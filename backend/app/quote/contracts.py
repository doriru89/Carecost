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
* ``Totals.likely`` is the exact sum of the lines listed in it.

``python -m app.api_contracts`` regenerates ``contracts/quote_api.schema.json`` and
``contracts/catalog.schema.json``.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.etl.contracts import Cell, Method, Money, SourceKind
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
)

PAYER_ID_RE = r"^[A-Z][A-Z0-9_]*$"  # data/etl/payer_aliases.yaml `payers:` keys (BCBS_MA ...)
PATH_ID_RE = r"^[a-z0-9_]+_v[0-9]+$"  # care_paths.CarePath.id
QUESTION_ID_RE = r"^Q[0-9]+$"
ANSWER_RE = r"^[a-z0-9_]+$"


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


class QuoteRequest(_Strict):
    payment: Payment
    care_path_id: str | None = Field(pattern=PATH_ID_RE)
    answers: dict[str, list[str]] = Field(
        description="Chip answers keyed by questions.yaml id (Q14 -> referral layer, tier "
        "modifiers). Ids and values only; never free text.",
    )
    service_codes: list[str] = Field(
        description="D3 manual picker: CPT/HCPCS codes from the catalog"
    )
    site_ids: list[str] | None = Field(
        description="Only these sites; None = every site that offers the services"
    )

    @model_validator(mode="after")
    def _one_of(self) -> QuoteRequest:
        if (self.care_path_id is None) == (not self.service_codes):
            raise ValueError("give exactly one of care_path_id or service_codes")
        for c in self.service_codes:
            if not re.match(CODE_RE, c):
                raise ValueError(f"bad service code {c!r}")
        for q, vals in self.answers.items():
            if not re.match(QUESTION_ID_RE, q) or not all(re.match(ANSWER_RE, v) for v in vals):
                raise ValueError(f"answers must be question ids -> answer values, got {q!r}")
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


class SourceChip(_Strict):
    """What the source chip on a line shows (hover text keys off source_kind, plan §2.2)."""

    source_id: str = Field(
        pattern=ID_RE,
        description="data/etl sources registry id, e.g. mtauburn_mrf (joins /our-data)",
    )
    source_kind: SourceKind
    publisher: str = Field(
        description="Who published it, e.g. 'Mount Auburn Hospital', 'BCBS MA', 'CMS'"
    )
    label_key: str = Field(
        pattern=r"^source\.[a-z0-9_]+$", description="fixed copy key: source.<source_kind>"
    )
    freshness: Freshness = Field(
        description="Per data point: (a) publisher late to refresh, (b) stale on our side"
    )
    rows: int | None = Field(default=None, ge=0, description="price-file rows behind the number")


class NpiPrice(_Strict):
    npi: str = Field(pattern=r"^[0-9]{10}$")
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
    sources: list[SourceChip] = Field(description="Chips for the price shown, with freshness")

    @model_validator(mode="after")
    def _chip(self) -> ElsewhereOption:
        if self.cell.kind == "money" and not self.sources:
            raise ValueError(f"elsewhere {self.site_id}: a Money needs its source chip")
        return self


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
    sources: list[SourceChip] = Field(
        default_factory=list, description="One chip per number shown (two for a conflict)"
    )
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
            if kind == "money" and not self.sources:
                raise ValueError(f"{self.line_id}: a Money line needs its source chip")
            if kind == "conflict" and len(self.sources) < 2:
                raise ValueError(f"{self.line_id}: a conflict shows both sources")
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


# --------------------------------------------------------------------------- totals


class SummedAmount(_Strict):
    """A sum of line Money values. Not a ``Money``: a sum has no single Provenance; each part's
    provenance stays on its line (``line_ids``)."""

    low: float = Field(ge=0)
    high: float = Field(ge=0)
    line_ids: list[str] = Field(min_length=1)
    includes_estimate: bool = Field(description="True when a rung-6 estimate is in the sum")
    includes_late_source: bool = Field(description="True when a 'late to refresh' price is in it")
    includes_stale_source: bool = Field(
        description="True when a price we are behind on refreshing (our side) is in it"
    )


class ExcludedLine(_Strict):
    line_id: str
    reason: ExcludedReason


class YouPay(_Strict):
    """What the person actually owes depends on their plan; we say how, never guess the number."""

    kind: Literal[
        "deductible_then_coinsurance",  # commercial: until the deductible is met, the full amount
        "medicare_20_percent",
        "masshealth_small_or_no_copay",
        "cash_full_amount",
    ]
    note_key: str = Field(pattern=r"^youpay\.[a-z0-9_]+$")
    portal_label: str | None = None
    portal_url: str | None = Field(default=None, description="Insurer member portal, e.g. MyBlue")


class Totals(_Strict):
    likely: SummedAmount | None = Field(
        description="certain + likely Money lines with in_total; None when nothing can be summed"
    )
    complete: bool = Field(
        description="False when a certain/likely line has no dollar amount (the total is a floor)"
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
        pattern=ID_RE, description="The site's own price source (its hospital MRF or posted page)"
    )
    price_freshness: Freshness = Field(
        description="Per site: freshness of the site's own price source (both sides)"
    )
    any_source_late: bool = Field(
        description="(a) any source on this receipt is late to refresh (publisher side)"
    )
    any_source_stale_on_our_side: bool = Field(
        description="(b) we are behind on refreshing any source on this receipt (our side)"
    )
    service_areas: list[ServiceArea]


class SiteQuote(_Strict):
    site: SiteSummary
    receipt: Receipt
    other_payers: list[OtherPayerRange] = Field(default_factory=list)

    @model_validator(mode="after")
    def _site_freshness(self) -> SiteQuote:
        chips = [c for ln in self.receipt.lines for c in ln.sources]
        s = self.site
        for c in chips:
            if c.source_id == s.price_source_id and c.freshness != s.price_freshness:
                raise ValueError(f"{s.site_id}: chip {c.source_id} disagrees with price_freshness")
        late = any(c.freshness.late_to_refresh for c in chips) or s.price_freshness.late_to_refresh
        stale = (
            any(c.freshness.stale_on_our_side for c in chips) or s.price_freshness.stale_on_our_side
        )
        if (s.any_source_late, s.any_source_stale_on_our_side) != (late, stale):
            raise ValueError(f"{s.site_id}: any_source_late / any_source_stale_on_our_side wrong")
        return self


class SourceStatus(_Strict):
    """One source and both freshness sides. Listed in DataVersion.sources_behind and /our-data."""

    source_id: str = Field(pattern=ID_RE)
    source_kind: SourceKind
    publisher: str
    freshness: Freshness


class OurDataResponse(_Strict):
    """Future /our-data page: every registered source, both sides, so Austin can tell 'we forgot
    to update' (stale_on_our_side) from 'the publisher did not publish' (late_to_refresh)."""

    as_of: date
    sources: list[SourceStatus]


class DataVersion(_Strict):
    """Shown in 'Sources & dates'. Lets the UI say how old the whole answer is."""

    build_id: str = Field(description="ETL build id, e.g. 20261024-1cb8089d")
    build_date: date
    tic_release: str | None = Field(description="e.g. tic-2026-11; None = TiC not loaded yet")
    sites_version: int
    care_paths_version: str | None
    sources_behind: list[SourceStatus] = Field(
        description="Every source behind this answer that is late (publisher) or stale (ours)"
    )

    @model_validator(mode="after")
    def _behind_only(self) -> DataVersion:
        for st in self.sources_behind:
            f = st.freshness
            if not (f.late_to_refresh or f.stale_on_our_side):
                raise ValueError(f"{st.source_id} is current; only list sources that are behind")
        return self


class CarePathRef(_Strict):
    id: str = Field(pattern=PATH_ID_RE)
    version: str
    title: str
    review_status: Literal["pending_austin", "changes_requested", "approved"] = Field(
        description="Not 'approved' -> the UI shows a draft banner"
    )


class QuoteResponse(_Strict):
    payment: Payment
    care_path: CarePathRef | None
    service_codes: list[str]
    data_version: DataVersion
    sites: list[SiteQuote]
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
    def _ids(self) -> QuoteResponse:
        ids = [s.site.site_id for s in self.sites]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate site in quote")
        seen: dict[str, Freshness] = {}
        for sq in self.sites:
            pairs = [(c.source_id, c.freshness) for ln in sq.receipt.lines for c in ln.sources]
            pairs.append((sq.site.price_source_id, sq.site.price_freshness))
            pairs += [
                (c.source_id, c.freshness)
                for ln in sq.receipt.lines
                for e in ln.elsewhere
                for c in e.sources
            ]
            for sid, f in pairs:
                if seen.setdefault(sid, f) != f:
                    raise ValueError(f"source {sid} has two different freshness values")
        flagged = {k for k, f in seen.items() if f.late_to_refresh or f.stale_on_our_side}
        behind = {st.source_id: st.freshness for st in self.data_version.sources_behind}
        if set(behind) != flagged or any(behind[k] != seen[k] for k in flagged):
            raise ValueError("data_version.sources_behind must list exactly the flagged sources")
        late = any(f.late_to_refresh for f in seen.values())
        stale = any(f.stale_on_our_side for f in seen.values())
        if late != ("late_to_refresh_sources" in self.notices):
            raise ValueError("notice late_to_refresh_sources <=> some source is late (publisher)")
        if stale != ("stale_on_our_side_sources" in self.notices):
            raise ValueError("notice stale_on_our_side_sources <=> we are behind on some source")
        return self


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
