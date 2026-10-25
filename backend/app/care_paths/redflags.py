"""Red-flag screening: Q0 checklist and a free-text backstop (English + Chinese).

Not a triage instrument: it only decides when the price tool must stop. Deterministic and
explainable on purpose (no ML, no LLM, no network). When unsure it fails toward escalation:
a false positive costs one extra screen, a miss can cost a life.

How free text is matched
------------------------
1. Canonical text: NFKC, lowercase, apostrophes dropped ("can't" -> "cant"), hyphens to spaces,
   "cannot" / "can not" -> "cant", then a few fixed masks that hide non-symptom compounds
   ("chest press", "chest x ray", "food poisoning", "breathe through my nose", 胸推, 胸片 ...)
   and rewrite "不舒服" to "难受" (discomfort is a symptom, not a negation).
2. Tokens: English words, single CJK characters, and break tokens (hard: . ; ! ? 。; soft: , ，).
3. A flag fires if any of its patterns matches. A pattern is a list of term groups that must all
   appear; a group matches if any of its terms matches somewhere without being negated.
4. Term syntax (redflags.json strings):
     "chest pain"          phrase, contiguous tokens; the last English word may take s/es
     "suicid*"             a trailing * is a prefix match on that word
     "hurt*|pain*"         alternatives
     "chest ~4 hurt*|pain*"  left side, then right side with at most 4 word tokens between,
                           not across a hard break (commas are fine)
     "!kill myself"        never negated (crisis language: ambivalent statements screen positive)
5. Negation only suppresses a match when it scopes over it: a negator in the 4 tokens before the
   match inside the same clause (clauses end at punctuation and but / however / 但 / 可是), or a
   negator inside the gap of a "~" term ("chest doesnt hurt", 胸口不痛). Uncertainty is not
   negation: "not sure", "dont know", "no idea", "dont think", 不知道, 是不是, 不确定 ... never
   negate. "never had chest pain this bad" is not negated either (cancel phrases after the match).

Display priority: the highest disposition rank wins; on equal rank the disposition listed first in
redflags.json wins (call_911 before crisis_988, see the crisis_988 note there).

One-way escalation: ``combine`` lets a later LLM step raise the disposition, never lower it or
clear a code flag. Unknown LLM values are ignored and logged.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from app.care_paths.models import RedFlag, RedFlagSet
from app.care_paths.text import normalize

log = logging.getLogger(__name__)

NEG_WINDOW = 4
CANCEL_WINDOW = 5

_EN_NEGATORS = frozenset(
    {
        "no",
        "not",
        "without",
        "never",
        "denies",
        "deny",
        "denied",
        "dont",
        "didnt",
        "doesnt",
        "havent",
        "hasnt",
        "isnt",
        "arent",
        "wasnt",
        "none",
        "nor",
        "neither",
    }
)
_ZH_NEGATORS = frozenset({"没", "不", "无", "未"})
_BREAK_WORDS = frozenset({"but", "however", "although", "though", "但"})
_BREAK_SEQS = (("可", "是"), ("然", "而"))

# Token sequences that contain a negator but do not negate a symptom (uncertainty, intensity).
_NOT_NEGATION = (
    "not sure",
    "not too sure",
    "not certain",
    "not know",
    "dont know",
    "didnt know",
    "dont think",
    "not think",
    "no idea",
    "no clue",
    "not clear",
    "not only",
    "no longer",
    "不知道",
    "是不是",
    "不确定",
    "不清楚",
    "说不清",
    "说不定",
    "不会是",
    "受不了",
    "不了",
    "不行",
    "不停",
    "止不住",
    "不住",
    "不断",
    "不得了",
    "不对劲",
)
# After a negated match, these phrases turn "never had X" into a positive ("never had X this bad").
_CANCEL_AFTER = (
    "like this",
    "this bad",
    "this severe",
    "this painful",
    "until now",
    "before today",
)

# Fixed rewrites applied to canonical text before tokenizing. Hides compounds that look like a
# symptom but are not one. Keep this list short and literal.
_MASKS = (
    ("chest press", "chestpress"),
    ("chest day", "chestday"),
    ("chest fly", "chestfly"),
    ("chest flies", "chestfly"),
    ("chest workout", "chestworkout"),
    ("chest exercise", "chestexercise"),
    ("chest muscle", "chestmuscle"),
    ("chest x ray", "chestxray"),
    ("chest xray", "chestxray"),
    ("chest ct", "chestct"),
    ("chest of drawers", "drawers"),
    ("breast stroke", "breaststroke"),
    ("back stroke", "backstroke"),
    ("heat stroke", "heatstroke"),
    ("sun stroke", "sunstroke"),
    ("food poisoning", "foodpoisoning"),
    ("poison ivy", "poisonivy"),
    ("poison oak", "poisonoak"),
    ("giving me a heart attack", "givingmeaheartattack"),
    ("gave me a heart attack", "givingmeaheartattack"),
    ("almost had a heart attack", "givingmeaheartattack"),
    ("breathe through my nose", "nosebreathing"),
    ("breath through my nose", "nosebreathing"),
    ("responding to treatment", "respondingtotreatment"),
    ("responding to therapy", "respondingtotreatment"),
    ("responding to physical therapy", "respondingtotreatment"),
    ("responding to pt", "respondingtotreatment"),
    ("responding to the medication", "respondingtotreatment"),
    ("responding to medication", "respondingtotreatment"),
    ("responding to meds", "respondingtotreatment"),
    ("responding to the injection", "respondingtotreatment"),
    ("不舒服", "难受"),
    ("看得我心梗", "看得我生气"),
    ("气得我心梗", "看得我生气"),
    ("让我心梗", "看得我生气"),
    ("胸推", "推举"),
    ("练胸", "练肌"),
    ("胸肌", "肌肉"),
    ("胸片", "片子"),
    ("食物中毒", "吃坏肚子"),
)

_TOKEN_RE = re.compile(r"[a-z0-9]+|[㐀-鿿]|[.;!?。；！？\n]|[,，、]")
_HARD = frozenset(".;!?。；！？\n")
_SOFT = frozenset(",，、")


@dataclass
class ScreenResult:
    disposition: str | None
    flag_ids: list[str] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)  # flag id -> the term that matched
    escalated_by_llm: bool = False


# --------------------------------------------------------------------------- text


def canonical(text: str) -> str:
    s = normalize(text).lower()
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("'", "").replace("`", "").replace("-", " ").replace("_", " ")
    s = re.sub(r"\bcan not\b", "cant", s)
    s = re.sub(r"\bcannot\b", "cant", s)
    s = re.sub(r"\s+", " ", s)
    for a, b in _MASKS:
        s = s.replace(a, b)
    return s


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(canonical(text))


def _is_word(tok: str) -> bool:
    return tok not in _HARD and tok not in _SOFT


def _split_words(phrase: str) -> tuple[str, ...]:
    """'chest pain' -> ('chest', 'pain'); '胸口痛' -> ('胸', '口', '痛'); mixed is fine."""
    out: list[str] = []
    for part in phrase.strip().split():
        out += re.findall(r"[a-z0-9]+\*?|[㐀-鿿]", part)
    return tuple(out)


# --------------------------------------------------------------------------- terms


@dataclass(frozen=True)
class _Term:
    left: tuple[tuple[str, ...], ...]
    right: tuple[tuple[str, ...], ...] | None
    gap: int
    no_negation: bool
    raw: str


_PROX = re.compile(r"\s+~(\d+)\s+")


@lru_cache(maxsize=None)
def parse_term(raw: str) -> _Term:
    s = canonical(raw.strip())
    no_neg = s.startswith("!")
    if no_neg:
        s = s[1:].strip()
    parts = _PROX.split(s)

    def alts(side: str) -> tuple[tuple[str, ...], ...]:
        out = tuple(w for w in (_split_words(a) for a in side.split("|")) if w)
        if not out:
            raise ValueError(f"empty red-flag term side in {raw!r}")
        return out

    if len(parts) == 1:
        return _Term(alts(parts[0]), None, 0, no_neg, raw)
    if len(parts) == 3:
        return _Term(alts(parts[0]), alts(parts[2]), int(parts[1]), no_neg, raw)
    raise ValueError(f"red-flag term has more than one '~': {raw!r}")


def _word_eq(pat: str, tok: str, last: bool) -> bool:
    if pat.endswith("*"):
        return tok.startswith(pat[:-1])
    if tok == pat:
        return True
    return last and pat.isascii() and tok in (pat + "s", pat + "es")


def _phrase_at(toks: list[str], i: int, words: tuple[str, ...]) -> int | None:
    """End index (exclusive) if `words` matches at i."""
    if i + len(words) > len(toks):
        return None
    for k, w in enumerate(words):
        if not _word_eq(w, toks[i + k], k == len(words) - 1):
            return None
    return i + len(words)


def _phrase_hits(toks: list[str], side: tuple[tuple[str, ...], ...]) -> list[tuple[int, int]]:
    hits = []
    for i in range(len(toks)):
        for words in side:
            e = _phrase_at(toks, i, words)
            if e is not None:
                hits.append((i, e))
    return hits


# --------------------------------------------------------------------------- negation


def _not_negation_mask(toks: list[str]) -> set[int]:
    covered: set[int] = set()
    for p in _NOT_NEGATION:
        words = _split_words(p)
        for s, e in _phrase_hits(toks, (words,)):
            covered.update(range(s, e))
    return covered


def _is_negator(toks: list[str], i: int, safe: set[int]) -> bool:
    if i in safe:
        return False
    return toks[i] in _EN_NEGATORS or toks[i] in _ZH_NEGATORS


def _is_break(toks: list[str], i: int) -> bool:
    t = toks[i]
    if t in _HARD or t in _SOFT or t in _BREAK_WORDS:
        return True
    return any(
        i + 1 < len(toks) and (toks[i], toks[i + 1]) == seq or i > 0 and (toks[i - 1], t) == seq
        for seq in _BREAK_SEQS
    )


def _negated_before(toks: list[str], start: int, end: int, safe: set[int]) -> bool:
    seen = 0
    i = start - 1
    negated = False
    while i >= 0 and seen < NEG_WINDOW:
        if _is_break(toks, i):
            break
        if _is_negator(toks, i, safe):
            negated = True
            break
        seen += 1
        i -= 1
    if not negated:
        return False
    after: list[str] = []
    j = end
    while j < len(toks) and len(after) < CANCEL_WINDOW and not _is_break(toks, j):
        after.append(toks[j])
        j += 1
    tail = " ".join(after)
    return not any(f" {c} " in f" {tail} " for c in _CANCEL_AFTER)


def _gap_ok(toks: list[str], a: int, b: int, max_gap: int, safe: set[int]) -> bool:
    """Tokens in [a, b) are the gap between the two sides of a '~' term."""
    words = 0
    for i in range(a, b):
        t = toks[i]
        if t in _HARD:
            return False
        if t in _SOFT:
            continue
        if _is_negator(toks, i, safe):
            return False
        words += 1
    return words <= max_gap


def term_hit(toks: list[str], term: _Term, safe: set[int] | None = None) -> bool:
    if safe is None:
        safe = _not_negation_mask(toks)
    lefts = _phrase_hits(toks, term.left)
    if term.right is None:
        spans = lefts
    else:
        rights = _phrase_hits(toks, term.right)
        spans = [
            (ls, re_)
            for ls, le in lefts
            for rs, re_ in rights
            if rs >= le and _gap_ok(toks, le, rs, term.gap, safe)
        ]
    for s, e in spans:
        if term.no_negation or not _negated_before(toks, s, e, safe):
            return True
    return False


# --------------------------------------------------------------------------- flags


def _flag_match(flag: RedFlag, toks: list[str], safe: set[int]) -> str | None:
    """The first matching term (for evidence), or None."""
    for pattern in flag.patterns:
        first: str | None = None
        for group in pattern:
            hit = next((t for t in group if term_hit(toks, parse_term(t), safe)), None)
            if hit is None:
                break
            first = first or hit
        else:
            return first
    return None


def rank_key(flagset: RedFlagSet) -> dict[str, tuple[int, int]]:
    """Higher sorts first-wins: (rank, -position in redflags.json). Ties go to the earlier one."""
    return {d.id: (d.rank, -i) for i, d in enumerate(flagset.dispositions)}


def _pick(
    flag_ids: list[str], flagset: RedFlagSet, evidence: dict[str, str] | None = None
) -> ScreenResult:
    if not flag_ids:
        return ScreenResult(None, [])
    key = rank_key(flagset)
    by_id = {f.id: f for f in flagset.flags}
    best = max(flag_ids, key=lambda fid: key[by_id[fid].disposition])
    return ScreenResult(by_id[best].disposition, sorted(flag_ids), dict(evidence or {}))


def _symptom_cover(toks: list[str], flagset: RedFlagSet) -> set[int]:
    """Tokens inside a symptom phrase that itself contains a negator (喘不过气, cant breathe, 没反应,
    no feeling): such a negator describes the symptom and must not negate the next term."""
    covered: set[int] = set()
    for f in flagset.flags:
        for pattern in f.patterns:
            for group in pattern:
                for raw in group:
                    t = parse_term(raw)
                    for side in (t.left, t.right or ()):
                        for words in side:
                            if any(w in _EN_NEGATORS or w in _ZH_NEGATORS for w in words):
                                for s, e in _phrase_hits(toks, (words,)):
                                    covered.update(range(s, e))
    return covered


def screen_text(text: str, flagset: RedFlagSet, areas: list[str] | None = None) -> ScreenResult:
    """Free-text gate. The chat gate runs before any path is known: call it with areas=None."""
    toks = tokens(text)
    safe = _not_negation_mask(toks) | _symptom_cover(toks, flagset)
    scope = None if areas is None else set(areas) | {"global"}
    evidence: dict[str, str] = {}
    for f in flagset.flags:
        if scope is not None and not scope & set(f.areas):
            continue
        hit = _flag_match(f, toks, safe)
        if hit is not None:
            evidence[f.id] = hit
    return _pick(list(evidence), flagset, evidence)


def screen_checklist(checked: list[str], flagset: RedFlagSet) -> ScreenResult:
    known = {f.id for f in flagset.flags}
    unknown = set(checked) - known
    if unknown:
        raise ValueError(f"unknown red flags: {sorted(unknown)}")
    return _pick(list(checked), flagset)


def checklist_for_area(path_area: str, flagset: RedFlagSet) -> list[RedFlag]:
    areas = set(flagset.path_areas.get(path_area, [path_area])) | {"global"}
    return [
        f
        for f in flagset.flags
        if (f.in_checklist and areas & set(f.areas)) or areas & set(f.checklist_areas)
    ]


# --------------------------------------------------------------------------- one-way escalation


def combine(code: ScreenResult, llm_disposition: str | None, flagset: RedFlagSet) -> ScreenResult:
    """Merge the deterministic gate with a later LLM opinion. The LLM can only RAISE.

    - llm_disposition None: the code result, unchanged.
    - unknown value: ignored, logged as invalid, code result unchanged.
    - strictly higher rank than the code disposition: the LLM value wins,
      code flag ids are kept, ``escalated_by_llm`` is set.
    - equal or lower: the code result, unchanged. A code call_911 / crisis_988 can never be lowered
      or cleared, and an LLM never swaps one top-rank page for the other.
    """
    if llm_disposition is None:
        return code
    key = rank_key(flagset)
    if llm_disposition not in key:
        log.warning("red-flag combine: invalid LLM disposition %r ignored", llm_disposition)
        return code
    if code.disposition is not None and key[llm_disposition][0] <= key[code.disposition][0]:
        return code
    return ScreenResult(llm_disposition, list(code.flag_ids), dict(code.evidence), True)
