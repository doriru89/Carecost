"""Contract for ``data/sites/sites.yaml`` (filled by stream A3) and the freshness label.

A *site* is a place a person can go: an urgent care, a hospital outpatient department, an
orthopedic walk-in clinic, a small specialist office. Plan §2.6 + D7:

* coordinates (Census batch geocoder in CI), address, phone, hours and where the hours came from;
* ``billing_type``: billed as an office visit, or as hospital outpatient (adds a facility fee);
* booking options are *links only* (On My Way, Solv, Clockwise, MyChart / Patient Gateway): never
  scraped, never iframed unless ``iframe_mgb``;
* posted self-pay prices, each with the URL it was read from and the date it was checked.

Ids are free strings validated against registries in tests, never closed enums: Austin wants many
insurers, hospitals, urgent cares and small clinics inside the Greater Boston scope.

``Freshness`` is shared with the quote contract. It keeps two meanings apart: the publisher is
late (shown, labelled "late to refresh", never hidden) vs we are behind our own fetch schedule
("stale on our side", our fault). See the class docstring.

``python -m app.api_contracts`` regenerates ``contracts/site.schema.json``.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.etl.contracts import placeholders_allowed

ID_RE = r"^[a-z0-9][a-z0-9_]*$"
CODE_RE = r"^([0-9]{4}[0-9A-Z]|[A-Z][0-9]{4})$"  # CPT / HCPCS (same rule as care_paths.CptRef)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- freshness


SourceCadence = Literal[
    "hospital_mrf_365_days",  # hospital MRF: >365 days after the file's own last_updated_on (Austin: 超过一年算没更新)
    "tic_45_days",  # insurer TiC: due monthly; late after 45 days
    "fee_schedule_annual",  # Medicare PFS / MassHealth: next annual effective date
    "fee_schedule_quarterly",  # OPPS / ASC addenda: next quarterly release
    "posted_page_date_365_days",  # clinic page: >365 days after the date printed on the page
    "no_publisher_deadline",  # the source states no date / has no cycle: never "late"
]
"""(a) Source side: when the *publisher* owed us a newer version."""

OurCadence = Literal[
    "hospital_monthly",
    "tic_monthly",
    "nppes_monthly",
    "sites_weekly",  # posted prices + hours (the weekly price checker)
    "fee_schedule_per_release",  # due when the publisher releases the next version
]
"""(b) Our side: when *we* owed ourselves a new fetch/check."""

SOURCE_DEADLINE_DAYS: dict[str, int | None] = {
    "hospital_mrf_365_days": 365,
    "tic_45_days": 45,
    "fee_schedule_annual": None,  # explicit next effective date
    "fee_schedule_quarterly": None,  # explicit next release date
    "posted_page_date_365_days": 365,
    "no_publisher_deadline": None,
}
OUR_DEADLINE_DAYS: dict[str, int | None] = {
    "hospital_monthly": 31,
    "tic_monthly": 31,
    "nppes_monthly": 31,
    "sites_weekly": 7,
    "fee_schedule_per_release": None,  # explicit next release date
}


class Freshness(_Strict):
    """How current one source is, from two sides that must never be confused (Austin, 2026-10-24).

    (a) Source side -- ``late_to_refresh``: the publisher (hospital, insurer, agency, clinic) is
        past its own deadline. Shown to users as "late to refresh"; the data is still shown.
    (b) Our side -- ``stale_on_our_side``: OUR last successful fetch/check is older than our own
        schedule. That is our fault, never the publisher's; the UI and /our-data say so.

    Rule: we only call a publisher late when our own check is current. If we are stale we do not
    know whether they published since, so ``late_to_refresh`` must be False.
    Build these with ``Freshness.compute`` so every producer applies the same cadences.
    """

    last_updated: date | None = Field(
        description="(a) The source's own date: file last_updated_on, fee schedule effective date, "
        "date printed on a clinic page. None = the source states no date."
    )
    expected_by: date | None = Field(
        description="(a) When the publisher owed a newer version under source_rule. None = no deadline."
    )
    late_to_refresh: bool = Field(
        description="(a) publisher past its deadline (and our check is current)"
    )
    source_rule: SourceCadence
    fetched_at: date = Field(description="(b) our last successful fetch / check of this source")
    our_refresh_due: date | None = Field(
        description="(b) when our next fetch/check was due under our_rule. None = no newer release known."
    )
    stale_on_our_side: bool = Field(description="(b) we are behind our own schedule")
    our_rule: OurCadence

    @model_validator(mode="after")
    def _two_sides(self) -> Freshness:
        if self.late_to_refresh and self.expected_by is None:
            raise ValueError("late_to_refresh needs expected_by (the deadline that was missed)")
        if (
            self.last_updated is not None
            and self.expected_by is not None
            and self.expected_by < self.last_updated
        ):
            raise ValueError("expected_by cannot be before last_updated")
        if self.stale_on_our_side and self.our_refresh_due is None:
            raise ValueError("stale_on_our_side needs our_refresh_due (the schedule we missed)")
        if self.late_to_refresh and self.stale_on_our_side:
            raise ValueError(
                "cannot blame the publisher while our own check is stale: refresh first"
            )
        return self

    @classmethod
    def compute(
        cls,
        *,
        as_of: date,
        source_rule: SourceCadence,
        last_updated: date | None,
        our_rule: OurCadence,
        fetched_at: date,
        expected_by: date | None = None,
        our_refresh_due: date | None = None,
    ) -> Freshness:
        """The one implementation of both cadences. Day-based rules derive the deadline; release
        rules (fee schedules) take the next release date explicitly."""
        days = SOURCE_DEADLINE_DAYS[source_rule]
        if days is not None:
            expected_by = last_updated + timedelta(days=days) if last_updated else None
        our_days = OUR_DEADLINE_DAYS[our_rule]
        if our_days is not None:
            our_refresh_due = fetched_at + timedelta(days=our_days)
        stale = our_refresh_due is not None and as_of > our_refresh_due
        late = (not stale) and expected_by is not None and as_of > expected_by
        return cls(
            last_updated=last_updated,
            expected_by=expected_by,
            late_to_refresh=late,
            source_rule=source_rule,
            fetched_at=fetched_at,
            our_refresh_due=our_refresh_due,
            stale_on_our_side=stale,
            our_rule=our_rule,
        )

    def at(self, as_of: date) -> Freshness:
        """The same inputs evaluated on ``as_of``. Served freshness is computed per request, never
        frozen at build time: an image nobody rebuilt must still turn "stale on our side"."""
        return Freshness.compute(
            as_of=as_of,
            source_rule=self.source_rule,
            last_updated=self.last_updated,
            our_rule=self.our_rule,
            fetched_at=self.fetched_at,
            expected_by=self.expected_by,
            our_refresh_due=self.our_refresh_due,
        )


# --------------------------------------------------------------------------- site parts


SiteType = Literal[
    "urgent_care",
    "hospital_outpatient",
    "ortho_walk_in",
    "specialist_office",
    "primary_care_office",
    "imaging_center",
    "ambulatory_surgery_center",
]

BillingType = Literal["office_visit", "hospital_outpatient", "asc", "unknown"]
"""office_visit: one professional/global bill. hospital_outpatient: the hospital adds a facility
fee on top of the doctor's fee (e.g. MGH Chelsea). asc: an ambulatory surgery center bills its
facility fee plus the doctor (and anesthesia) separately (colonoscopy centers). unknown: not
established yet (UI says so)."""

ListingStatus = Literal["web_verified", "multi_registry", "registry_only"]
"""How sure we are the site exists and is open. registry_only sites (one registry, no web
confirmation) wait in the to-verify queue and are never quoted (D27 / census D7)."""

TIN_RE = r"^[0-9]{9}$"  # EIN digits only, the form TiC provider groups join on
CENSUS_ID_RE = r"^GB[0-9]{4}$"  # research-v3/clinic-census.csv site_id (also TiC tic_site_ids)


def normalize_tin(raw: str) -> str:
    """'04-3026897' / '043026897' / ' 04 3026897 ' -> '043026897' (P1 problem 4). A TiC file prints
    an EIN with a dash; the census and Site.tins keep digits only. Not 9 digits -> ValueError."""
    d = re.sub(r"[\s-]", "", raw or "")
    if not re.fullmatch(r"[0-9]{9}", d):
        raise ValueError(f"not an EIN: {raw!r}")
    return d


Ownership = Literal[
    "hospital_system",
    "independent_group",
    "pe_backed_chain",
    "franchise",  # one brand, franchisee-owned PCs (AFC)
    "payer_owned",  # owned by an insurer's group (Atrius -> Optum / UnitedHealth)
    "community_health_center",  # FQHC / community health center
    "retail",  # pharmacy / retail clinic (MinuteClinic)
    "unknown",
]
"""D27 / census D3. Name- and TIN-based; PE / payer backing is [unverified] unless a source says so."""

BillingConfidence = Literal["stated", "likely", "unknown"]
"""stated: an operator billing page or a hospital-satellite licence says so; likely: registry
evidence (census ``*_likely``); unknown: not established."""

OfferedService = Literal[
    "visit", "xray", "mri", "ct", "ultrasound", "imaging", "joint_injection", "physical_therapy",
    "endoscopy", "skin_biopsy", "lab",
]  # fmt: skip


def check_npi(n: str, *, placeholders_ok: bool = False) -> str:
    """A CMS NPI is 10 digits starting with 1 or 2. Fixtures may use 000000000x placeholders."""
    if not (len(n) == 10 and n.isdigit()):
        raise ValueError(f"bad NPI {n!r}")
    if n[0] not in "12" and not placeholders_ok:
        raise ValueError(f"NPI {n!r} does not start with 1 or 2 (placeholder?)")
    return n


ServiceArea = Literal["ortho", "skin", "gi", "urgent_care"]

Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Address(_Strict):
    street: str
    city: str
    state: str = Field(default="MA", pattern=r"^[A-Z]{2}$")
    zip: str = Field(pattern=r"^[0-9]{5}$")


class Coordinates(_Strict):
    lat: float = Field(ge=41.0, le=43.5, description="Greater Boston scope guard")
    lon: float = Field(ge=-72.5, le=-69.5)
    geocoded_by: Literal["census_batch", "operator_page", "manual", "hospital_registry"]
    geocoded_at: date


class HoursSpan(_Strict):
    days: list[Day] = Field(min_length=1)
    opens: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    closes: str = Field(pattern=r"^([01][0-9]|2[0-4]):[0-5][0-9]$")


class Hours(_Strict):
    source: Literal["on_my_way", "operator_html", "operator_schema_org", "manual"]
    source_url: str | None
    checked_at: date
    weekly: list[HoursSpan] = Field(
        default_factory=list, description="Empty = by appointment / unknown"
    )
    may_close_early: bool = Field(
        default=False, description="Operator warns hours vary with clinical capacity"
    )


BookingKind = Literal["deep_link", "iframe_mgb", "walk_in", "call"]
BookingProvider = Literal[
    "on_my_way",  # Epic On My Way (BILH / MGB urgent care)
    "solv",
    "clockwise",
    "zocdoc",
    "mychart_open_scheduling",
    "operator_site",
    "phone",
    "none",  # walk-in with no booking at all
]


class BookingOption(_Strict):
    """D7: links only. The app never posts to these systems and never scrapes them."""

    kind: BookingKind
    provider: BookingProvider
    label: str = Field(description="Button text, e.g. 'Reserve a spot'")
    url: str | None = None
    phone: str | None = None

    @model_validator(mode="after")
    def _needs_target(self) -> BookingOption:
        if self.kind in ("deep_link", "iframe_mgb"):
            if not (self.url and self.url.startswith("https://")):
                raise ValueError(f"{self.kind} needs an https url")
        if self.kind == "call" and not self.phone:
            raise ValueError("call needs a phone number")
        return self


class PortalLink(_Strict):
    """D7: the health system's patient portal (MyChart, MGB Patient Gateway). Link only."""

    kind: Literal["mychart", "patient_gateway"]
    system_id: str = Field(pattern=ID_RE, description="e.g. mgb, bilh, bmc")
    label: str
    url: str

    @field_validator("url")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("portal url must be https")
        return v


class PostedCashPrice(_Strict):
    """A self-pay price the site posts on its own website (never Solv / MyChart / Zocdoc).

    Written only after Austin approves the weekly price checker's diff.
    """

    item_id: str = Field(pattern=ID_RE, description="stable within the site, e.g. xray_2_views")
    label: str = Field(description="As the site words it, e.g. 'X-ray, 2 views'")
    codes: list[str] = Field(
        default_factory=list, description="CPT/HCPCS we map it to; empty = no confident mapping"
    )
    amount: float = Field(ge=0)
    includes_provider_fee: bool | None = Field(
        description="True when the posted price covers the clinician's own fee too; None = unclear"
    )
    add_on_to_visit: bool = Field(
        default=False, description="Site says 'plus the visit price' (Carbon Health X-rays)"
    )
    source_url: str
    final_url: str | None = Field(
        default=None, description="After redirects; checker rejects a redirect"
    )
    checked_at: date
    page_sha256: str | None = Field(
        default=None, description="sha256 of the checker's normalized JSON of the price table"
    )

    @field_validator("codes")
    @classmethod
    def _codes(cls, v: list[str]) -> list[str]:
        for c in v:
            if not re.match(CODE_RE, c):
                raise ValueError(f"bad CPT/HCPCS code {c!r}")
        return v

    @field_validator("source_url")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("source_url must be https")
        return v


class Offered(_Strict):
    """P1 problem 14: evidence that a site offers a service. Only positive evidence is recorded;
    the absence of an entry means "not known", never "not offered"."""

    service: OfferedService
    codes: list[str] = Field(
        default_factory=list, description="CPT/HCPCS when the source names them"
    )
    evidence: Literal["posted_price", "operator_page", "dph_license", "census_category"]
    source: str = Field(description="URL or registry row the evidence came from")
    checked_at: date

    @field_validator("codes")
    @classmethod
    def _codes(cls, v: list[str]) -> list[str]:
        for c in v:
            if not re.match(CODE_RE, c):
                raise ValueError(f"bad CPT/HCPCS code {c!r}")
        return v


class Site(_Strict):
    id: str = Field(pattern=ID_RE)
    census_id: str | None = Field(
        default=None,
        pattern=CENSUS_ID_RE,
        description="clinic-census row; TiC rows carry it in tic_site_ids (P1 problem 4)",
    )
    name: str
    site_type: SiteType
    operator: str = Field(description="Who runs it, e.g. 'BILH', 'AFC franchise', 'Carbon Health'")
    system_id: str | None = Field(
        default=None, pattern=ID_RE, description="Health system id (mgb, bilh, bmc ...) if any"
    )
    hospital_entity_id: str | None = Field(
        default=None,
        pattern=ID_RE,
        description="data/registries/hospitals.yaml id whose price file prices this site "
        "(hospital_outpatient sites); None for independent clinics",
    )
    billing_type: BillingType
    billing_type_source: str | None = Field(
        default=None, description="URL or note that established billing_type"
    )
    billing_type_confidence: BillingConfidence = "unknown"
    ownership: Ownership = "unknown"
    ownership_detail: str | None = None
    children_only: bool = Field(
        default=False, description="Pediatric-only site: the UI shows 'children only' (D27)"
    )
    address: Address
    coords: Coordinates
    phone: str | None = None
    hours: Hours | None = None
    booking: list[BookingOption] = Field(default_factory=list)
    portal_links: list[PortalLink] = Field(default_factory=list)
    service_areas: list[ServiceArea] = Field(min_length=1)
    type_2_npis: list[str] = Field(default_factory=list)
    tins: list[str] = Field(
        default_factory=list,
        description="Billing TINs (9 digits) that price this site in TiC files. Match by TIN, "
        "never by name: one AFC franchise bills under several TINs.",
    )
    tins_source: str | None = Field(
        default=None, description="Where the TINs came from (NPPES, TiC match, census row)"
    )
    tin_npis: list[str] = Field(
        default_factory=list,
        description="TiC provider groups whose tin.type is 'npi' (a 10-digit NPI used as the TIN)",
    )
    offered: list[Offered] = Field(default_factory=list, description="P1 problem 14")
    listing_status: ListingStatus
    listing_checked_at: date
    cash_prices: list[PostedCashPrice] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("type_2_npis")
    @classmethod
    def _npi10(cls, v: list[str], info: ValidationInfo) -> list[str]:
        for n in v:
            check_npi(n, placeholders_ok=placeholders_allowed(info))
        return v

    @field_validator("tins")
    @classmethod
    def _tins(cls, v: list[str]) -> list[str]:
        for t in v:
            if not re.match(TIN_RE, t):
                raise ValueError(f"TIN {t!r} must be 9 digits (no dash)")
        if len(v) != len(set(v)):
            raise ValueError("duplicate TIN")
        return v

    @model_validator(mode="after")
    def _billing(self) -> Site:
        if self.site_type == "hospital_outpatient" and self.billing_type == "office_visit":
            raise ValueError(f"{self.id}: a hospital outpatient site cannot bill as office_visit")
        if (self.billing_type == "asc") != (self.site_type == "ambulatory_surgery_center"):
            if self.billing_type == "asc" or self.billing_type != "unknown":
                raise ValueError(f"{self.id}: billing_type asc <=> an ambulatory surgery center")
        if (self.tins or self.tin_npis) and not self.tins_source:
            raise ValueError(f"{self.id}: tins need tins_source")
        for n in self.tin_npis:
            check_npi(n)
        ids = [p.item_id for p in self.cash_prices]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.id}: duplicate cash price item_id")
        return self


class SitesFile(_Strict):
    """``data/sites/sites.yaml``."""

    version: int
    sites: list[Site]

    @field_validator("sites")
    @classmethod
    def _unique(cls, v: list[Site]) -> list[Site]:
        ids = [s.id for s in v]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"duplicate site id(s) {sorted(dup)}")
        return v
