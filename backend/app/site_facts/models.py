"""Shapes of the X1 files: capabilities.yaml, a run file, facts.yaml.

A run file is X1 ``facts.yaml`` without ``status`` plus a header naming the run. Value rules:

* ``official_name``: the name exactly as the page writes it.
* ``phone``: the main phone for this site as written on the page (``617-555-0100``).
* ``hours``: ``[{days: [mon, ...], open: "08:00", close: "20:00"}]``, 24h clock, ``24:00`` allowed
  as a close; days the page lists as closed are simply left out.
* ``capabilities.<id>``: ``offered`` | ``not_offered`` | ``unknown``. ``offered`` and
  ``not_offered`` need evidence; ``unknown`` is the same as leaving it out.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TIME_RE = r"^([01][0-9]|2[0-3]):[0-5][0-9]$|^24:00$"
ID_RE = r"^[a-z0-9][a-z0-9_]*$"
Status = Literal["agreed", "austin_reviewed", "disputed"]
CapValue = Literal["offered", "not_offered", "unknown"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Label(_Strict):
    en: str = Field(min_length=1)
    zh: str = Field(min_length=1)


class Cover(_Strict):
    path: str = Field(pattern=ID_RE)
    step: str = Field(pattern=ID_RE)


class Capability(_Strict):
    label: Label
    covers: list[Cover]


class CapabilityFile(_Strict):
    version: Literal[1]
    capabilities: dict[str, Capability]

    @field_validator("capabilities")
    @classmethod
    def _ids(cls, v: dict[str, Capability]) -> dict[str, Capability]:
        bad = [k for k in v if not re.match(ID_RE, k)]
        if bad:
            raise ValueError(f"capability ids must be snake_case: {bad}")
        return v


class Evidence(_Strict):
    url: str = Field(pattern=r"^https://")
    quote: str = Field(min_length=3)
    fetched_at: str
    page_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HoursSpan(_Strict):
    days: list[Day] = Field(min_length=1)
    open: str = Field(pattern=TIME_RE)
    close: str = Field(pattern=TIME_RE)


# ------------------------------------------------------------------ run file (no status)


class RunText(_Strict):
    value: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class RunHours(_Strict):
    value: list[HoursSpan] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class RunCap(_Strict):
    value: CapValue
    evidence: list[Evidence] = Field(default_factory=list)


class RunSite(_Strict):
    official_name: RunText | None = None
    phone: RunText | None = None
    hours: RunHours | None = None
    capabilities: dict[str, RunCap] = Field(default_factory=dict)
    pages_read: list[str] = Field(default_factory=list)  # every URL the run looked at
    note: str | None = None


class RunFile(_Strict):
    version: Literal[1]
    run_id: str = Field(pattern=ID_RE)
    extracted_by: str = Field(
        min_length=1
    )  # who / which model, and that it did not see the other run
    extracted_at: str
    sites: dict[str, RunSite]


# ------------------------------------------------------------------ facts.yaml (X1)


class FactText(_Strict):
    value: str
    status: Status
    evidence: list[Evidence]


class FactHours(_Strict):
    value: list[HoursSpan]
    status: Status
    evidence: list[Evidence]


class FactCap(_Strict):
    value: CapValue
    status: Status
    evidence: list[Evidence]


class FactSite(_Strict):
    official_name: FactText | None = None
    phone: FactText | None = None
    hours: FactHours | None = None
    capabilities: dict[str, FactCap] = Field(default_factory=dict)


class FactsFile(_Strict):
    version: Literal[1]
    sites: dict[str, FactSite]


# ------------------------------------------------------------------ comparison keys


def norm_name(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.casefold().replace("&", " and ")))


def norm_phone(s: str) -> str:
    d = re.sub(r"\D", "", s)
    return d[1:] if len(d) == 11 and d.startswith("1") else d


def norm_hours(spans: list[HoursSpan]) -> tuple[tuple[str, str, str], ...]:
    per_day = sorted({(d, s.open, s.close) for s in spans for d in s.days},
                     key=lambda x: (DAYS.index(x[0]), x[1]))  # fmt: skip
    return tuple(per_day)
