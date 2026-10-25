"""Chat API contract (wave 2.0). Contract models ONLY. Provider-agnostic (Gemini free tier in dev,
Lava-prepaid in prod): nothing here names a model or a vendor.

Order of work on the server for every message (the contract makes the order visible):

1. Budget gate (D2): ~$1 per hashed IP per day soft cap, $2 hard stop, plus the prepaid wallet.
   Over the hard stop or wallet empty -> ``AiPausedReply``; browsing prices still works (D3).
2. Red-flag gate (redflags.json, deterministic): a hit -> ``RedFlagReply``. No prices, no LLM call.
3. Only then the LLM, whose output is forced into one of: ``ClarifyReply`` (question ids from
   questions.yaml only, rendered as chips, max 2), ``CarePathsReply`` (path ids from the catalog
   only), ``TextReply``.

Plain JSON, not streaming: see contracts/README.md ("Why plain JSON").

``python -m app.api_contracts`` regenerates ``contracts/chat_api.schema.json``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.quote.contracts import ANSWER_RE, PATH_ID_RE, QUESTION_ID_RE, Payment

Disposition = Literal["call_911", "crisis_988", "er_today", "seen_today", "routine"]
"""Exactly the four dispositions in data/redflags/redflags.json (a test keeps them equal)."""

MAX_QUESTIONS_PER_TURN = 2
MAX_TEXT_CHARS = 2000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Title(_Strict):
    en: str
    zh: str | None = None


# --------------------------------------------------------------------------- request


class ChatRequest(_Strict):
    conversation_id: str | None = Field(
        pattern=r"^[A-Za-z0-9_-]{16,64}$",
        description="Opaque, issued by the server on the first reply; None on the first message",
    )
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    payment: Payment
    email: EmailStr = Field(
        description="D2: required before AI use, deliberately unverified. The only personal "
        "field in any CareCost contract."
    )
    answers: dict[str, list[str]] = Field(
        description="Chip answers so far, questions.yaml id -> answer values (client keeps state)",
    )
    locale: Literal["en", "zh"]

    @model_validator(mode="after")
    def _answers(self) -> ChatRequest:
        for q, vals in self.answers.items():
            if not re.match(QUESTION_ID_RE, q) or not all(re.match(ANSWER_RE, v) for v in vals):
                raise ValueError(f"answers must be question ids -> answer values, got {q!r}")
        return self


# --------------------------------------------------------------------------- reply variants


class RedFlagReply(_Strict):
    """Full-page stop (plan §4.1). Copy is copied verbatim from redflags.json `dispositions`."""

    kind: Literal["red_flag"]
    disposition: Disposition
    flag_ids: list[str] = Field(min_length=1, description="redflags.json flag ids (rf_*)")
    headline: Title
    text: Title
    prices_withheld: Literal[True] = True


class ChipAnswer(_Strict):
    value: str = Field(pattern=ANSWER_RE)
    label: Title


class ChipQuestion(_Strict):
    question_id: str = Field(pattern=QUESTION_ID_RE)
    text: Title
    multi: bool
    answers: list[ChipAnswer] = Field(min_length=1)


class CandidatePath(_Strict):
    path_id: str = Field(pattern=PATH_ID_RE)
    title: str
    match: Literal["entry_matched", "ai_ranked"] = Field(
        description="entry_matched: the answers satisfy the path's entry rule (deterministic). "
        "ai_ranked: the LLM picked it from the catalog."
    )
    review_status: Literal["pending_austin", "changes_requested", "approved"]


class ClarifyReply(_Strict):
    kind: Literal["clarify"]
    lead_in: str | None = Field(description="Short assistant sentence before the chips")
    questions: list[ChipQuestion] = Field(min_length=1, max_length=MAX_QUESTIONS_PER_TURN)
    candidates: list[CandidatePath] = Field(
        default_factory=list, description="Prices can show from turn one; questions only refine"
    )
    card_ids: list[str] = Field(default_factory=list, description="questions.yaml card ids")


class CarePathsReply(_Strict):
    kind: Literal["care_paths"]
    text: str
    candidates: list[CandidatePath] = Field(min_length=1)
    card_ids: list[str] = Field(default_factory=list)


class TextReply(_Strict):
    """Anything else: out of scope, 'not covered yet', a follow-up answer. No prices in text."""

    kind: Literal["text"]
    text: str
    card_ids: list[str] = Field(default_factory=list)


class AiPausedReply(_Strict):
    kind: Literal["ai_paused"]
    reason: Literal["ip_daily_cap", "wallet_exhausted", "provider_unavailable"]
    message_key: Literal["ai.paused_ip_cap", "ai.paused_wallet", "ai.paused_provider"]
    resumes_at: datetime | None = Field(description="UTC; None when unknown (wallet / provider)")
    browse_prices_available: Literal[True] = True


ChatReply = Annotated[
    Union[RedFlagReply, ClarifyReply, CarePathsReply, TextReply, AiPausedReply],
    Field(discriminator="kind"),
]


class BudgetStatus(_Strict):
    """D2. Per hashed IP per UTC day; the wallet is the prepaid ceiling (~$10)."""

    state: Literal["ok", "near_soft_cap", "over_soft_cap", "paused"]
    soft_cap_usd: float = Field(gt=0)
    hard_cap_usd: float = Field(gt=0)
    spent_today_usd: float = Field(ge=0)
    wallet: Literal["ok", "low", "exhausted"]
    resets_at: datetime

    @model_validator(mode="after")
    def _caps(self) -> BudgetStatus:
        if self.soft_cap_usd > self.hard_cap_usd:
            raise ValueError("soft cap must be <= hard cap")
        return self


class ChatResponse(_Strict):
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")
    reply: ChatReply
    budget: BudgetStatus
    llm_called: bool = Field(description="False for red-flag, ai_paused and cached replies")

    @model_validator(mode="after")
    def _gate_order(self) -> ChatResponse:
        if self.reply.kind in ("red_flag", "ai_paused") and self.llm_called:
            raise ValueError(f"{self.reply.kind} replies are decided before any LLM call")
        if (
            self.reply.kind == "ai_paused"
            and self.budget.state != "paused"
            and (self.reply.reason == "ip_daily_cap")
        ):
            raise ValueError("ip_daily_cap pause needs budget.state == paused")
        return self
