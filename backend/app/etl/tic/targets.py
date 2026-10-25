"""Provider targets: which TiC provider groups become ``rate_row`` rows.

Matching is on identifiers only, never on business names (UHC lists AFC as "MVNE 1"):

1. **NPI first.** A group matches when any of its NPIs is a target NPI (a site's org NPI). That
   automatically collects *every* TIN the site's NPIs bill under (AFC NPIs appear under three
   UHC TINs at once; AFC has 9+ franchisee TINs).
2. **TIN.** A group also matches when its TIN digits are a target TIN (EIN, or a 10-digit
   ``tin.type = npi``).

The list is ``data/etl/tic_provider_targets.csv`` (built from research-v3/clinic-census.csv,
tins.tsv and the AFC franchisee list; A3's NPPES/DPH/CMS set replaces it later). Staging keeps
every provider group of every file, so a new target list only needs ``tic normalize`` again.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from app.etl.config import CONFIG_DIR

TARGETS_CSV = "tic_provider_targets.csv"


@dataclass
class Targets:
    tins: dict[str, set[str]] = field(default_factory=dict)  # tin digits -> site ids ('' = no site)
    npis: dict[str, set[str]] = field(default_factory=dict)  # npi -> site ids

    def match(self, tin_digits: str, npis: list[str]) -> str:
        """'' (no match) / 'npi' / 'tin' / 'npi+tin'."""
        by_npi = any(n in self.npis for n in npis)
        by_tin = bool(tin_digits) and tin_digits in self.tins
        return "npi+tin" if by_npi and by_tin else "npi" if by_npi else "tin" if by_tin else ""

    def sites_for(self, tin_digits: str, npis: list[str]) -> set[str]:
        out: set[str] = set()
        for n in npis:
            out |= self.npis.get(n, set())
        out |= self.tins.get(tin_digits, set())
        out.discard("")
        return out


def load_targets(path: Path | None = None) -> Targets:
    p = path or (CONFIG_DIR / TARGETS_CSV)
    t = Targets()
    with p.open(newline="") as f:
        for r in csv.DictReader(f):
            v = "".join(ch for ch in r["value"] if ch.isdigit())
            if not v:
                continue
            d = t.npis if r["kind"] == "npi" else t.tins
            d.setdefault(v, set()).add(r.get("site_id") or "")
    return t
