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

Registry membership is a real validator, not a fixture test: a ``ChatResponse`` only validates
with a ``ChatContext`` (``model_validate(data, context=ctx.as_context())``), which carries the
registries (catalog, questions.yaml, redflags.json, glossary), the request it answers and the LLM
call meter. Without one, validation fails, so the endpoint cannot skip the checks. Note for the
chat stream: do not declare ``response_model=ChatResponse`` on the route (FastAPI would
re-validate without the context); validate once with the context and return its JSON.

``python -m app.api_contracts`` regenerates ``contracts/chat_api.schema.json``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    model_validator,
)

from app.care_paths.loader import load_paths
from app.care_paths.models import CarePath
from app.care_paths.router import matches
from app.quote.contracts import (
    ANSWER_RE,
    PATH_ID_RE,
    QUESTION_ID_RE,
    Answers,
    Catalog,
    Payment,
    check_answers,
)
from app.sites.contracts import ID_RE

Disposition = Literal["call_911", "crisis_988", "er_today", "seen_today", "routine"]
"""Exactly the four dispositions in data/redflags/redflags.json (a test keeps them equal)."""

MAX_QUESTIONS_PER_TURN = 2
MAX_TEXT_CHARS = 2000
MAX_HISTORY_TURNS = 6  # P5b: earlier user turns the client may send back
MAX_HISTORY_CHARS = 4000
MAX_TURNS_PER_CONVERSATION = 12  # metrics F4: past this, the reply is ai_paused(conversation_cap)
MAX_LLM_ATTEMPTS = 2  # one retry at most; both attempts are charged (failure review F10)
MAX_LLM_TEXT_CHARS = 300
MAX_EVIDENCE_CHARS = 80

REPO_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------- LLM text filter

_MONEY_WORDS = r"(dollars?|usd|bucks|cents?|美元|美金|块钱|块|元)"
_LLM_TEXT_BANNED: list[tuple[str, re.Pattern[str]]] = [
    ("a currency symbol", re.compile(r"[$¥€£₹]")),
    (
        "an amount of money",
        re.compile(
            rf"[0-9零一二两三四五六七八九十百千万][0-9.,]*\s*(k|千|万)?\s*{_MONEY_WORDS}", re.I
        ),
    ),
    ("an amount of money", re.compile(r"\b(usd|dollars?)\s*[0-9]", re.I)),
    ("a price", re.compile(r"\b(costs?|price[sd]?|charges?|pay|fee)s?\b\D{0,12}[0-9]", re.I)),
    ("a billing code", re.compile(r"\b([0-9]{4}[0-9A-Z]|[A-Z][0-9]{4})\b")),
    (
        "a link",
        re.compile(
            r"https?://|www\.|\b[a-z0-9-]+\.(com|org|net|io|gov|edu|co|us|info|biz|ly|me|app)\b",
            re.I,
        ),
    ),
    ("an email address", re.compile(r"@")),
    ("a phone number", re.compile(r"\+?\d[\d\s().-]{6,}\d|\b1[-\s]?\d{3}[-\s]?[A-Z0-9]{3,}", re.I)),
    ("markup", re.compile(r"[<>]|\]\(")),
]


def check_llm_text(v: str) -> str:
    """Every string an LLM writes for the screen: one or two short sentences, no dollars, codes,
    links, phone numbers or markup. The UI supplies every number; the AI only explains."""
    if len(v) > MAX_LLM_TEXT_CHARS:
        raise ValueError(f"LLM text is over {MAX_LLM_TEXT_CHARS} chars")
    for what, rx in _LLM_TEXT_BANNED:
        if rx.search(v):
            raise ValueError(f"LLM text may not contain {what}: {v!r}")
    return v


LlmText = Annotated[str, AfterValidator(check_llm_text)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Title(_Strict):
    en: str
    zh: str | None = None


# --------------------------------------------------------------------------- request


class Focus(_Strict):
    care_path_id: str | None = Field(pattern=PATH_ID_RE)
    site_id: str | None = Field(pattern=ID_RE)
    line_id: str | None = Field(pattern=ID_RE)

    @model_validator(mode="after")
    def _line_needs_site(self) -> Focus:
        if self.line_id is not None and self.site_id is None:
            raise ValueError("focus.line_id needs focus.site_id (lines are per site)")
        return self


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
    answers: Answers = Field(
        description="Chip answers so far, questions.yaml id -> answer values (client keeps state)",
    )
    history: list[Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS)]] = Field(
        max_length=MAX_HISTORY_TURNS,
        description="P5b: the person's own earlier messages, oldest first. Never assistant turns: "
        "a client-forged assistant turn is how the old route was broken.",
    )
    focus: Focus | None = Field(
        description="P5: the receipt line the person is asking about, so the server can paste our "
        "own sourced text for it into the prompt"
    )
    locale: Literal["en", "zh"]

    @model_validator(mode="after")
    def _answers(self) -> ChatRequest:
        check_answers(self.answers)
        if sum(len(t) for t in self.history) > MAX_HISTORY_CHARS:
            raise ValueError(f"history is over {MAX_HISTORY_CHARS} chars")
        return self

    def user_texts(self) -> list[str]:
        return [*self.history, self.text]


# --------------------------------------------------------------------------- reply variants


class RedFlagReply(_Strict):
    """Full-page stop (plan §4.1). Copy is copied verbatim from redflags.json `dispositions`."""

    kind: Literal["red_flag"]
    disposition: Disposition
    flag_ids: list[str] = Field(
        default_factory=list,
        description="redflags.json flag ids (rf_*); empty only when the LLM raised it",
    )
    escalated_by_llm: bool = Field(
        False, description="redflags.combine(): the LLM raised the disposition (one way only)"
    )
    headline: Title
    text: Title
    prices_withheld: Literal[True] = True

    @model_validator(mode="after")
    def _flags_or_llm(self) -> RedFlagReply:
        if not self.flag_ids and not self.escalated_by_llm:
            raise ValueError("a code-decided red flag names its flags")
        return self


class ChipAnswer(_Strict):
    value: str = Field(pattern=ANSWER_RE)
    label: Title


class ChipQuestion(_Strict):
    question_id: str = Field(pattern=QUESTION_ID_RE)
    text: Title
    multi: bool
    answers: list[ChipAnswer] = Field(min_length=1)


class BecauseAnswer(_Strict):
    """D33: one of the person's own chip answers that satisfied the path's entry rule. Built by
    the server from the request, never written by the LLM."""

    question_id: str = Field(pattern=QUESTION_ID_RE)
    value: str = Field(pattern=ANSWER_RE)
    label: Title = Field(description="The answer's label, verbatim from questions.yaml")


class CandidatePath(_Strict):
    path_id: str = Field(pattern=PATH_ID_RE)
    title: str
    match: Literal["entry_matched", "ai_ranked"] = Field(
        description="entry_matched: the answers satisfy the path's entry rule (deterministic). "
        "ai_ranked: the LLM picked it from the catalog."
    )
    review_status: Literal["pending_austin", "changes_requested", "approved"]
    because: list[BecauseAnswer] = Field(
        description="D33: why this path, as the person's own answers that matched its entry "
        "rule (question order). Empty for ai_ranked: the model's guess has no listed reason."
    )


CarePathCopyKey = Literal["copy.not_a_diagnosis", "copy.when_to_see_a_doctor"]
CARE_PATH_COPY_KEYS: tuple[str, ...] = ("copy.not_a_diagnosis", "copy.when_to_see_a_doctor")
"""D33: fixed copy shown with every reply that shows care paths (not LLM text)."""


def _check_copy_keys(candidates: list[CandidatePath], keys: list[str]) -> None:
    want = list(CARE_PATH_COPY_KEYS) if candidates else []
    if keys != want:
        raise ValueError(f"a reply showing care paths carries exactly {want} (D33)")


class InferredAnswer(_Strict):
    """P5: an answer the model read from the person's own words, shown as a pre-selected chip
    ("I understood: ... [change]"). Never the absence of something (no "none" values)."""

    question_id: str = Field(pattern=QUESTION_ID_RE)
    value: str = Field(pattern=ANSWER_RE)
    evidence: str = Field(
        min_length=1,
        max_length=MAX_EVIDENCE_CHARS,
        description="Verbatim substring of the person's own text that supports it",
    )


class ServiceRef(_Strict):
    """P5: a catalog service the model points at when no care path fits. The UI quotes it through
    the manual path with picked_by=assistant: shown, labelled, never summed."""

    service_id: str = Field(pattern=ID_RE)
    plain_name: str = Field(description="Filled from the catalog by id, never by the model")


class ClarifyReply(_Strict):
    kind: Literal["clarify"]
    lead_in: LlmText | None = Field(description="Short assistant sentence before the chips")
    understood: list[InferredAnswer] = Field(default_factory=list)
    questions: list[ChipQuestion] = Field(min_length=1, max_length=MAX_QUESTIONS_PER_TURN)
    candidates: list[CandidatePath] = Field(
        default_factory=list, description="Prices can show from turn one; questions only refine"
    )
    copy_keys: list[CarePathCopyKey] = Field(
        description="D33: not-a-diagnosis + when-to-see-a-doctor, whenever candidates show"
    )
    card_ids: list[str] = Field(default_factory=list, description="questions.yaml card ids")

    @model_validator(mode="after")
    def _copy(self) -> ClarifyReply:
        _check_copy_keys(self.candidates, list(self.copy_keys))
        return self


class CarePathsReply(_Strict):
    kind: Literal["care_paths"]
    text: LlmText
    understood: list[InferredAnswer] = Field(default_factory=list)
    candidates: list[CandidatePath] = Field(min_length=1)
    copy_keys: list[CarePathCopyKey] = Field(
        description="D33: not-a-diagnosis + when-to-see-a-doctor (fixed copy, not LLM text)"
    )
    card_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _copy(self) -> CarePathsReply:
        _check_copy_keys(self.candidates, list(self.copy_keys))
        return self


class TextReply(_Strict):
    """Anything else: out of scope, 'not covered yet', a follow-up answer. No prices in text."""

    kind: Literal["text"]
    text: LlmText
    card_ids: list[str] = Field(default_factory=list)
    services: list[ServiceRef] = Field(default_factory=list, max_length=3)
    glossary_keys: list[str] = Field(default_factory=list)
    focus_line_id: str | None = Field(
        default=None, description="The receipt line this explains: must be the request's focus"
    )


class LlmInvalidReply(_Strict):
    """The model answered but its output failed validation twice (one retry, both charged)."""

    kind: Literal["llm_invalid"]
    message_key: Literal["ai.output_invalid"]
    browse_prices_available: Literal[True] = True


class AiPausedReply(_Strict):
    kind: Literal["ai_paused"]
    reason: Literal["ip_daily_cap", "wallet_exhausted", "provider_unavailable", "conversation_cap"]
    message_key: Literal[
        "ai.paused_ip_cap", "ai.paused_wallet", "ai.paused_provider", "ai.paused_conversation_cap"
    ]
    resumes_at: AwareDatetime | None = Field(description="None when unknown (wallet / provider)")
    browse_prices_available: Literal[True] = True

    @model_validator(mode="after")
    def _key(self) -> AiPausedReply:
        if PAUSE_KEY[self.reason] != self.message_key:
            raise ValueError(f"{self.reason} needs message_key {PAUSE_KEY[self.reason]}")
        return self


PAUSE_KEY = {
    "ip_daily_cap": "ai.paused_ip_cap",
    "wallet_exhausted": "ai.paused_wallet",
    "provider_unavailable": "ai.paused_provider",
    "conversation_cap": "ai.paused_conversation_cap",
}

ChatReply = Annotated[
    Union[RedFlagReply, ClarifyReply, CarePathsReply, TextReply, LlmInvalidReply, AiPausedReply],
    Field(discriminator="kind"),
]


class BudgetStatus(_Strict):
    """D2 + metrics F2. Per hashed IP per provider day (the reset time zone is provider config:
    Gemini resets at midnight Pacific). Dollars and turns both count; whichever hits first pauses.
    The wallet is the prepaid ceiling (~$10)."""

    state: Literal["ok", "near_soft_cap", "over_soft_cap", "paused"]
    soft_cap_usd: float = Field(gt=0)
    hard_cap_usd: float = Field(gt=0)
    spent_today_usd: float = Field(ge=0)
    turns_today: int = Field(ge=0, description="LLM turns this IP used today, this one included")
    turn_cap: int = Field(gt=0, description="Per-IP daily turn cap (a share of the project RPD)")
    wallet: Literal["ok", "low", "exhausted"]
    resets_at: AwareDatetime

    @model_validator(mode="after")
    def _caps(self) -> BudgetStatus:
        if self.soft_cap_usd > self.hard_cap_usd:
            raise ValueError("soft cap must be <= hard cap")
        if self.turns_today > self.turn_cap:
            raise ValueError("turns_today cannot pass turn_cap (that turn should not have run)")
        spent_out = self.spent_today_usd >= self.hard_cap_usd
        if (spent_out or self.turns_today == self.turn_cap or self.wallet == "exhausted") and (
            self.state != "paused"
        ):
            raise ValueError("at the hard cap, the turn cap or an empty wallet, state is paused")
        return self


# --------------------------------------------------------------------------- registries + context


@dataclass(frozen=True)
class ChatRegistries:
    """The closed sets a reply may name, loaded from the content files (never hard-coded)."""

    questions: dict[str, dict[str, Any]]
    cards: frozenset[str]
    dispositions: dict[str, dict[str, Any]]
    flags: dict[str, str]  # flag id -> disposition id
    glossary: frozenset[str]
    catalog: Catalog
    paths: dict[str, CarePath]
    conditions: dict[str, tuple[str, ...]]  # D33 vocabulary: condition id -> names

    @classmethod
    def load(cls, catalog: Catalog, repo: Path = REPO_ROOT) -> ChatRegistries:
        qs = yaml.safe_load((repo / "data" / "questions" / "questions.yaml").read_text())
        rf = json.loads((repo / "data" / "redflags" / "redflags.json").read_text())
        gl = yaml.safe_load((repo / "content" / "glossary" / "glossary.yaml").read_text())
        cn = yaml.safe_load((repo / "data" / "chat" / "condition_names.yaml").read_text())
        return cls(
            questions={q["id"]: q for q in qs["questions"]},
            cards=frozenset(c["id"] for c in qs["cards"]),
            dispositions={d["id"]: d for d in rf["dispositions"]},
            flags={f["id"]: f["disposition"] for f in rf["flags"]},
            glossary=frozenset(gl["terms"]),
            catalog=catalog,
            paths=load_paths(repo / "data" / "care_paths" / "paths"),
            conditions={k: tuple(v) for k, v in cn["conditions"].items()},
        )

    def conditions_in(self, text: str) -> set[str]:
        """Condition ids whose names appear in ``text`` (case-insensitive, word boundaries)."""
        low = text.lower()
        return {
            cid
            for cid, names in self.conditions.items()
            if any(re.search(rf"(?<![a-z]){re.escape(n.lower())}(?![a-z])", low) for n in names)
        }

    def allowed_conditions(self, path_ids: list[str]) -> set[str]:
        """D33, derived: conditions the path's own title/intro names, or its glossary keys."""
        out: set[str] = set()
        for pid in path_ids:
            p = self.paths.get(pid)
            if p is not None:
                out |= self.conditions_in(f"{p.title.en} {p.intro}")
                out |= set(p.glossary) & set(self.conditions)
        return out

    def because(self, path_id: str, answers: dict[str, list[str]]) -> list[dict[str, Any]] | None:
        """D33: the person's answers that satisfy the path's entry rule (question order), or None
        when they do not satisfy it."""
        p = self.paths[path_id]
        if not matches(p, answers):
            return None
        e = p.entry
        used: dict[str, set[str]] = {}
        for cond in [
            e.all_of,
            *[c for c in e.any_of if all(set(answers.get(q, [])) & set(v) for q, v in c.items())],
        ]:
            for q, vals in cond.items():
                used.setdefault(q, set()).update(set(answers.get(q, [])) & set(vals))
        out = []
        for qid, q in self.questions.items():
            for a in q["answers"]:
                if a["value"] in used.get(qid, set()):
                    out.append({"question_id": qid, "value": a["value"], "label": a["label"]})
        return out

    def check_answers(self, answers: dict[str, list[str]]) -> None:
        for qid, vals in answers.items():
            q = self.questions.get(qid)
            if q is None:
                raise ValueError(f"unknown question {qid}")
            bad = set(vals) - {a["value"] for a in q["answers"]}
            if bad:
                raise ValueError(f"{qid}: unknown answers {sorted(bad)}")


@dataclass
class LlmMeter:
    """Counts provider calls. The LLM client wrapper calls ``record()`` once per call; the
    handler never sets ``llm_called`` itself (theater F7: a self-reported bool proves nothing)."""

    calls: int = 0

    def record(self) -> None:
        self.calls += 1


@dataclass
class ChatContext:
    registries: ChatRegistries
    request: ChatRequest
    meter: LlmMeter = field(default_factory=LlmMeter)
    conversation_turn: int = 1  # the server's own count for this conversation_id

    @classmethod
    def for_request(
        cls,
        request: ChatRequest,
        registries: ChatRegistries,
        meter: LlmMeter | None = None,
        conversation_turn: int = 1,
    ) -> ChatContext:
        """Refuses a request whose chip answers are not in questions.yaml (security F4)."""
        registries.check_answers(request.answers)
        return cls(registries, request, meter or LlmMeter(), conversation_turn)

    def as_context(self) -> dict[str, Any]:
        return {"chat": self}


def _check_reply(reply: Any, ctx: ChatContext) -> None:
    reg, kind = ctx.registries, reply.kind
    if kind == "red_flag":
        d = reg.dispositions.get(reply.disposition)
        if d is None:
            raise ValueError(f"disposition {reply.disposition} is not in redflags.json")
        if reply.headline.model_dump() != d["headline"] or reply.text.model_dump() != d["text"]:
            raise ValueError("red-flag copy must be verbatim from redflags.json")
        unknown = [f for f in reply.flag_ids if f not in reg.flags]
        if unknown:
            raise ValueError(f"unknown red flags {unknown}")
    if kind == "clarify":
        for chip in reply.questions:
            src = reg.questions.get(chip.question_id)
            if src is None:
                raise ValueError(f"unknown question {chip.question_id}")
            want = [(a["value"], a["label"]) for a in src["answers"]]
            got = [(a.value, a.label.model_dump()) for a in chip.answers]
            if chip.text.model_dump() != src["text"] or got != want:
                raise ValueError(
                    f"{chip.question_id}: chip text must be verbatim from questions.yaml"
                )
            if chip.multi != bool(src.get("multi")):
                raise ValueError(f"{chip.question_id}: multi must match questions.yaml")
    if kind in ("clarify", "care_paths"):
        paths = {p.id: p for p in reg.catalog.care_paths}
        for c in reply.candidates:
            p = paths.get(c.path_id)
            if p is None:
                raise ValueError(f"unknown care path {c.path_id}")
            if (c.title, c.review_status) != (p.title, p.review_status):
                raise ValueError(f"{c.path_id}: title and review_status come from the catalog")
            got = [b.model_dump() for b in c.because]
            if c.match == "entry_matched":
                want = reg.because(c.path_id, ctx.request.answers)
                if want is None:
                    raise ValueError(f"{c.path_id}: entry_matched but the answers miss its entry")
                if got != want:
                    raise ValueError(f"{c.path_id}: because must be the answers that matched")
            elif got:
                raise ValueError(f"{c.path_id}: an ai_ranked path lists no because")
        texts = ctx.request.user_texts()
        for u in reply.understood:
            reg.check_answers({u.question_id: [u.value]})
            if u.value == "none":
                raise ValueError("the model may infer a symptom, never its absence ('none')")
            if not any(u.evidence in t for t in texts):
                raise ValueError(f"{u.question_id}: evidence must quote the person's own words")
    if kind in ("clarify", "care_paths", "text"):
        # D33: condition names in LLM text only from the paths this reply shows
        if kind == "text":
            focus = ctx.request.focus
            shown = [focus.care_path_id] if focus and focus.care_path_id else []
            llm = [reply.text]
        else:
            shown = [c.path_id for c in reply.candidates]
            llm = [reply.lead_in or ""] if kind == "clarify" else [reply.text]
        extra = set().union(*(reg.conditions_in(t) for t in llm)) - reg.allowed_conditions(shown)
        if extra:
            raise ValueError(f"LLM text names conditions outside the care path: {sorted(extra)}")
        bad = set(reply.card_ids) - reg.cards
        if bad:
            raise ValueError(f"unknown cards {sorted(bad)}")
    if kind == "text":
        services = {s.service_id: s for s in reg.catalog.services}
        for s in reply.services:
            svc = services.get(s.service_id)
            if svc is None or svc.plain_name != s.plain_name:
                raise ValueError(f"service {s.service_id}: must be a catalog service, catalog name")
        if set(reply.glossary_keys) - reg.glossary:
            raise ValueError(
                f"unknown glossary keys {sorted(set(reply.glossary_keys) - reg.glossary)}"
            )
        focus = ctx.request.focus
        if reply.focus_line_id is not None and (
            focus is None or focus.line_id != reply.focus_line_id
        ):
            raise ValueError("focus_line_id must be the line the person asked about")


class ChatResponse(_Strict):
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")
    reply: ChatReply
    budget: BudgetStatus
    llm_called: bool = Field(
        description="From the LLM client's call meter, never set by the handler. False for "
        "red-flag, ai_paused and cached replies"
    )
    conversation_turn: int = Field(ge=1, description="The server's count for this conversation")

    @model_validator(mode="after")
    def _gate_order(self, info: ValidationInfo) -> ChatResponse:
        ctx = (info.context or {}).get("chat")
        if not isinstance(ctx, ChatContext):
            raise ValueError(
                "ChatResponse must be validated with a ChatContext (registries + request + LLM "
                "meter): model_validate(data, context=ctx.as_context())"
            )
        calls = ctx.meter.calls
        if self.llm_called != (calls > 0):
            raise ValueError(f"llm_called must come from the LLM meter ({calls} calls)")
        if calls > MAX_LLM_ATTEMPTS:
            raise ValueError(f"at most {MAX_LLM_ATTEMPTS} LLM attempts per turn (one retry)")
        if self.reply.kind == "llm_invalid" and calls == 0:
            raise ValueError("llm_invalid needs an LLM call")
        if self.conversation_turn != ctx.conversation_turn:
            raise ValueError("conversation_turn is the server's count")
        if self.conversation_turn > MAX_TURNS_PER_CONVERSATION and not (
            self.reply.kind == "ai_paused" and self.reply.reason == "conversation_cap"
        ):
            raise ValueError(
                f"past {MAX_TURNS_PER_CONVERSATION} turns the reply is conversation_cap"
            )
        _check_reply(self.reply, ctx)
        escalated = self.reply.kind == "red_flag" and self.reply.escalated_by_llm
        if self.reply.kind in ("red_flag", "ai_paused") and self.llm_called and not escalated:
            raise ValueError(f"{self.reply.kind} replies are decided before any LLM call")
        if escalated and not self.llm_called:
            raise ValueError("escalated_by_llm needs an LLM call")
        if (
            self.reply.kind == "ai_paused"
            and self.budget.state != "paused"
            and (self.reply.reason == "ip_daily_cap")
        ):
            raise ValueError("ip_daily_cap pause needs budget.state == paused")
        return self
