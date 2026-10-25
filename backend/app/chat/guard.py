"""Chat-side checks on LLM text, on top of the contract's LlmText filter + D33 deny-list.

1. Voice: no stock acknowledgement opener (Kenza 2026-04 rule, made mechanical).
2. D33, stronger than the deny-list: the deny-list (data/chat/condition_names.yaml) only catches
   names someone listed. This adds a cheap allow-list on medical word shapes: any word that
   LOOKS like a condition name (English suffixes -itis, -osis, -oma, -pathy, -algia, -emia,
   -ectomy, -plasia; the nouns syndrome / disease / disorder / cancer / tumor / tear / infection;
   Chinese 癌 / 炎 / 瘤 / 综合征 / 综合症) must appear in the reviewed text of a path the reply shows
   (title, intro, glossary terms). "rotator cuff tendinopathy" passes only if the path says it.
   False positives cost one retry; misses cost a made-up diagnosis on screen.
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
    pass


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
