"""Typed schema for CareCost clinical content (care paths, questions, red flags, glossary).

Three ideas the schema keeps apart on purpose (clinical-sources.md §5.1):
  appropriateness  -- "should a doctor order this here?"  (guideline rating, normative)
  likelihood_tier  -- "how often does it happen?"        (bounded above by appropriateness, V3)
  plain.why        -- "why would they do it?"            (our words, cited)

English is the primary language for all user-facing copy; Chinese is optional (titles, red flags).
CPT codes live only in `cpts` (price layer) and never in user-facing strings (V6).
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.care_paths.text import word_count

CONNECT_CPT_OID = "2.16.840.1.113883.6.12"
QUOTE_MAX_WORDS = 15

Tier = Literal["certain", "likely", "possible", "rare"]
TIER_ORDER: dict[str, int] = {"rare": 0, "possible": 1, "likely": 2, "certain": 3}

Rating = Literal[
    # ACR Appropriateness Criteria
    "UA",
    "MBA",
    "UNA",
    # AAOS strength of recommendation
    "aaos_strong",
    "aaos_moderate",
    "aaos_limited",
    "aaos_consensus",
    # USPSTF grades
    "uspstf_A",
    "uspstf_B",
    "uspstf_C",
    "uspstf_D",
    "uspstf_I",
    # ACG (GRADE)
    "acg_strong",
    "acg_conditional",
    # Not a test a guideline rates: the visit itself, a plan rule, or a step implied by another step
    "standard_of_care",
    "plan_rule",
    "implied_by_parent",
]

SourceTier = Literal["guideline", "government", "society_patient_page", "secondary"]
StepKind = Literal[
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
ReviewStatus = Literal["pending_austin", "changes_requested", "approved"]
ReviewerKind = Literal["human_clinician", "human_nonclinician", "ai"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- sources


class AcrVariant(_Strict):
    description: str
    requires_prior_radiographs: bool
    ratings: dict[str, Literal["UA", "MBA", "UNA"]]


class Source(_Strict):
    title: str
    publisher: str
    year: int
    url: str
    pages: list[str] = Field(
        default_factory=list, description="when one source spans several pages (fetched for checks)"
    )
    tier: SourceTier
    license: Literal[
        "public_domain_us_gov", "copyrighted_link_only", "uk_open_government_licence_v3"
    ]
    jurisdiction: str = "US"
    checked_at: dt.date
    recheck_after_days: int = Field(gt=0)
    fetched_text_sha256: str | None = None
    excerpts: list[str] = Field(default_factory=list)
    acr_variants: dict[int, AcrVariant] | None = None


class SourceRegistry(_Strict):
    sources: dict[str, Source]


# --------------------------------------------------------------------------- care path parts


class Citation(_Strict):
    """Where a claim comes from. `doc` is a key in data/care_paths/sources.yaml."""

    doc: str
    year: int
    section: str
    url: str
    quote: str = Field(min_length=3)
    claim_field: Literal["why", "what", "when_skipped", "appropriateness", "coverage", "intro"]

    @field_validator("quote")
    @classmethod
    def _short_quote(cls, v: str) -> str:
        if word_count(v) > QUOTE_MAX_WORDS:
            raise ValueError(f"quote must be <= {QUOTE_MAX_WORDS} words (copyright + V2)")
        return v


class Appropriateness(_Strict):
    rating: Rating
    source: str | None = None
    variant: int | None = None
    procedure: str | None = Field(
        default=None, description="ACR procedure label exactly as in the rating table"
    )
    note: str | None = None

    @model_validator(mode="after")
    def _acr_needs_locator(self) -> Appropriateness:
        if self.rating in ("UA", "MBA", "UNA") and (
            self.source is None or self.variant is None or self.procedure is None
        ):
            raise ValueError("ACR ratings need source + variant + procedure")
        if self.rating in ("standard_of_care", "implied_by_parent") and not self.note:
            raise ValueError(f"{self.rating} needs a note explaining the basis")
        return self


class Plain(_Strict):
    """User-facing copy (English). D8: `name` leads in plain words; `technical_name` is small text."""

    name: str
    technical_name: str
    what: str
    why: str
    when_skipped: str
    how_long: str | None = None
    prep: str | None = None


class CptRef(_Strict):
    code: str = Field(pattern=r"^([0-9]{4}[0-9A-Z]|[A-Z][0-9]{4})$")
    role: Literal["primary", "alternative", "add_on", "drug", "guidance"]
    payer_scope: Literal["all", "commercial", "medicare"] = "all"
    modifier: str | None = None
    mapping: Literal["confirmed_pfs", "asserted"] = Field(
        description="confirmed_pfs: exists in PFS and research cited it for this step without "
        "doubt. asserted: exists in PFS but research flagged the step-to-code mapping [断言]."
    )
    note: str | None = None


class LearnMore(_Strict):
    kind: Literal["medlineplus_connect", "link_out"]
    label: str
    url: str
    code: str | None = None
    resolved_title: str | None = None

    @model_validator(mode="after")
    def _connect_needs_code(self) -> LearnMore:
        if self.kind == "medlineplus_connect" and not self.code:
            raise ValueError("medlineplus_connect links need the code they were resolved from")
        return self


class AiPotential(_Strict):
    """Something an AI thinks may be billed too. Shown in a dashed box, never in the total."""

    label: Literal["AI-suggested"]
    text: str
    ai_generated: Literal[True]
    cpts: list[CptRef] = Field(default_factory=list)


class Step(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    layer: Literal[0, 1, 2]
    parent: str | None = None
    after: list[str] = Field(
        default_factory=list, description="steps that must have happened before this one"
    )
    kind: StepKind
    condition: dict[str, list[str]] | None = Field(
        default=None, description="only shown when these answers hold (e.g. layer-0 referral)"
    )
    appropriateness: Appropriateness
    likelihood_tier: Tier
    travels_with: str | None = Field(
        default=None, description="billed whenever this other step happens (e.g. pathology)"
    )
    plain: Plain
    when_skipped_basis: Literal["clinical", "logic", "plan_rule"] = "clinical"
    citations: list[Citation] = Field(min_length=1)
    cpts: list[CptRef] = Field(default_factory=list)
    no_price: bool = False
    no_price_reason: str | None = None
    glossary: list[str] = Field(default_factory=list)
    learn_more: list[LearnMore] = Field(default_factory=list)
    ai_potential: list[AiPotential] = Field(default_factory=list)
    reviewer_note: str | None = None

    def all_codes(self) -> set[str]:
        codes = {c.code for c in self.cpts}
        for item in self.ai_potential:
            codes |= {c.code for c in item.cpts}
        return codes


class Entry(_Strict):
    all_of: dict[str, list[str]] = Field(default_factory=dict)
    any_of: list[dict[str, list[str]]] = Field(default_factory=list)
    none_of: dict[str, list[str]] = Field(default_factory=dict)


class TierModifier(_Strict):
    when: dict[str, list[str]]
    step: str
    tier: Tier
    appropriateness: Appropriateness | None = Field(
        default=None, description="when the answer moves the step to a different guideline variant"
    )
    note: str | None = None


class GoldenCase(_Strict):
    name: str
    answers: dict[str, str | list[str]]
    expect: str
    expect_tiers: dict[str, Tier] = Field(default_factory=dict)


class Exit(_Strict):
    when: str
    text: str
    citations: list[Citation] = Field(default_factory=list)


class Reviewer(_Strict):
    id: str
    kind: ReviewerKind
    at: dt.date | None
    verdict: Literal["ok", "changes_requested"] | None


class Review(_Strict):
    status: ReviewStatus
    drafted_by: str
    drafted_at: dt.date | None = None
    reviewers: list[Reviewer] = Field(default_factory=list)

    @model_validator(mode="after")
    def _two_person_rule(self) -> Review:
        for r in self.reviewers:
            if r.kind == "ai" or r.id.startswith("ai:") or r.id == self.drafted_by:
                raise ValueError(f"reviewer {r.id!r} is the drafter or an AI; it cannot review")
        if self.status == "approved":
            ok = {r.id for r in self.reviewers if r.verdict == "ok" and r.at is not None}
            if len(ok) < 2:
                raise ValueError("approved needs >= 2 distinct human reviewers with verdict ok")
        return self


class Title(_Strict):
    en: str
    zh: str | None = None


class Scope(_Strict):
    area: Literal[
        "msk_shoulder", "msk_knee", "msk_back", "msk_ankle", "skin", "gi_upper", "gi_lower"
    ]
    acuity: Literal["acute", "chronic", "preventive", "subacute"]
    severity_band: list[Literal["minor", "moderate"]]


class CarePath(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+_v[0-9]+$")
    version: str
    title: Title
    intro: str
    scope: Scope
    priority: int = 0
    entry: Entry
    red_flags: list[str]
    glossary: list[str] = Field(default_factory=list)
    intro_citations: list[Citation] = Field(min_length=1)
    steps: list[Step] = Field(min_length=1)
    tier_modifiers: list[TierModifier] = Field(default_factory=list)
    exits: list[Exit] = Field(default_factory=list)
    coverage_note: str | None = None
    coverage_citations: list[Citation] = Field(default_factory=list)
    golden_cases: list[GoldenCase] = Field(default_factory=list)
    clinical_uncertainties: list[str] = Field(default_factory=list)
    review: Review

    @model_validator(mode="after")
    def _graph_refs(self) -> CarePath:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.id}: duplicate step ids")
        known = set(ids)
        for s in self.steps:
            for ref in [s.parent, s.travels_with, *s.after]:
                if ref is not None and ref not in known:
                    raise ValueError(f"{self.id}.{s.id}: unknown step reference {ref!r}")
        for m in self.tier_modifiers:
            if m.step not in known:
                raise ValueError(f"{self.id}: modifier targets unknown step {m.step!r}")
        return self


# --------------------------------------------------------------------------- questions


class Answer(_Strict):
    value: str = Field(pattern=r"^[a-z0-9_]+$")
    label: Title
    routes_to: list[str] = Field(min_length=1)


class Question(_Strict):
    id: str = Field(pattern=r"^Q[0-9]+$")
    text: Title
    slot: str
    applies_to: list[str]
    multi: bool = False
    answers: list[Answer]
    sources: list[str] = Field(default_factory=list)
    note: str | None = None


class Card(_Strict):
    """A message instead of (exit) or alongside (note) a care path, chosen by answers like a path."""

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    kind: Literal["exit", "note"]
    when_any: list[dict[str, list[str]]] = Field(min_length=1)
    title: Title
    text: str
    citations: list[Citation] = Field(default_factory=list)


class QuestionSet(_Strict):
    version: str
    review: Review
    questions: list[Question]
    cards: list[Card]


# --------------------------------------------------------------------------- red flags


class Disposition(_Strict):
    id: Literal["call_911", "er_today", "seen_today", "routine"]
    rank: int
    headline: Title
    text: Title


class BiText(_Strict):
    en: str
    zh: str


class RedFlag(_Strict):
    id: str = Field(pattern=r"^rf_[a-z0-9_]+$")
    areas: list[str]
    disposition: Literal["call_911", "er_today", "seen_today", "routine"]
    checklist: BiText
    in_checklist: bool = True
    patterns: list[list[list[str]]] = Field(
        description="any pattern matches; a pattern is a list of term groups that must all appear; "
        "a group matches if any of its terms appears (not negated)"
    )
    sources: list[str]
    mapping_note: str | None = None


class RedFlagSet(_Strict):
    version: str
    doc: str = ""
    review: Review
    areas: list[str]
    path_areas: dict[str, list[str]]
    dispositions: list[Disposition]
    flags: list[RedFlag]


# --------------------------------------------------------------------------- glossary


class LinkOut(_Strict):
    label: str
    url: str


class GlossaryTerm(_Strict):
    plain_name: str
    technical_name: str
    short: str
    zh_plain_name: str | None = None
    based_on: str = Field(description="source id; must be public domain (paraphrased, credited)")
    triggers: list[str] = Field(min_length=1)
    link_out: list[LinkOut] = Field(default_factory=list)


class Glossary(_Strict):
    version: str
    review: Review
    credit: str
    terms: dict[str, GlossaryTerm]


# --------------------------------------------------------------------------- code registries


class CptEntry(_Strict):
    status: str
    has_professional_technical_split: bool


class CptRegistry(_Strict):
    source_file: str
    source_sha256: str
    release: str
    status_legend: dict[str, str]
    codes: dict[str, CptEntry]


class ConnectCheck(_Strict):
    checked_at: dt.date
    endpoint: str
    resolves: dict[str, list[str]]
    no_result: list[str]
