"""Chat-side checks on LLM text, on top of the contract's LlmText filter + D33 deny-list.

1. Voice: no stock acknowledgement opener (Kenza 2026-04 rule, made mechanical).
2. D33, stronger than the deny-list: the deny-list (data/chat/condition_names.yaml) only catches
   names someone listed. This adds a cheap allow-list on medical word shapes: any word that
   LOOKS like a condition name (English suffixes -itis, -osis, -oma, -pathy, -algia, -emia,
   -ectomy, -plasia; the nouns syndrome / disease / disorder / cancer / tumor / tear / infection;
   Chinese 癌 / 炎 / 瘤 / 综合征 / 综合症) must appear in the reviewed text of a path the reply shows
   (title, intro, glossary terms). "rotator cuff tendinopathy" passes only if the path says it.
   False positives cost one retry; misses cost a made-up diagnosis on screen.
3. Money in any form (review 2026-10-24): currency WORDS are rejected even without a number
   ("around three hundred dollars", "a couple grand"). LlmText already rejects symbols and
   digit/number-character + unit; the AI has no reason to talk about money at all.
4. Diagnostic cue phrases (review 2026-10-24), a structural rule instead of a longer word list:
   "might/could/may be", "sounds like", "you probably have", "likely", "consistent with", 可能是,
   像是 ... One rule: a word within the next few words after the cue must come from the shown
   paths' reviewed text ("most likely the rotator cuff" passes for the shoulder path; "might be a
   pinched nerve" does not). A turn that shows no path has no such text, so every cue is
   rejected there: explaining what it may be belongs to turns that show paths.
5. No digits at all (review round 2, Austin option A): any ASCII or full-width digit in model text
   is rejected ("roughly 150", "６ weeks"). The UI shows every number; the model spells nothing
   numeric. Chinese number words stay allowed unless a currency unit follows (LlmText).
"""

from __future__ import annotations

import re

from app.chat.prompt import STOCK_OPENERS_EN, STOCK_OPENERS_ZH

_EN_SHAPES = re.compile(
    r"\b[a-z]+(?:itis|osis|oses|omas?|pathy|pathies|algia|emia|aemia|ectomy|plasia)\b"
    r"|\b(?:syndromes?|diseases?|disorders?|cancers?|tumou?rs?|tears?|torn|infections?|"
    r"fractures?|hernias?|lesions?|cysts?)\b",
    re.I,
)
# 'tear' as in crying / wear-and-tear is allowed when the path text has it; ordinary non-medical
# words that match a shape are listed here.
_EN_OK = {"diagnosis", "prognosis", "osmosis", "aroma", "diploma", "coma", "comma", "soma"}
_ZH_SHAPES = re.compile(r"[一-鿿]{0,4}(?:癌|炎|瘤|综合征|综合症)")


class GuardError(ValueError):
    rule: str = "guard"  # set by the caller: which check rejected the text


def check_voice(text: str | None) -> None:
    if not text:
        return
    t = text.strip().lower().lstrip("\"'“")
    for op in STOCK_OPENERS_EN:
        if t.startswith(op) and (len(t) == len(op) or not t[len(op)].isalpha()):
            raise GuardError(f"stock acknowledgement opener {op!r}: start with the substance")
    for op in STOCK_OPENERS_ZH:
        if t.startswith(op):
            raise GuardError(f"stock acknowledgement opener {op!r}: start with the substance")


def condition_like_words(text: str) -> set[str]:
    out = {m.group(0).lower() for m in _EN_SHAPES.finditer(text)} - _EN_OK
    out |= {m.group(0)[-3:] if m.group(0).endswith(("综合征", "综合症")) else m.group(0)[-2:]
            for m in _ZH_SHAPES.finditer(text)}  # fmt: skip
    return out


def check_condition_shapes(text: str | None, allowed_text: str) -> None:
    if not text:
        return
    allowed_low = allowed_text.lower()
    bad = sorted(w for w in condition_like_words(text) if w not in allowed_low)
    if bad:
        raise GuardError(
            f"LLM text uses condition-like words the shown care paths do not: {bad} (D33)"
        )


_MONEY_WORDS = re.compile(
    r"\b(?:dollars?|bucks?|usd|cents?|grand)\b"
    r"|美元|美金|块钱|人民币|(?<![单公多])元(?![素旦宵])",
    re.I,
)


def check_money(text: str | None) -> None:
    if not text:
        return
    m = _MONEY_WORDS.search(text)
    if m:
        raise GuardError(f"LLM text may not talk about money ({m.group(0)!r}): the UI shows prices")


_EN_CUES = re.compile(
    r"\b(?:might|could|may)\s+(?:well\s+)?be\b|\bsounds?\s+like\b|\blooks?\s+like\b"
    r"|\byou\s+(?:probably|likely|may|might|could)\s+have\b|\b(?:most\s+)?likely\b"
    r"|\bprobably\b|\bconsistent\s+with\b|\bsuggests?\b",
    re.I,
)
_ZH_CUES = re.compile(r"可能是|可能有|像是|也许是|大概是|应该是|估计是")
CUE_WINDOW = 5  # words after an English cue
ZH_WINDOW = 8  # characters after a Chinese cue
_STOP = {
    "a", "an", "the", "it", "is", "be", "of", "in", "on", "to", "and", "or", "your", "you",
    "that", "this", "with", "from", "some", "kind", "sort", "type", "problem", "issue",
    "something", "related", "caused", "due", "by", "more", "most", "often", "usually",
}  # fmt: skip


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z][a-z'-]*", s.lower())


def check_diagnostic_cues(text: str | None, allowed_text: str) -> None:
    """A cue must be followed by the shown paths' own words. On a turn that shows no path the
    allowed text is empty, so every cue is rejected: one rule covers both cases."""
    if not text:
        return
    allowed_words = set(_words(allowed_text)) - _STOP
    for m in _EN_CUES.finditer(text):
        after = [w for w in _words(text[m.end() :])[:CUE_WINDOW] if w not in _STOP]
        if not any(w in allowed_words for w in after):
            raise GuardError(f"diagnostic cue {m.group(0)!r} not followed by a shown path's words")
    for m in _ZH_CUES.finditer(text):
        tail = text[m.end() : m.end() + ZH_WINDOW]
        if not allowed_text or not any(
            tail[i : i + 2] in allowed_text for i in range(len(tail) - 1)
        ):
            raise GuardError(f"diagnostic cue {m.group(0)!r} not followed by a shown path's words")


_DIGIT = re.compile(r"[0-9\uff10-\uff19]")


def check_digits(text: str | None) -> None:
    if not text:
        return
    m = _DIGIT.search(text)
    if m:
        raise GuardError(f"LLM text may not contain digits ({m.group(0)!r}): the UI shows numbers")
