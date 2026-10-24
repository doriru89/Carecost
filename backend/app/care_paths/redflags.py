"""Red-flag screening: Q0 checklist and a free-text backstop (English + Chinese).

Deliberately simple and conservative: substring/word matching with short-window negation
("no chest pain", "没有胸痛"). When several flags match, the most urgent disposition wins.
This is not a triage instrument; it only decides when the price tool must stop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.care_paths.models import RedFlag, RedFlagSet
from app.care_paths.text import normalize

_EN_NEGATORS = {
    "no",
    "not",
    "without",
    "never",
    "denies",
    "deny",
    "don't",
    "dont",
    "didn't",
    "haven't",
    "isn't",
    "none",
}
_EN_BREAK = re.compile(r"[.;!?,]|\bbut\b|\bhowever\b|\balthough\b")
_ZH_NEGATORS = ("没有", "没", "不", "无", "未")
_ZH_BREAK = re.compile(r"[，。；！？,.;!?]|但是|但|可是|不过")


@dataclass
class ScreenResult:
    disposition: str | None
    flag_ids: list[str] = field(default_factory=list)


def _is_cjk(term: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in term)


def _negated(text: str, start: int, cjk: bool) -> bool:
    before = text[max(0, start - 40) : start]
    if cjk:
        clause = _ZH_BREAK.split(before)[-1]
        return any(n in clause[-4:] for n in _ZH_NEGATORS)
    clause = _EN_BREAK.split(before)[-1]
    tail = clause.split()[-4:]
    return any(w in _EN_NEGATORS for w in tail)


def _term_hits(text: str, term: str) -> bool:
    term_n = normalize(term).lower()
    cjk = _is_cjk(term_n)
    if cjk:
        rx = re.compile(re.escape(term_n))
    else:
        rx = re.compile(r"(?<![a-z])" + re.escape(term_n) + r"(?:s|es)?(?![a-z])")
    return any(not _negated(text, m.start(), cjk) for m in rx.finditer(text))


def _flag_matches(flag: RedFlag, text: str) -> bool:
    return any(
        all(any(_term_hits(text, t) for t in group) for group in pattern)
        for pattern in flag.patterns
    )


def _rank(flagset: RedFlagSet) -> dict[str, int]:
    return {d.id: d.rank for d in flagset.dispositions}


def _pick(flag_ids: list[str], flagset: RedFlagSet) -> ScreenResult:
    if not flag_ids:
        return ScreenResult(None, [])
    rank = _rank(flagset)
    by_id = {f.id: f for f in flagset.flags}
    best = max(flag_ids, key=lambda fid: rank[by_id[fid].disposition])
    return ScreenResult(by_id[best].disposition, sorted(flag_ids))


def screen_text(text: str, flagset: RedFlagSet, areas: list[str] | None = None) -> ScreenResult:
    t = normalize(text).lower()
    scope = None if areas is None else set(areas) | {"global"}
    hits = [
        f.id
        for f in flagset.flags
        if (scope is None or scope & set(f.areas)) and _flag_matches(f, t)
    ]
    return _pick(hits, flagset)


def screen_checklist(checked: list[str], flagset: RedFlagSet) -> ScreenResult:
    known = {f.id for f in flagset.flags}
    unknown = set(checked) - known
    if unknown:
        raise ValueError(f"unknown red flags: {sorted(unknown)}")
    return _pick(list(checked), flagset)


def checklist_for_area(path_area: str, flagset: RedFlagSet) -> list[RedFlag]:
    areas = set(flagset.path_areas.get(path_area, [path_area])) | {"global"}
    return [f for f in flagset.flags if f.in_checklist and areas & set(f.areas)]
