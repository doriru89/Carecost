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

``Freshness`` is shared with the quote contract: a source older than its refresh deadline is never
hidden. If it has data the data is shown, labelled "late to refresh" (Austin, 2026-10-24).

``python -m app.api_contracts`` regenerates ``contracts/site.schema.json``.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_RE = r"^[a-z0-9][a-z0-9_]*$"
CODE_RE = r"^([0-9]{4}[0-9A-Z]|[A-Z][0-9]{4})$"  # CPT / HCPCS (same rule as care_paths.CptRef)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- freshness


FreshnessRule = Literal[
    "etl_warn_after_days",  # hospital MRF: file's last_updated_on + gates.yaml staleness.warn_after_days
    "cms_annual",  # federal floor: 45 CFR 180.50(e), one year after last_updated_on
    "tic_monthly",  # insurer TiC files are due monthly
    "fee_schedule_effective",  # government fee schedule: the next effective date
    "posted_price_weekly_check",  # site's posted cash price: re-checked weekly by the price checker
    "hours_weekly_check",
]


class Freshness(_Strict):
    """How current one data source is. Explicit fields, never free text.

    ``late_to_refresh`` is computed by whoever builds the payload (ETL / quote engine) as
    ``as_of > expected_by``. A late source is still shown, with the "late to refresh" label.
    """

    last_updated: date | None = Field(
        description="The source's own date: file last_updated_on, fee schedule effective date, "
        "or the day a posted price was last checked. None = the source does not say."
    )
    expected_by: date | None = Field(
        description="When a newer version was due under `rule`. None = no deadline known."
    )
    late_to_refresh: bool
    rule: FreshnessRule

    @model_validator(mode="after")
    def _late_needs_deadline(self) -> Freshness:
        if self.late_to_refresh and self.expected_by is None:
            raise ValueError("late_to_refresh needs expected_by (the deadline that was missed)")
        if (
            self.last_updated is not None
            and self.expected_by is not None
            and self.expected_by < self.last_updated
        ):
            raise ValueError("expected_by cannot be before last_updated")
        return self


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

BillingType = Literal["office_visit", "hospital_outpatient", "unknown"]
"""office_visit: one professional/global bill. hospital_outpatient: the hospital adds a facility
fee on top of the doctor's fee (e.g. MGH Chelsea). unknown: not established yet (UI says so)."""

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


class Site(_Strict):
    id: str = Field(pattern=ID_RE)
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
    address: Address
    coords: Coordinates
    phone: str | None = None
    hours: Hours | None = None
    booking: list[BookingOption] = Field(default_factory=list)
    portal_links: list[PortalLink] = Field(default_factory=list)
    service_areas: list[ServiceArea] = Field(min_length=1)
    type_2_npis: list[str] = Field(default_factory=list)
    cash_prices: list[PostedCashPrice] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("type_2_npis")
    @classmethod
    def _npi10(cls, v: list[str]) -> list[str]:
        for n in v:
            if not (len(n) == 10 and n.isdigit()):
                raise ValueError(f"bad NPI {n!r}")
        return v

    @model_validator(mode="after")
    def _billing(self) -> Site:
        if self.site_type == "hospital_outpatient" and self.billing_type == "office_visit":
            raise ValueError(f"{self.id}: a hospital outpatient site cannot bill as office_visit")
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
