"""Reader for the site facts S0 writes (X1): what each site's own website says it offers.

    data/sites/site_facts/capabilities.yaml   capability id -> the care-path steps it performs
    data/sites/site_facts/facts.yaml          site id -> capability -> offered | not_offered | unknown

Only a claim with status ``agreed`` (both independent runs agree and every quote is found
verbatim in the cached page) or ``austin_reviewed`` is evidence; ``disputed`` and a missing entry
are unknown. Both files absent = no site facts (the engine works without them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.quote.store import REPO_ROOT

FACTS_DIR = REPO_ROOT / "data" / "sites" / "site_facts"
EVIDENCE = frozenset({"agreed", "austin_reviewed"})


@dataclass
class SiteFacts:
    """site id -> {(path id, step id): "offered" | "not_offered"} (evidence only)."""

    steps: dict[str, dict[tuple[str, str], str]] = field(default_factory=dict)

    def step(self, site_id: str, path_id: str, step_id: str) -> str | None:
        return self.steps.get(site_id, {}).get((path_id, step_id))


def load_site_facts(root: Path = FACTS_DIR) -> SiteFacts:
    caps_p, facts_p = root / "capabilities.yaml", root / "facts.yaml"
    if not (caps_p.exists() and facts_p.exists()):
        return SiteFacts()
    caps = yaml.safe_load(caps_p.read_text()) or {}
    facts = yaml.safe_load(facts_p.read_text()) or {}
    for doc, name in ((caps, "capabilities.yaml"), (facts, "facts.yaml")):
        if doc.get("version") != 1:
            raise ValueError(f"site_facts/{name}: version must be 1 (X1)")
    covers: dict[str, list[tuple[str, str]]] = {
        cid: [(c["path"], c["step"]) for c in (spec.get("covers") or [])]
        for cid, spec in (caps.get("capabilities") or {}).items()
    }
    out: dict[str, dict[tuple[str, str], str]] = {}
    for sid, rec in (facts.get("sites") or {}).items():
        for cid, claim in ((rec or {}).get("capabilities") or {}).items():
            if cid not in covers:
                raise ValueError(f"site_facts {sid}: unknown capability {cid!r}")
            value, status = claim.get("value"), claim.get("status")
            if value not in ("offered", "not_offered", "unknown"):
                raise ValueError(f"site_facts {sid}.{cid}: bad value {value!r}")
            if status not in ("agreed", "austin_reviewed", "disputed"):
                raise ValueError(f"site_facts {sid}.{cid}: bad status {status!r}")
            if status not in EVIDENCE or value == "unknown":
                continue
            if status == "agreed" and not claim.get("evidence"):
                raise ValueError(f"site_facts {sid}.{cid}: an agreed claim needs its evidence")
            steps = out.setdefault(sid, {})
            for key in covers[cid]:
                # "offered" by any capability wins over another capability's "not_offered"
                if steps.get(key) != "offered":
                    steps[key] = value
    return SiteFacts(out)
