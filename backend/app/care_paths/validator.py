"""V1-V10 content rules (clinical-sources.md §5.3) plus question-routing and glossary checks.

Every rule returns a list of Violation; an empty list means clean. Tests turn them into CI failures.
"""

from __future__ import annotations

import datetime as dt
import re
import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from app.care_paths.loader import ContentBundle
from app.care_paths.models import TIER_ORDER, Appropriateness, CarePath, Citation, Review, Step
from app.care_paths.text import normalize, words

EVIDENCE_TIERS = {"guideline", "government"}

# Highest likelihood tier a rating allows (V3). UNA may only be "rare", with a reviewer note.
TIER_CAP: dict[str, str] = {
    "UA": "certain",
    "MBA": "possible",
    "UNA": "rare",
    "aaos_strong": "certain",
    "aaos_moderate": "likely",
    "aaos_limited": "possible",
    "aaos_consensus": "possible",
    "uspstf_A": "certain",
    "uspstf_B": "certain",
    "uspstf_C": "possible",
    "uspstf_D": "rare",
    "uspstf_I": "possible",
    "acg_strong": "certain",
    "acg_conditional": "possible",
    "standard_of_care": "certain",
    "plan_rule": "certain",
    "implied_by_parent": "certain",
}

RAW_CODE_RE = re.compile(r"\b(?:\d{4}[0-9A-Z]|[A-Z]\d{4})\b|\bCPT\b|\bHCPCS\b", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    rule: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.where}: {self.message}"


def max_tier(rating: str) -> str:
    return TIER_CAP[rating]


def _tier_le(a: str, b: str) -> bool:
    return TIER_ORDER[a] <= TIER_ORDER[b]


# --------------------------------------------------------------------------- iteration helpers


def _path_citations(path: CarePath) -> Iterator[tuple[str, Citation]]:
    for c in path.intro_citations:
        yield f"{path.id}.intro", c
    for c in path.coverage_citations:
        yield f"{path.id}.coverage", c
    for e in path.exits:
        for c in e.citations:
            yield f"{path.id}.exit", c
    for s in path.steps:
        for c in s.citations:
            yield f"{path.id}.{s.id}", c


def _all_citations(b: ContentBundle) -> Iterator[tuple[str, Citation]]:
    for path in b.paths.values():
        yield from _path_citations(path)
    for card in b.questions.cards:
        for c in card.citations:
            yield f"card:{card.id}", c


def _appropriateness(path: CarePath) -> Iterator[tuple[str, Appropriateness]]:
    for s in path.steps:
        yield f"{path.id}.{s.id}", s.appropriateness
    for i, m in enumerate(path.tier_modifiers):
        if m.appropriateness is not None:
            yield f"{path.id}.modifier[{i}]", m.appropriateness


# --------------------------------------------------------------------------- V1


def v1_evidence(b: ContentBundle) -> list[Violation]:
    out: list[Violation] = []

    def tier_ok(c: Citation) -> bool:
        src = b.sources.get(c.doc)
        return src is not None and src.tier in EVIDENCE_TIERS

    for path in b.paths.values():
        if not any(tier_ok(c) for c in path.intro_citations):
            out.append(Violation("V1", path.id, "intro has no guideline/government citation"))
        for s in path.steps:
            where = f"{path.id}.{s.id}"
            if not any(tier_ok(c) for c in s.citations if c.claim_field == "why"):
                out.append(Violation("V1", where, "plain.why has no guideline/government citation"))
            if s.when_skipped_basis == "clinical" and not any(
                tier_ok(c) for c in s.citations if c.claim_field == "when_skipped"
            ):
                out.append(
                    Violation("V1", where, "clinical when_skipped has no guideline/government cite")
                )
            if s.when_skipped_basis == "logic" and not s.reviewer_note:
                out.append(Violation("V1", where, "logic-based when_skipped needs a reviewer_note"))
    return out


# --------------------------------------------------------------------------- V2


def v2_quotes_and_ratings(b: ContentBundle) -> list[Violation]:
    out: list[Violation] = []
    for where, c in _all_citations(b):
        src = b.sources.get(c.doc)
        if src is None:
            out.append(Violation("V2", where, f"unknown source {c.doc!r}"))
            continue
        if c.year != src.year:
            out.append(
                Violation("V2", where, f"{c.doc}: cites year {c.year}, registry says {src.year}")
            )
        if c.url != src.url:
            out.append(Violation("V2", where, f"{c.doc}: url differs from registry"))
        q = normalize(c.quote)
        if not any(q in normalize(e) for e in src.excerpts):
            out.append(Violation("V2", where, f"quote not in stored snapshot of {c.doc}: {q!r}"))
    for path in b.paths.values():
        for where, a in _appropriateness(path):
            if a.source is not None and a.source not in b.sources:
                out.append(Violation("V2", where, f"rating source {a.source!r} unknown"))
                continue
            if a.rating not in ("UA", "MBA", "UNA"):
                continue
            src = b.sources[a.source or ""]
            table = (src.acr_variants or {}).get(a.variant or -1)
            if table is None:
                out.append(Violation("V2", where, f"{a.source} has no variant {a.variant}"))
                continue
            actual = table.ratings.get(a.procedure or "")
            if actual is None:
                out.append(Violation("V2", where, f"V{a.variant} has no row {a.procedure!r}"))
            elif actual != a.rating:
                out.append(
                    Violation("V2", where, f"rating {a.rating} but ACR V{a.variant} says {actual}")
                )
    return out


# --------------------------------------------------------------------------- V3


def v3_likelihood_bound(b: ContentBundle) -> list[Violation]:
    out: list[Violation] = []
    for path in b.paths.values():
        by_id = {s.id: s for s in path.steps}
        for s in path.steps:
            where = f"{path.id}.{s.id}"
            cap = TIER_CAP[s.appropriateness.rating]
            if not _tier_le(s.likelihood_tier, cap):
                out.append(
                    Violation(
                        "V3",
                        where,
                        f"{s.likelihood_tier} exceeds {cap} for {s.appropriateness.rating}",
                    )
                )
            if s.appropriateness.rating == "UNA" and not s.reviewer_note:
                out.append(Violation("V3", where, "UNA step needs a reviewer_note"))
            if s.travels_with:
                t = by_id[s.travels_with]
                if not _tier_le(s.likelihood_tier, t.likelihood_tier):
                    out.append(
                        Violation(
                            "V3", where, f"more likely than the step it travels with ({t.id})"
                        )
                    )
        for i, m in enumerate(path.tier_modifiers):
            rating = (m.appropriateness or by_id[m.step].appropriateness).rating
            cap = TIER_CAP[rating]
            if not _tier_le(m.tier, cap):
                out.append(
                    Violation(
                        "V3", f"{path.id}.modifier[{i}]", f"{m.tier} exceeds {cap} ({rating})"
                    )
                )
    return out


# --------------------------------------------------------------------------- V4


def _ancestors(step: Step, by_id: dict[str, Step]) -> set[str]:
    seen: set[str] = set()
    stack = list(step.after)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(by_id[cur].after)
    return seen


def _is_xray(s: Step) -> bool:
    proc = s.appropriateness.procedure or ""
    return s.kind == "imaging" and proc.startswith("Radiography")


def v4_xray_first(b: ContentBundle) -> list[Violation]:
    out: list[Violation] = []
    for path in b.paths.values():
        by_id = {s.id: s for s in path.steps}
        checks: list[tuple[str, Step, Appropriateness]] = [
            (f"{path.id}.{s.id}", s, s.appropriateness) for s in path.steps
        ]
        checks += [
            (f"{path.id}.modifier[{i}]", by_id[m.step], m.appropriateness)
            for i, m in enumerate(path.tier_modifiers)
            if m.appropriateness is not None
        ]
        for where, step, a in checks:
            if a.rating not in ("UA", "MBA", "UNA") or a.source not in b.sources:
                continue
            variant = (b.sources[a.source].acr_variants or {}).get(a.variant or -1)
            if variant is None or not variant.requires_prior_radiographs:
                continue
            if not any(_is_xray(by_id[x]) for x in _ancestors(step, by_id)):
                out.append(
                    Violation(
                        "V4", where, "variant assumes prior X-rays but no X-ray step precedes it"
                    )
                )
    return out


# --------------------------------------------------------------------------- V5


def v5_codes(b: ContentBundle) -> list[Violation]:
    out: list[Violation] = []
    for path in b.paths.values():
        for s in path.steps:
            where = f"{path.id}.{s.id}"
            for code in sorted(s.all_codes()):
                if code not in b.cpt_registry.codes:
                    out.append(Violation("V5", where, f"code {code} not in 2026 PFS registry"))
            if not s.cpts and not s.no_price:
                out.append(Violation("V5", where, "no CPT and no explicit no_price"))
            if s.no_price and not s.no_price_reason:
                out.append(Violation("V5", where, "no_price needs a no_price_reason"))
    return out


# --------------------------------------------------------------------------- V6


def _trigger_re(trigger: str) -> re.Pattern[str]:
    flags = 0 if trigger.isupper() else re.IGNORECASE
    return re.compile(r"(?<![A-Za-z])" + re.escape(trigger) + r"(?:s|es)?(?![A-Za-z])", flags)


def jargon_index(b: ContentBundle) -> list[tuple[str, re.Pattern[str]]]:
    return [(key, _trigger_re(t)) for key, term in b.glossary.terms.items() for t in term.triggers]


def _jargon_keys(text: str, index: list[tuple[str, re.Pattern[str]]]) -> set[str]:
    return {key for key, rx in index if rx.search(text)}


def _visible_step_strings(s: Step) -> list[str]:
    p = s.plain
    texts = [
        p.name,
        p.technical_name,
        p.what,
        p.why,
        p.when_skipped,
        p.how_long or "",
        p.prep or "",
    ]
    texts += [item.text for item in s.ai_potential]
    return texts


def v6_copy_lint(b: ContentBundle) -> list[Violation]:
    out: list[Violation] = []
    index = jargon_index(b)
    for path in b.paths.values():
        path_texts = [path.title.en, path.intro, path.coverage_note or ""]
        path_texts += [e.text for e in path.exits]
        for t in path_texts:
            if RAW_CODE_RE.search(t):
                out.append(Violation("V6", path.id, f"raw code in copy: {t[:60]!r}"))
            missing = _jargon_keys(t, index) - set(path.glossary)
            if missing:
                out.append(Violation("V6", path.id, f"unglossed jargon {sorted(missing)}"))
        for s in path.steps:
            where = f"{path.id}.{s.id}"
            for t in _visible_step_strings(s):
                if RAW_CODE_RE.search(t):
                    out.append(Violation("V6", where, f"raw code in copy: {t[:60]!r}"))
                missing = _jargon_keys(t, index) - set(s.glossary)
                if missing:
                    out.append(Violation("V6", where, f"unglossed jargon {sorted(missing)}"))
            name_jargon = _jargon_keys(s.plain.name, index)
            if name_jargon:
                out.append(
                    Violation(
                        "V6", where, f"D8: plain name leads with jargon {sorted(name_jargon)}"
                    )
                )
            if s.plain.name.strip().lower() == s.plain.technical_name.strip().lower():
                out.append(Violation("V6", where, "D8: plain name equals technical name"))
    for card in b.questions.cards:
        for t in (card.title.en, card.text):
            if RAW_CODE_RE.search(t):
                out.append(Violation("V6", f"card:{card.id}", f"raw code in copy: {t[:60]!r}"))
    return out


# --------------------------------------------------------------------------- V7


def required_flags(path: CarePath, b: ContentBundle) -> set[str]:
    areas = set(b.redflags.path_areas[path.scope.area])
    return {f.id for f in b.redflags.flags if areas & set(f.areas)}


def v7_red_flags(b: ContentBundle) -> list[Violation]:
    out: list[Violation] = []
    known = {f.id for f in b.redflags.flags}
    for path in b.paths.values():
        unknown = set(path.red_flags) - known
        if unknown:
            out.append(Violation("V7", path.id, f"unknown red flags {sorted(unknown)}"))
        missing = required_flags(path, b) - set(path.red_flags)
        if missing:
            out.append(Violation("V7", path.id, f"missing red flags {sorted(missing)}"))
    return out


# --------------------------------------------------------------------------- V8


def _review_violations(where: str, review: Review) -> list[Violation]:
    out: list[Violation] = []
    for r in review.reviewers:
        if r.kind == "ai" or r.id.startswith("ai:") or r.id == review.drafted_by:
            out.append(Violation("V8", where, f"reviewer {r.id!r} is AI or the drafter"))
    ok = {
        r.id
        for r in review.reviewers
        if r.verdict == "ok" and r.at is not None and r.kind != "ai" and not r.id.startswith("ai:")
    }
    if review.status == "approved" and len(ok) < 2:
        out.append(Violation("V8", where, "approved without 2 distinct human sign-offs"))
    if review.drafted_by.startswith("ai:") and review.status == "approved" and len(ok) < 2:
        out.append(Violation("V8", where, "AI-drafted content cannot self-approve"))
    return out


def v8_review(b: ContentBundle) -> list[Violation]:
    out: list[Violation] = []
    for path in b.paths.values():
        out += _review_violations(path.id, path.review)
    out += _review_violations("glossary", b.glossary.review)
    out += _review_violations("redflags", b.redflags.review)
    out += _review_violations("questions", b.questions.review)
    return out


# --------------------------------------------------------------------------- V9


def stale_sources(b: ContentBundle, today: dt.date | None = None) -> list[str]:
    today = today or dt.date.today()
    return [
        sid
        for sid, s in b.sources.items()
        if s.checked_at + dt.timedelta(days=s.recheck_after_days) < today
    ]


def warn_stale(b: ContentBundle, today: dt.date | None = None) -> None:
    for sid in stale_sources(b, today):
        warnings.warn(f"V9: source {sid} is past its recheck date", stacklevel=2)


def dependents_of(source_id: str, b: ContentBundle) -> list[str]:
    """Paths to re-review when a source is revised (V9 sweep)."""
    return sorted(
        p.id
        for p in b.paths.values()
        if any(c.doc == source_id for _, c in _path_citations(p))
        or any(a.source == source_id for _, a in _appropriateness(p))
    )


# --------------------------------------------------------------------------- V10


def v10_golden(b: ContentBundle) -> list[Violation]:
    from app.care_paths.router import route

    out: list[Violation] = []
    for path in b.paths.values():
        for g in path.golden_cases:
            where = f"{path.id}:{g.name}"
            try:
                r = route(g.answers, b)
            except ValueError as exc:
                out.append(Violation("V10", where, str(exc)))
                continue
            if r.target != g.expect:
                out.append(
                    Violation("V10", where, f"routed to {r.kind}:{r.target}, want {g.expect}")
                )
                continue
            for step_id, tier in g.expect_tiers.items():
                if r.tiers.get(step_id) != tier:
                    out.append(
                        Violation("V10", where, f"{step_id} tier {r.tiers.get(step_id)} != {tier}")
                    )
    return out


RULES: dict[str, Callable[[ContentBundle], list[Violation]]] = {
    "V1": v1_evidence,
    "V2": v2_quotes_and_ratings,
    "V3": v3_likelihood_bound,
    "V4": v4_xray_first,
    "V5": v5_codes,
    "V6": v6_copy_lint,
    "V7": v7_red_flags,
    "V8": v8_review,
    "V10": v10_golden,
}


def validate_all(b: ContentBundle) -> list[Violation]:
    out: list[Violation] = []
    for rule in RULES.values():
        out += rule(b)
    return out


# --------------------------------------------------------------------------- publishability


def publishable(path: CarePath, b: ContentBundle, audience: str = "personal") -> list[str]:
    """Reasons this path can't be shown as reviewed content. Empty list = publishable."""
    reasons: list[str] = []
    if path.review.status != "approved":
        reasons.append(f"review status is {path.review.status}")
    humans = [r for r in path.review.reviewers if r.verdict == "ok" and r.at and r.kind != "ai"]
    if len({r.id for r in humans}) < 2:
        reasons.append("needs 2 distinct non-AI reviewers")
    if audience == "public" and not any(r.kind == "human_clinician" for r in humans):
        reasons.append("public launch needs a clinician reviewer")
    asserted = sorted({c.code for s in path.steps for c in s.cpts if c.mapping == "asserted"})
    if asserted:
        reasons.append(f"asserted code mappings not confirmed: {asserted}")
    if path.clinical_uncertainties:
        reasons.append(f"{len(path.clinical_uncertainties)} open clinical uncertainties")
    for v in validate_all(b):
        if v.where.startswith(path.id):
            reasons.append(str(v))
    return reasons


# --------------------------------------------------------------------------- questions


def _answer_index(b: ContentBundle) -> dict[str, set[str]]:
    return {q.id: {a.value for a in q.answers} for q in b.questions.questions}


def check_question_routes(b: ContentBundle) -> list[str]:
    qids = {q.id for q in b.questions.questions}
    cards = {c.id for c in b.questions.cards}
    dispositions = {d.id for d in b.redflags.dispositions}
    problems: list[str] = []
    for q in b.questions.questions:
        for a in q.answers:
            for target in a.routes_to:
                kind, _, ref = target.partition(":")
                ok = False
                if kind == "path":
                    ok = ref in b.paths
                elif kind == "next":
                    ok = ref in qids
                elif kind == "card":
                    ok = ref in cards
                elif kind == "stop":
                    ok = ref in dispositions or ref == "by_flag"
                elif kind == "layer0":
                    ok = ref in ("on", "off")
                elif kind == "tier":
                    pid, _, sid = ref.partition(".")
                    ok = pid in b.paths and any(s.id == sid for s in b.paths[pid].steps)
                if not ok:
                    problems.append(f"{q.id}={a.value}: route {target!r} resolves to nothing")
    return problems


def _conditions(path: CarePath) -> Iterator[tuple[str, dict[str, list[str]]]]:
    yield "entry.all_of", path.entry.all_of
    for i, cond in enumerate(path.entry.any_of):
        yield f"entry.any_of[{i}]", cond
    yield "entry.none_of", path.entry.none_of
    for i, m in enumerate(path.tier_modifiers):
        yield f"modifier[{i}]", m.when
    for s in path.steps:
        if s.condition:
            yield f"{s.id}.condition", s.condition


def check_entry_answers(b: ContentBundle) -> list[str]:
    idx = _answer_index(b)
    problems: list[str] = []
    for card in b.questions.cards:
        for cond in card.when_any:
            for qid, values in cond.items():
                bad = [v for v in values if qid not in idx or v not in idx[qid]]
                if bad:
                    problems.append(f"card:{card.id}: {qid} has no answer(s) {bad}")
    for path in b.paths.values():
        for where, cond in _conditions(path):
            for qid, values in cond.items():
                if qid not in idx:
                    problems.append(f"{path.id}.{where}: unknown question {qid}")
                    continue
                for v in values:
                    if v not in idx[qid]:
                        problems.append(f"{path.id}.{where}: {qid} has no answer {v!r}")
        for g in path.golden_cases:
            for qid, val in g.answers.items():
                vals = val if isinstance(val, list) else [val]
                if qid == "Q0":
                    continue
                for v in vals:
                    if qid not in idx or v not in idx[qid]:
                        problems.append(f"{path.id}:{g.name}: bad answer {qid}={v}")
    return problems


def check_routes_match_entries(b: ContentBundle) -> list[str]:
    problems: list[str] = []
    declared: set[tuple[str, str, str]] = set()  # (qid, value, target)
    for q in b.questions.questions:
        for a in q.answers:
            for t in a.routes_to:
                declared.add((q.id, a.value, t))
    used: set[tuple[str, str, str]] = set()
    for path in b.paths.values():
        conds = [path.entry.all_of, *path.entry.any_of]
        for cond in conds:
            for qid, values in cond.items():
                for v in values:
                    used.add((qid, v, f"path:{path.id}"))
        for m in path.tier_modifiers:
            for qid, values in m.when.items():
                for v in values:
                    used.add((qid, v, f"tier:{path.id}.{m.step}"))
    for card in b.questions.cards:
        for cond in card.when_any:
            for qid, values in cond.items():
                for v in values:
                    used.add((qid, v, f"card:{card.id}"))
    for qid, v, target in sorted(declared):
        if target.startswith(("path:", "tier:", "card:")) and (qid, v, target) not in used:
            problems.append(f"{qid}={v} declares {target} but that path never uses the answer")
    for qid, v, target in sorted(used):
        if (qid, v, target) not in declared:
            problems.append(f"{target} uses {qid}={v} but the question doesn't declare the route")
    return problems


# --------------------------------------------------------------------------- glossary


def _shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i : i + n]) for i in range(len(w) - n + 1)}


def check_glossary_not_copied(b: ContentBundle) -> list[str]:
    source_shingles: set[tuple[str, ...]] = set()
    for s in b.sources.values():
        for e in s.excerpts:
            source_shingles |= _shingles(e)
    problems = []
    for key, t in b.glossary.terms.items():
        overlap = _shingles(t.short) & source_shingles
        if overlap:
            problems.append(f"{key}: copies source wording {' '.join(next(iter(overlap)))!r}")
    return problems
