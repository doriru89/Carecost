"""The skip-AI catalog (D3): care paths and the services in them, built from the care paths.

One service per step that has a price (keyed by the step's first primary code, ``svc_<code>``);
the same service in several care paths is listed once with every path id. Names come from the
care paths, so the catalog never says anything they do not:

* listed under a path (``GET /api/catalog/paths/{id}/services``): that path's own step names;
* in the global list: the step's names when every path names the service the same, else a
  neutral name, the code's own short description (codes.yaml), so the shoulder picker never
  reads "Guided exercise program for the ankle" (D2, C2).
"""

from __future__ import annotations

from typing import Any

from app.quote.contracts import Catalog
from app.quote.registry import Registry

CATALOG_VERSION = "1.0.0"


def path_service_names(reg: Registry) -> dict[tuple[str, str], tuple[str, str]]:
    """(path id, service id) -> (plain name, technical name) of that path's step."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for path in sorted(reg.paths.values(), key=lambda p: p.id):
        for st in path.steps:
            primary = [c for c in st.cpts if c.role == "primary"]
            if st.no_price or not primary:
                continue
            key = (path.id, f"svc_{primary[0].code.lower()}")
            out.setdefault(key, (st.plain.name, st.plain.technical_name))
    return out


def path_services(cat: Catalog, names: dict[tuple[str, str], tuple[str, str]],
                  path_id: str) -> list[dict[str, Any]]:  # fmt: skip
    """The services of one care path, each under that path's own step names."""
    out = []
    for s in cat.services:
        if path_id not in s.care_paths:
            continue
        d = s.model_dump(mode="json")
        d["plain_name"], d["technical_name"] = names[(path_id, s.service_id)]
        out.append(d)
    return out


def build_catalog(reg: Registry) -> Catalog:
    paths = sorted(reg.paths.values(), key=lambda p: p.id)
    services: dict[str, dict[str, Any]] = {}
    names = path_service_names(reg)
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
                svc["codes"].setdefault(
                    c.code, {"code": c.code, "role": c.role, "description": desc}
                )
            if path.id not in svc["care_paths"]:
                svc["care_paths"].append(path.id)
            for g in st.glossary:
                if g in reg.glossary and g not in svc["glossary_keys"]:
                    svc["glossary_keys"].append(g)
    for sid, svc in services.items():
        seen = {names[(pid, sid)] for pid in svc["care_paths"]}
        if len(seen) > 1:  # paths name it differently: a neutral name in the global list
            code = next(c for c in svc["codes"].values() if c["role"] == "primary")["code"]
            neutral = reg.describe(code) or svc["technical_name"]
            svc["plain_name"], svc["technical_name"] = neutral, neutral
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
