"""One chat turn. Order (the contract makes it visible):

1. Identity: client IP from the trusted proxy header (configured), HMAC'd with the email (D2).
2. The server's own turn count for the conversation.
3. Red-flag gate (redflags.json, code only) over the person's own words. A hit -> red_flag, no
   LLM call, no prices. It runs before the budget and the conversation cap on purpose: a person
   over their cap who writes "I want to kill myself" still gets the 988 page.
4. Conversation cap -> ai_paused(conversation_cap).
5. Provider / secret not configured -> ai_paused(provider_unavailable).
6. Budget: reserve the worst-case cost in the SQLite ledger (atomic), else ai_paused.
7. LLM (at most 2 attempts, both charged). Its JSON only fills: understood answers, which allowed
   question to ask, ai_ranked paths, catalog services, glossary keys, one short message, and a
   one-way escalation through ``redflags.combine``. Chips, candidates, "because", copy keys and
   the reply kind are built here from content files. The reply is validated once with a
   ``ChatContext``; a failure retries once, then ``llm_invalid``.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.care_paths.loader import load_paths
from app.care_paths.models import CarePath, QuestionSet, RedFlagSet
from app.care_paths.redflags import ScreenResult, combine, screen_text
from app.care_paths.router import matches
from app.chat import guard
from app.chat.config import ChatSettings
from app.chat.contracts import (
    CARE_PATH_COPY_KEYS,
    MAX_LLM_ATTEMPTS,
    MAX_TURNS_PER_CONVERSATION,
    PAUSE_KEY,
    REPO_ROOT,
    ChatContext,
    ChatRegistries,
    ChatRequest,
    ChatResponse,
    LlmMeter,
)
from app.chat.ledger import Caps, Ledger, Refused, Usage, resets_at
from app.chat.llm import (
    GeminiClient,
    LavaClient,
    LlmClient,
    MeteredClient,
    Price,
    ProviderError,
    estimate_input_tokens,
    price_per_mtok,
)
from app.chat.netid import hash_email, hash_ip
from app.chat.prompt import (
    DISPOSITIONS,
    LLM_OUTPUT_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
    retry_note,
)
from app.quote.contracts import Catalog

log = logging.getLogger(__name__)

NOT_ASKED = {"Q0", "Q14"}  # Q0 is the red-flag checklist (browse UI); Q14 duplicates `payment`
MAX_CANDIDATES = 3
NEAR_SOFT = 0.8
WALLET_LOW = 0.8


class RequestRejected(ValueError):
    """The request itself is wrong (HTTP 422), not the model."""


# --------------------------------------------------------------------------- LLM output


class _Understood(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question_id: str
    value: str
    evidence: str


class LlmOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str = ""
    understood: list[_Understood] = Field(default_factory=list)
    next_question_id: str | None = None
    path_ids: list[str] = Field(default_factory=list)
    service_ids: list[str] = Field(default_factory=list)
    glossary_keys: list[str] = Field(default_factory=list)
    escalate: str | None = None


def parse_llm_json(text: str) -> LlmOutput:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{") :]
    try:
        data = json.loads(t)
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return LlmOutput.model_validate(data)


# --------------------------------------------------------------------------- content


def catalog_from_paths(paths: dict[str, CarePath]) -> Catalog:
    """Fallback catalog when stream C's catalog is not wired in: the care paths only, no services
    (so the model can suggest no ServiceRef). C's catalog replaces it via ``ChatService(catalog=)``."""
    return Catalog.model_validate(
        {
            "version": "chat-fallback",
            "care_paths": [
                {
                    "id": p.id,
                    "title": p.title.en,
                    "area": p.scope.area,
                    "review_status": p.review.status,
                }
                for p in paths.values()
            ],
            "services": [],
        }
    )


@dataclass
class Content:
    registries: ChatRegistries
    questions: QuestionSet
    redflags: RedFlagSet

    @classmethod
    def load(cls, catalog: Catalog | None = None, repo: Path = REPO_ROOT) -> Content:
        cat = catalog or catalog_from_paths(load_paths(repo / "data" / "care_paths" / "paths"))
        qs = QuestionSet.model_validate(
            yaml.safe_load((repo / "data" / "questions" / "questions.yaml").read_text())
        )
        rf = RedFlagSet.model_validate(
            json.loads((repo / "data" / "redflags" / "redflags.json").read_text())
        )
        return cls(ChatRegistries.load(cat, repo), qs, rf)


def _holds(cond: dict[str, list[str]], answers: dict[str, list[str]]) -> bool:
    return all(set(answers.get(q, [])) & set(v) for q, v in cond.items())


def _contradicts(cond: dict[str, list[str]], answers: dict[str, list[str]]) -> bool:
    return any(q in answers and not set(answers[q]) & set(v) for q, v in cond.items())


def possible(p: CarePath, answers: dict[str, list[str]]) -> bool:
    e = p.entry
    if _contradicts(e.all_of, answers):
        return False
    if e.any_of and all(_contradicts(c, answers) for c in e.any_of):
        return False
    return not any(set(answers.get(q, [])) & set(v) for q, v in e.none_of.items())


class Planner:
    """Deterministic: which paths match, which questions could still change the path."""

    def __init__(self, content: Content):
        self.c = content
        self.order = [q.id for q in content.questions.questions]
        cat_ids = [p.id for p in content.registries.catalog.care_paths]
        self.paths = [content.registries.paths[i] for i in cat_ids if i in content.registries.paths]

    def _askable(self, qids: set[str], answers: dict[str, list[str]]) -> list[str]:
        area = set(answers.get("Q1", []))
        out = []
        for qid in self.order:
            if qid in NOT_ASKED or qid in answers or qid not in qids:
                continue
            applies = set(self.c.registries.questions[qid].get("applies_to", ["all"]))
            if "all" in applies or applies & area:
                out.append(qid)
        return out

    def matched(self, answers: dict[str, list[str]]) -> list[str]:
        return [p.id for p in self.paths if matches(p, answers)]  # type: ignore[arg-type]

    def distinguishing(self, answers: dict[str, list[str]]) -> list[str]:
        if "Q1" not in answers:
            return ["Q1"]
        qids: set[str] = set()
        for p in self.paths:
            if possible(p, answers) and not matches(p, answers):  # type: ignore[arg-type]
                qids |= set(p.entry.all_of)
                for c in p.entry.any_of:
                    qids |= set(c)
        return self._askable(qids, answers)

    def refining(self, path_ids: list[str], answers: dict[str, list[str]]) -> list[str]:
        qids: set[str] = set()
        for pid in path_ids:
            p = self.c.registries.paths[pid]
            for m in p.tier_modifiers:
                qids |= set(m.when)
            for s in p.steps:
                if s.condition:
                    qids |= set(s.condition)
        return self._askable(qids, answers)

    def cards(self, answers: dict[str, list[str]]) -> list[str]:
        return [c.id for c in self.c.questions.cards if any(_holds(w, answers) for w in c.when_any)]


# --------------------------------------------------------------------------- service


def _new_id() -> str:
    return "c_" + secrets.token_urlsafe(18)


def make_client(s: ChatSettings) -> LlmClient | None:
    if s.provider == "gemini" and s.gemini_api_key:
        return GeminiClient(
            api_key=s.gemini_api_key,
            model=s.gemini_model,
            thinking_level=s.gemini_thinking_level,
            max_output_tokens=s.max_output_tokens,
            timeout_s=s.timeout_s,
        )
    if s.provider == "lava" and s.lava_api_key:
        return LavaClient(
            api_key=s.lava_api_key,
            model=s.lava_model,
            base_url=s.lava_base_url,
            max_output_tokens=s.max_output_tokens,
            timeout_s=s.timeout_s,
        )
    return None


class ChatService:
    def __init__(
        self,
        settings: ChatSettings,
        content: Content | None = None,
        client: LlmClient | None | Callable[[], LlmClient | None] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = _new_id,
    ):
        self.s = settings
        self.content = content or Content.load()
        self.planner = Planner(self.content)
        self.clock = clock
        self.new_id = new_id
        self._client = client if client is not None else make_client(settings)
        self.caps = Caps(
            settings.ip_soft_usd, settings.ip_hard_usd, settings.global_daily_usd,
            settings.ip_turn_cap,
        )  # fmt: skip
        self.ledger = Ledger(settings.ledger_path, self.caps, clock)

    @property
    def client(self) -> LlmClient | None:
        c = self._client
        return c() if callable(c) and not hasattr(c, "complete") else c  # type: ignore[return-value]

    def price(self) -> Price:
        model = self.client.model if self.client else self.s.gemini_model
        try:
            pin, pout = price_per_mtok(model, self.clock().date())
        except KeyError:
            pin = pout = -1.0
        if self.s.price_in_per_mtok is not None:
            pin = self.s.price_in_per_mtok
        if self.s.price_out_per_mtok is not None:
            pout = self.s.price_out_per_mtok
        if pin < 0 or pout < 0:
            raise KeyError(f"no price for {model}")
        return Price(pin, pout)

    # ------------------------------------------------------------------ budget

    def budget(self, u: Usage, force_paused: bool = False, wallet_out: bool = False) -> dict:
        c = self.caps
        wallet = "ok"
        if wallet_out or u.global_spent_usd >= c.global_usd - 1e-9:
            wallet = "exhausted"
        elif u.global_spent_usd >= WALLET_LOW * c.global_usd:
            wallet = "low"
        spent = round(u.ip_spent_usd, 6)
        if (
            force_paused
            or spent >= c.ip_hard_usd
            or u.ip_turns >= c.ip_turn_cap
            or wallet == "exhausted"
        ):
            state = "paused"
        elif spent >= c.ip_soft_usd:
            state = "over_soft_cap"
        elif spent >= NEAR_SOFT * c.ip_soft_usd:
            state = "near_soft_cap"
        else:
            state = "ok"
        return {
            "state": state,
            "soft_cap_usd": c.ip_soft_usd,
            "hard_cap_usd": c.ip_hard_usd,
            "spent_today_usd": spent,
            "turns_today": min(u.ip_turns, c.ip_turn_cap),
            "turn_cap": c.ip_turn_cap,
            "wallet": wallet,
            "resets_at": resets_at(self.clock()).isoformat(),
        }

    # ------------------------------------------------------------------ entry point

    def handle(self, req: ChatRequest, ip: str) -> str:
        """Returns the validated ChatResponse JSON. Raises RequestRejected for a bad request."""
        secret = self.s.hmac_secret
        meter = LlmMeter()
        if secret is None:
            # no keyed hashes possible: red flags still run, the AI stays off
            ip_hash = email_hash = "unconfigured"
            cid, turn = self.new_id(), 1
            usage = Usage(0.0, 0, 0.0)
        else:
            ip_hash = hash_ip(secret, ip)
            email_hash = hash_email(secret, str(req.email))
            cid, turn = self.ledger.next_turn(req.conversation_id, ip_hash, email_hash, self.new_id)
            usage = self.ledger.usage(ip_hash)
        try:
            ctx = ChatContext.for_request(req, self.content.registries, meter, turn)
        except ValueError as e:
            raise RequestRejected(str(e)) from e
        if "any_checked" in req.answers.get("Q0", []):
            raise RequestRejected(
                "Q0 any_checked carries no flag ids: the checklist goes through the browse flow"
            )

        def out(reply: dict, budget: dict) -> str:
            doc = {
                "conversation_id": cid,
                "reply": reply,
                "budget": budget,
                "llm_called": meter.calls > 0,
                "conversation_turn": turn,
            }
            resp = ChatResponse.model_validate(doc, context=ctx.as_context())
            return str(resp.model_dump_json())

        # 3. red flags, code only
        code = screen_text("\n".join(req.user_texts()), self.content.redflags)
        if code.disposition is not None:
            return out(self._red_flag(code), self.budget(usage))
        # 4. conversation cap
        if turn > MAX_TURNS_PER_CONVERSATION:
            return out(self._paused("conversation_cap", None), self.budget(usage))
        # 5. configured?
        client = self.client
        if secret is None or client is None or self.s.provider == "off":
            return out(self._paused("provider_unavailable", None), self.budget(usage))
        try:
            price = self.price()
        except KeyError:
            log.error("chat: no price for the configured model; AI paused")
            return out(self._paused("provider_unavailable", None), self.budget(usage))
        if usage.ip_turns >= self.caps.ip_turn_cap:
            return out(
                self._paused("ip_daily_cap", resets_at(self.clock())),
                self.budget(usage, force_paused=True),
            )
        return self._llm_turn(req, ctx, meter, client, price, ip_hash, email_hash, cid, turn, out)

    # ------------------------------------------------------------------ LLM turn

    def _llm_turn(
        self,
        req: ChatRequest,
        ctx: ChatContext,
        meter: LlmMeter,
        client: LlmClient,
        price: Price,
        ip_hash: str,
        email_hash: str,
        cid: str,
        turn: int,
        out: Callable[[dict, dict], str],
    ) -> str:
        metered = MeteredClient(client, meter)
        payload = self._payload(req, turn)
        user = build_user_prompt(payload)
        turn_key = f"{cid}:{turn}"
        error: str | None = None
        for attempt in range(MAX_LLM_ATTEMPTS):
            prompt = user + (retry_note(error) if error else "")
            hold = price.cost(
                estimate_input_tokens(SYSTEM_PROMPT, prompt), self.s.max_output_tokens
            )
            try:
                res = self.ledger.reserve(
                    ip_hash=ip_hash, email_hash=email_hash, conversation_id=cid,
                    turn_key=turn_key, amount_usd=hold,
                )  # fmt: skip
            except Refused as r:
                if meter.calls:
                    return out(self._invalid(), self.budget(self.ledger.usage(ip_hash)))
                wallet = r.reason == "wallet_exhausted"
                return out(
                    self._paused(r.reason, resets_at(self.clock())),
                    self.budget(r.usage, force_paused=True, wallet_out=wallet),
                )
            try:
                result = metered.complete(SYSTEM_PROMPT, prompt, LLM_OUTPUT_SCHEMA)
            except ProviderError as e:
                self.ledger.settle(res, hold if e.maybe_billed else 0.0)
                log.warning("chat: provider error: %s", e)
                usage = self.ledger.usage(ip_hash)
                if meter.calls:
                    return out(self._invalid(), self.budget(usage))
                return out(self._paused("provider_unavailable", None), self.budget(usage))
            self.ledger.settle(res, price.cost(result.input_tokens, result.output_tokens))
            try:
                llm = parse_llm_json(result.text)
                reply = self._build(llm, req, turn)
                return out(reply, self.budget(self.ledger.usage(ip_hash)))
            except (ValueError, ValidationError) as e:  # ValidationError is a ValueError too
                error = str(e)
                log.info("chat: LLM output rejected (attempt %d): %s", attempt + 1, error[:300])
        return out(self._invalid(), self.budget(self.ledger.usage(ip_hash)))

    def _payload(self, req: ChatRequest, turn: int) -> dict[str, Any]:
        reg = self.content.registries
        answers = dict(req.answers)
        matched = self.planner.matched(answers)
        allowed = self.planner.distinguishing(answers) + self.planner.refining(matched, answers)
        questions = [
            {
                "id": q.id,
                "text": q.text.en,
                "answers": {a.value: a.label.en for a in q.answers},
            }
            for q in self.content.questions.questions
            if q.id not in NOT_ASKED
        ]
        p: dict[str, Any] = {
            "locale": req.locale,
            "conversation_turn": turn,
            "person_messages": req.user_texts(),
            "chip_answers": answers,
            "questions": questions,
            "allowed_next_questions": list(dict.fromkeys(allowed)),
            "shown_paths": [
                {"id": pid, "title": reg.paths[pid].title.en, "intro": reg.paths[pid].intro}
                for pid in matched
            ],
            "catalog_paths": [
                {"id": c.id, "title": c.title, "intro": reg.paths[c.id].intro}
                for c in reg.catalog.care_paths
                if c.id in reg.paths
            ],
            "catalog_services": [
                {"id": s.service_id, "name": s.plain_name} for s in reg.catalog.services
            ],
            "glossary_keys": sorted(reg.glossary),
        }
        focus = self._focus_text(req)
        if focus is not None:
            p["receipt_line_asked_about"] = focus
        return p

    def _focus_text(self, req: ChatRequest) -> dict[str, Any] | None:
        """P5: our own sourced text for the receipt line the person asks about (never prices)."""
        f = req.focus
        if f is None or f.care_path_id is None:
            return None
        p = self.content.registries.paths.get(f.care_path_id)
        if p is None:
            return None
        step = None
        if f.line_id:
            for s in sorted(p.steps, key=lambda s: -len(s.id)):
                if f.line_id == s.id or f.line_id.startswith(s.id + "_"):
                    step = s
                    break
        d: dict[str, Any] = {"care_path": p.title.en, "intro": p.intro}
        if step is not None:
            d |= {
                "name": step.plain.name,
                "what": step.plain.what,
                "why": step.plain.why,
                "when_skipped": step.plain.when_skipped,
            }
        return d

    # ------------------------------------------------------------------ building replies

    def _red_flag(self, r: ScreenResult) -> dict:
        d = self.content.registries.dispositions[r.disposition]  # type: ignore[index]
        return {
            "kind": "red_flag",
            "disposition": r.disposition,
            "flag_ids": list(r.flag_ids),
            "escalated_by_llm": r.escalated_by_llm,
            "headline": d["headline"],
            "text": d["text"],
        }

    def _paused(self, reason: str, at: datetime | None) -> dict:
        if reason == "conversation_cap":
            at = None  # a new conversation, not a time, lifts it
        return {
            "kind": "ai_paused",
            "reason": reason,
            "message_key": PAUSE_KEY[reason],
            "resumes_at": at.isoformat() if at else None,
        }

    @staticmethod
    def _invalid() -> dict:
        return {"kind": "llm_invalid", "message_key": "ai.output_invalid"}

    def _chip(self, qid: str) -> dict:
        q = self.content.registries.questions[qid]
        return {
            "question_id": qid,
            "text": q["text"],
            "multi": bool(q.get("multi")),
            "answers": [{"value": a["value"], "label": a["label"]} for a in q["answers"]],
        }

    def _candidate(self, pid: str, match: str, answers: dict[str, list[str]]) -> dict:
        reg = self.content.registries
        cat = {p.id: p for p in reg.catalog.care_paths}
        c = cat.get(pid)
        because = reg.because(pid, answers) if match == "entry_matched" else []
        return {
            "path_id": pid,
            "title": c.title if c else pid,
            "match": match,
            "review_status": c.review_status if c else "pending_austin",
            "because": because or [],
        }

    def _allowed_text(self, path_ids: list[str]) -> str:
        reg = self.content.registries
        parts = []
        for pid in path_ids:
            p = reg.paths.get(pid)
            if p is None:
                continue
            parts += [p.title.en, p.title.zh or "", p.intro, " ".join(p.glossary)]
            parts += [n for g in p.glossary for n in reg.conditions.get(g, ())]
        return " ".join(parts)

    def _build(self, llm: LlmOutput, req: ChatRequest, turn: int) -> dict:
        reg = self.content.registries
        # one-way escalation (the code gate already found nothing)
        if llm.escalate is not None:
            if llm.escalate not in DISPOSITIONS:
                raise ValueError(f"escalate must be one of {DISPOSITIONS} or null")
            esc = combine(ScreenResult(None, []), llm.escalate, self.content.redflags)
            if esc.escalated_by_llm:
                return self._red_flag(esc)

        answers = {k: list(v) for k, v in req.answers.items()}
        merged = {k: list(v) for k, v in answers.items()}
        for u in llm.understood:
            if u.question_id not in reg.questions:
                raise ValueError(f"understood: unknown question {u.question_id}")
            if u.question_id not in answers:  # the person's own chip answers win
                merged.setdefault(u.question_id, []).append(u.value)
        understood = [u.model_dump() for u in llm.understood if u.question_id not in answers]

        cat_paths = {c.id for c in reg.catalog.care_paths}
        unknown = [p for p in llm.path_ids if p not in cat_paths or p not in reg.paths]
        if unknown:
            raise ValueError(f"path_ids not in the catalog: {unknown}")
        services = self._services(llm)  # unknown ids fail here, whether or not they are shown

        entry = self.planner.matched(answers)
        via_understood = [p for p in self.planner.matched(merged) if p not in entry]
        specific = bool(entry or via_understood)
        llm_paths = list(llm.path_ids) if (turn > 1 or specific) else []
        ai = [p for p in dict.fromkeys(via_understood + llm_paths) if p not in entry]
        cands = [self._candidate(p, "entry_matched", answers) for p in entry]
        cands += [self._candidate(p, "ai_ranked", answers) for p in ai]
        cands = cands[:MAX_CANDIDATES]
        shown = [c["path_id"] for c in cands]
        cards = self.planner.cards(merged)
        msg = llm.message.strip()

        if req.focus is not None:
            shown_text = [req.focus.care_path_id] if req.focus.care_path_id else []
            self._check_text(msg, shown_text, required=True)
            return {
                "kind": "text",
                "text": msg,
                "card_ids": cards,
                "services": services,
                "glossary_keys": list(dict.fromkeys(llm.glossary_keys)),
                "focus_line_id": req.focus.line_id,
            }

        dist = self.planner.distinguishing(merged)
        refine = self.planner.refining(entry + via_understood, merged)
        out_of_scope = "other" in merged.get("Q1", []) or (not dist and not cands)
        if out_of_scope:
            self._check_text(msg, [], required=True)
            return {
                "kind": "text",
                "text": msg,
                "card_ids": cards,
                "services": services,
                "glossary_keys": list(dict.fromkeys(llm.glossary_keys)),
            }

        pick = llm.next_question_id
        ask: str | None = None
        if pick is not None and pick in dist + refine:
            ask = pick
        elif dist and not entry:
            ask = dist[0]  # the code's distinguishing question when the model's pick is not allowed
        lead_in = msg if (ask is not None and ask == pick) else None
        copy = list(CARE_PATH_COPY_KEYS) if cands else []

        if ask is not None:
            # the model's sentence is checked even when it is not shown: an output that names a
            # diagnosis or a price is a bad output, retried, never quietly trimmed
            self._check_text(msg, shown, required=False)
            return {
                "kind": "clarify",
                "lead_in": lead_in or None,
                "understood": understood,
                "questions": [self._chip(ask)],
                "candidates": cands,
                "copy_keys": copy,
                "card_ids": cards,
            }
        self._check_text(msg, shown, required=True)
        return {
            "kind": "care_paths",
            "text": msg,
            "understood": understood,
            "candidates": cands,
            "copy_keys": copy,
            "card_ids": cards,
        }

    def _services(self, llm: LlmOutput) -> list[dict]:
        cat = {s.service_id: s for s in self.content.registries.catalog.services}
        out = []
        for sid in dict.fromkeys(llm.service_ids):
            s = cat.get(sid)
            if s is None:
                raise ValueError(f"service {sid} is not in the catalog")
            out.append({"service_id": sid, "plain_name": s.plain_name})
        return out[:3]

    def _check_text(self, text: str | None, shown: list[str], required: bool) -> None:
        if required and not text:
            raise ValueError("message is empty")
        allowed = self._allowed_text(shown)
        guard.check_voice(text)
        guard.check_money(text)
        guard.check_condition_shapes(text, allowed)
        guard.check_diagnostic_cues(text, allowed)
