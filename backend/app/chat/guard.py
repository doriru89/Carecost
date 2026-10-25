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
6. P13 / R14 (wave-2 review, security-gate F6): structural rejects, because a prompt is not a
   boundary. Sites belong to the list, money and value to the receipt, urgency to red-flag copy.
   a. Site, operator or chain names: tokens and phrases derived from data/sites/sites.yaml (names,
      operators, ownership detail, towns) minus generic words, plus curated short forms
      (data/chat/site_names.yaml: "AFC", "Mass General", "the Saugus one" via the town token).
   b. Value and money talk: cheap*, afford*, save, best value, worth it, costs less, out of pocket,
      magnitudes (hundred, thousand, grand), Chinese 便宜 / 划算 / 省钱 / 两百 ... On turns that show
      care paths (prices sit beside them) the neutral nouns price, cost, fee, pay, bill, charge and
      every English number word (two ... ninety) are rejected too. A question turn with no path may
      still say "more than six weeks ago" (the review-round-2 ruling on number words), and a focus
      turn that explains one receipt line may say "fee".
   c. Urgency judgements: emergency, ER, urgent (except "urgent care", a kind of place), serious,
      worry, wait, skip, soon, right away, no need, fine to ..., 急诊, 严重, 不用担心, 马上 ...
   d. Spelled-out links: "dot com", "www".
   False positives cost one retry, then fixed copy with the same chips (never a blank turn).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

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
    "something", "related", "caused", "due", "by", "more", "most", "often", "usually", "main",
    "really", "very", "quite",
}  # fmt: skip
# A cue whose next content word is one of these talks about the conversation or a trigger, not a
# diagnosis (wave-2 false positives: "It could be helpful to know whether...", "Lifting overhead
# might be the main trigger...", "That likely narrows things down..."). A condition word later in
# the sentence is still caught by the D33 deny-list and the condition shapes.
_CUE_NOT_DIAGNOSIS = {
    "helpful", "useful", "good", "worth", "easier", "harder", "important", "narrows", "narrow",
    "narrowing", "trigger", "triggers", "triggered", "worse", "better", "enough", "clearer",
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
        if after and after[0] in _CUE_NOT_DIAGNOSIS:
            continue  # "could be helpful to know", "likely narrows things down"
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


# --------------------------------------------------------------------------- 6. P13 price turns

_MAGNITUDES = "hundreds?|thousands?|millions?|dozens?|grand"
_CARDINALS = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"\b",
    re.I,
)
_VALUE_EN = re.compile(
    r"\b(?:cheap\w*|inexpensive|expensive|pricey|overpriced|afford\w*|budget\w*|bargains?|deals?|"
    r"discount\w*|save|saves|saving|savings|money|spend\w*|free of charge|for free|"
    r"(?:best|good|great|better|low|lower|high|higher)[\s-](?:value|cost|price)s?|value for|"
    r"worth (?:it|the|paying|going)|low-cost|out[\s-]of[\s-]pocket|"
    r"(?:costs?|pay|paying|charges?) (?:less|more|little|a lot)|"
    rf"(?:{_MAGNITUDES}))\b",
    re.I,
)
_VALUE_ZH = re.compile(
    r"便宜|划算|实惠|省钱|省点钱|性价比|贵|花钱|多少钱|免费|优惠|值得|值不值|"
    r"[零一二两三四五六七八九十几]+\s*[百千万]"
)
_PRICE_NOUNS = re.compile(
    r"\b(?:prices?|priced|pricing|costs?|costly|fees?|pay|paying|paid|payment|bills?|billed|"
    r"billing|charges?|charged)\b|价格|价钱|费用|收费|付钱|账单",
    re.I,
)
_URGENCY_EN = re.compile(
    r"\bemergenc(?:y|ies)\b|\bA&E\b|\bambulance\b|\burgent(?!\s*[- ]?\s*care)\b|\burgently\b|"
    r"\burgency\b|\bserious(?:ly)?\b|\bworr(?:y|ied|ying)\b|\bwait(?:s|ed|ing)?\b|\bskip\w*\b|"
    r"\bright away\b|\bimmediately\b|\basap\b|\bsoon\b|\bno need\b|\bneedn't\b|"
    r"\b(?:don't|do not|doesn't|does not|won't|will not|wouldn't|shouldn't)\s+(?:need|have to)\b|"
    r"\b(?:fine|safe|okay|ok)\s+to\b|\bnothing to\b|\bharmless\b|\bdanger\w*\b|"
    r"\blife[\s-]threatening\b|\bnot (?:a|an) (?:big deal|problem|concern)\b",
    re.I,
)
_ER = re.compile(r"\bE\.?R\.?(?![A-Za-z])")  # case-sensitive: "ER", "E.R.", never "er" / "her"
_URGENCY_ZH = re.compile(
    r"急诊|急症|紧急|不急|着急|别急|严重|担心|可以等|再等|等等看|马上|立即|立刻|尽快|赶紧|赶快|"
    r"不需要|不用去|没关系|没事|没什么大不了|危险|救护车"
)
_SPELLED_LINK = re.compile(r"\bdot\s+(?:com|org|net|io|gov|edu|co|us)\b|\bwww\b", re.I)


@dataclass(frozen=True)
class SiteNames:
    """Every name a reply could use to point at a place (P13). Built from the site registry, so a
    new site is covered the day it is added; data/chat/site_names.yaml holds what derivation
    cannot know (short forms, generic words that must stay usable)."""

    pattern: re.Pattern[str] | None
    case_sensitive: re.Pattern[str] | None
    size: int

    @classmethod
    def build(
        cls,
        texts: Iterable[str],
        aliases: Iterable[str],
        generic: Iterable[str],
        capitalized_only: Iterable[str] = (),
    ) -> SiteNames:
        gen = {g.lower() for g in generic}
        caps = {c.lower() for c in capitalized_only}
        terms: set[str] = {a.lower() for a in aliases}
        for t in texts:
            for w in re.findall(r"[A-Za-z][A-Za-z'&-]*[A-Za-z]", t or ""):
                w = w.lower()
                if len(w) >= 3 and w not in gen and w not in caps:
                    terms.add(w)
        terms -= gen
        alts = "|".join(sorted((re.escape(t) for t in terms), key=len, reverse=True))
        rx = re.compile(rf"(?<![A-Za-z])(?:{alts})(?![A-Za-z])", re.I) if terms else None
        cs = "|".join(sorted((re.escape(c.capitalize()) for c in caps), key=len, reverse=True))
        rx_cs = re.compile(rf"(?<![A-Za-z])(?:{cs})(?![A-Za-z])") if caps else None
        return cls(rx, rx_cs, len(terms) + len(caps))

    def find(self, text: str) -> str | None:
        for rx in (self.pattern, self.case_sensitive):
            m = rx.search(text) if rx is not None else None
            if m:
                return m.group(0)
        return None


SITE_NAMES_FILE = Path(__file__).resolve().parents[3] / "data" / "chat" / "site_names.yaml"


def load_site_names(repo: Path, sites_path: Path | None = None) -> SiteNames:
    env = os.environ.get("CARECOST_SITES_PATH")
    path = sites_path or (Path(env) if env else repo / "data" / "sites" / "sites.yaml")
    cfg = yaml.safe_load((repo / "data" / "chat" / "site_names.yaml").read_text())
    sites = yaml.safe_load(path.read_text())["sites"] if path.exists() else []
    texts: list[str] = []
    for site in sites:
        texts += [site.get("name") or "", site.get("operator") or ""]
        texts += [site.get("ownership_detail") or "", (site.get("address") or {}).get("city") or ""]
    return SiteNames.build(
        texts, cfg.get("aliases", []), cfg.get("generic_words", []),
        cfg.get("capitalized_only", []),
    )  # fmt: skip


def check_site_names(text: str | None, names: SiteNames | None) -> None:
    if not text or names is None:
        return
    hit = names.find(text)
    if hit:
        raise GuardError(
            f"LLM text may not name a site, operator or chain ({hit!r}): the list does"
        )


def check_value(text: str | None, price_turn: bool) -> None:
    if not text:
        return
    m = _VALUE_EN.search(text) or _VALUE_ZH.search(text)
    if m is None and price_turn:
        m = _PRICE_NOUNS.search(text) or _CARDINALS.search(text)
    if m:
        raise GuardError(
            f"LLM text may not talk about money or value ({m.group(0)!r}): the receipt does"
        )


def check_urgency(text: str | None) -> None:
    if not text:
        return
    m = _URGENCY_EN.search(text) or _ER.search(text) or _URGENCY_ZH.search(text)
    if m:
        raise GuardError(
            f"LLM text may not judge urgency ({m.group(0)!r}): only red-flag copy does"
        )


def check_spelled_links(text: str | None) -> None:
    if not text:
        return
    m = _SPELLED_LINK.search(text)
    if m:
        raise GuardError(f"LLM text may not contain a link ({m.group(0)!r})")
