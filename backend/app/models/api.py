"""Pydantic request/response models for public API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, EmailStr

# --- Intake ---


class IntakeRequest(BaseModel):
    full_name: str | None = None
    date_of_birth: str | None = None
    zip: str | None = None
    phone: str | None = None
    insurance_carrier: str | None = None
    plan_name: str | None = None
    member_id: str | None = None
    plan_type: str | None = None
    deductible_cents: int | None = None
    oop_max_cents: int | None = None
    copay_cents: int | None = None
    coinsurance_pct: int | None = None
    care_focus: str | None = None
    symptoms: list[str] | None = None
    symptom_severity: str | None = None
    free_text: str | None = None


class IntakeResponse(BaseModel):
    normalized: dict[str, Any]
    missing_required: list[str]


# --- Confirm (LLM) ---


class ConfirmRequest(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class FollowUpQuestion(BaseModel):
    id: str
    text: str


class ConfirmResponse(BaseModel):
    missing_fields: list[str]
    follow_up_questions: list[FollowUpQuestion]
    suggested_updates: dict[str, Any]


class ConfirmApplyRequest(BaseModel):
    fields: dict[str, Any]
    answers: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class ConfirmApplyResponse(BaseModel):
    normalized: dict[str, Any]
    missing_required: list[str]
    ready_for_estimate: bool


# --- Estimate ---


class ProvenanceItem(BaseModel):
    field: str
    source: str
    confidence: float
    kind: Literal["FACT", "ASSUMED"]


class AllowedAmountRange(BaseModel):
    min: int
    max: int
    currency: Literal["USD"] = "USD"


class OopRange(BaseModel):
    min: int
    max: int
    label: str | None = None


class ProviderEstimate(BaseModel):
    provider_id: str
    allowed_amount_range: AllowedAmountRange
    oop_range: OopRange
    provenance: list[ProvenanceItem]
    assumptions: list[str]
    other_insurers_oop_range: OopRange | None = Field(
        default=None,
        description="OOP band across other payers (min of lower bounds, max of upper bounds).",
    )
    payer_used: str | None = Field(
        default=None,
        description="Payer key used for primary oop_range (matches prices.payer).",
    )


class EstimateRequest(BaseModel):
    intake: dict[str, Any]
    confirmed: dict[str, Any] | None = None
    scenario_id: str | None = None
    bundle_id: str | None = None


class EstimateResponse(BaseModel):
    bundle_id: str
    scenario_id: str
    providers: list[dict[str, Any]]
    estimates: list[ProviderEstimate]


class ProviderListItem(BaseModel):
    id: str
    name: str
    address: str
    city: str
    zip: str
    lat: float
    lng: float
    phone: str | None = None
    specialties: list[str]
    source: str | None = None
    hospital: str | None = None


class ProvidersQuery(BaseModel):
    bbox: str | None = None
    zip: str | None = None
    hospital: str | None = None
    in_network_only: bool | None = None
    specialty: str | None = None


# --- Auth ---


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    sub: str
    email: str | None = None


# --- Users ---


class UserMeResponse(BaseModel):
    sub: str
    email: EmailStr | None = None
    user_profile: dict[str, Any] | None = None
    insurance_profile: dict[str, Any] | None = None


class UserMePatch(BaseModel):
    user_profile: dict[str, Any] | None = None
    insurance_profile: dict[str, Any] | None = None
