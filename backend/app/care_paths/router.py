"""Deterministic routing from question answers to one care path (or a card, or a stop).

Order: red flags (Q0) stop first -> exactly one path whose entry matches -> otherwise a card.
No AI here: the chat layer only fills in answers; this function decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.care_paths.loader import ContentBundle
from app.care_paths.models import CarePath
from app.care_paths.redflags import screen_checklist

Answers = dict[str, "str | list[str]"]


@dataclass
class RouteResult:
    kind: Literal["stop", "path", "card", "none"]
    target: str | None
    tiers: dict[str, str] = field(default_factory=dict)
    active_steps: list[str] = field(default_factory=list)
    layer0_referral: bool = False
    notes: list[str] = field(default_factory=list)
    flag_ids: list[str] = field(default_factory=list)


def _values(answers: Answers, qid: str) -> set[str]:
    v = answers.get(qid)
    if v is None:
        return set()
    return set(v) if isinstance(v, list) else {v}


def _holds(cond: dict[str, list[str]], answers: Answers) -> bool:
    return all(_values(answers, q) & set(vals) for q, vals in cond.items())


def matches(path: CarePath, answers: Answers) -> bool:
    e = path.entry
    if e.all_of and not _holds(e.all_of, answers):
        return False
    if e.any_of and not any(_holds(c, answers) for c in e.any_of):
        return False
    for q, vals in e.none_of.items():
        if _values(answers, q) & set(vals):
            return False
    return True


def _answer_routes(answers: Answers, b: ContentBundle) -> list[str]:
    routes: list[str] = []
    for q in b.questions.questions:
        chosen = _values(answers, q.id)
        for a in q.answers:
            if a.value in chosen:
                routes += a.routes_to
    return routes


def route(answers: Answers, b: ContentBundle) -> RouteResult:
    flags = answers.get("Q0") or []
    flag_list = flags if isinstance(flags, list) else [flags]
    if flag_list:
        screen = screen_checklist(flag_list, b.redflags)
        if screen.disposition:
            return RouteResult("stop", screen.disposition, flag_ids=screen.flag_ids)

    routes = _answer_routes(answers, b)
    layer0 = "layer0:on" in routes
    live = [c for c in b.questions.cards if any(_holds(w, answers) for w in c.when_any)]
    notes = [c.id for c in live if c.kind == "note"]
    exits = [c.id for c in live if c.kind == "exit"]

    candidates = [p for p in b.paths.values() if matches(p, answers)]
    if candidates:
        top = max(p.priority for p in candidates)
        best = [p for p in candidates if p.priority == top]
        if len(best) > 1:
            raise ValueError(f"ambiguous route: {[p.id for p in best]} for {answers}")
        path = best[0]
        tiers: dict[str, str] = {s.id: s.likelihood_tier for s in path.steps}
        for m in path.tier_modifiers:
            if _holds(m.when, answers):
                tiers[m.step] = m.tier
        active = [s.id for s in path.steps if s.condition is None or _holds(s.condition, answers)]
        return RouteResult(
            "path",
            path.id,
            tiers=tiers,
            active_steps=active,
            layer0_referral=layer0,
            notes=notes,
        )
    if exits:
        return RouteResult("card", exits[0], notes=notes, layer0_referral=layer0)
    return RouteResult("none", None, notes=notes)
