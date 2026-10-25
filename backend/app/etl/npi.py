"""NPI validity at the ETL boundary: placeholders never reach the pack (R10).

Insurers publish placeholder NPIs (``"0"`` in 73 Aetna / Tufts provider groups, 7,566 rows) that
then fail the quote contract's ``^[0-9]{10}$`` and 500 a whole quote. An NPI is kept only when it
is 10 digits with a valid check digit (CMS NPI standard: Luhn over the prefix ``80840`` + the
first 9 digits). Everything else is dropped and counted per source; the staged row keeps the raw
values in ``extra`` (``dropped_npis``) so staging stays lossless.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

_TEN = re.compile(r"^[0-9]{10}$")


def is_valid_npi(npi: str) -> bool:
    s = str(npi).strip()
    if not _TEN.match(s):
        return False
    digits = [int(c) for c in "80840" + s[:9]]
    total = 0
    for i, d in enumerate(reversed(digits)):  # double every other digit, from the right
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(s[9])


def clean_npis(npis: Iterable[str]) -> tuple[list[str], list[str]]:
    """-> (kept valid NPIs, dropped raw values), order kept."""
    kept: list[str] = []
    dropped: list[str] = []
    for n in npis:
        (kept if is_valid_npi(n) else dropped).append(str(n))
    return kept, dropped


def placeholder_key(raw: str) -> str:
    """Bucket for the per-source count: the value itself when short (``"0"``), else its shape."""
    s = str(raw).strip()
    if len(s) <= 4:
        return s or "(empty)"
    return "bad_check_digit" if _TEN.match(s) else f"not_10_digits:{len(s)}"


def count(dropped: Iterable[str]) -> dict[str, int]:
    return dict(Counter(placeholder_key(d) for d in dropped))
