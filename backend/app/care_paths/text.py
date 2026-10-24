"""Text helpers shared by the schema, validator and red-flag matcher."""

from __future__ import annotations

import re
import unicodedata

_PUNCT_MAP = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "‐": "-",
    "‑": "-",
    " ": " ",
}


def normalize(s: str) -> str:
    """NFKC, straight quotes/dashes, collapsed whitespace. Used for verbatim quote matching."""
    s = unicodedata.normalize("NFKC", s)
    for k, v in _PUNCT_MAP.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s).strip()


def word_count(s: str) -> int:
    return len(normalize(s).split())


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", normalize(s).lower())
