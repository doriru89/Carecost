"""The skip-AI catalog (D3): care paths and the services in them, built from the care paths.

One service per step that has a price (keyed by the step's first primary code, ``svc_<code>``);
the same service in several care paths is listed once with every path id. Names are the step's
own plain / technical names (the first path in id order wins), so the catalog never says
anything the care paths do not.
"""

from __future__ import annotations

from typing import Any

from app.quote.contracts import Catalog
from app.quote.registry import Registry

CATALOG_VERSION = "1.0.0"


def build_catalog(reg: Registry) -> Catalog:
    paths = sorted(reg.paths.values(), key=lambda p: p.id)
    services: dict[str, dict[str, Any]] = {}
    for path in paths:
        areas = reg.path_areas(path)
        for st in path.steps:
            primary = [c for c in st.cpts if c.role == "primary"]
            if st.no_price or not primary:
                continue
            sid = f"svc_{primary[0].code.lower()}"
            svc = services.setdefault(
                sid,
                {
                    "service_id": sid,
                    "plain_name": st.plain.name,
                    "technical_name": st.plain.technical_name,
                    "kind": st.kind,
                    "areas": set(),
                    "codes": {},
                    "care_paths": [],
                    "glossary_keys": [],
                },
            )
            svc["areas"] |= areas
            for c in st.cpts:
                desc = reg.describe(c.code) or c.note or st.plain.technical_name
                svc["codes"].setdefault(c.code, {"code": c.code, "role": c.role, "description": desc})
            if path.id not in svc["care_paths"]:
                svc["care_paths"].append(path.id)
            for g in st.glossary:
                if g in reg.glossary and g not in svc["glossary_keys"]:
                    svc["glossary_keys"].append(g)
    return Catalog.model_validate(
        {
            "version": CATALOG_VERSION,
            "care_paths": [
                {
                    "id": p.id,
                    "title": p.title.en,
                    "area": p.scope.area,
                    "review_status": p.review.status,
                }
                for p in paths
            ],
            "services": [
                {**s, "areas": sorted(s["areas"]), "codes": list(s["codes"].values())}
                for _, s in sorted(services.items())
            ],
        }
    )
