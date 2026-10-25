"""Everything the quote engine reads besides rate rows: sites, care paths, payer networks, rules.

* **Sites** (D27, P1 problem 12): ``CARECOST_SITES_PATH`` or A3's ``data/sites/sites.yaml`` (208
  sites) by default; ``contracts/fixtures/sites.json`` (6 sites) is the small test registry. JSON
  or YAML; every entry is validated with the ``Site`` contract. Joined to TiC by ``Site.tins`` +
  ``Site.tin_npis`` + ``Site.type_2_npis``, and by ``Site.census_id`` <-> the TiC rows'
  ``tic_site_ids`` (the pack's ``census_tins``).
* **Radiology groups** (P1 problem 6): ``data/sites/radiology_groups.yaml`` (A3), the billing
  TINs of the radiologists who read at each hospital.
* **Data-quality notices**: ``data/etl/data_quality_notices.yaml`` (A3), shown on the summary of
  every site priced by the named file.
* **Payment -> TiC networks** (P1 problem 3): ``data/etl/tic_networks.yaml`` (A2). An insurance
  payment ``{payer_id, product, network}`` reads every network file of that payer and product,
  or only the named network (``network`` matches the file id, e.g. ``hmo_blue`` selects
  ``tic_bcbs_ma_hmo_blue_fi`` and ``_si``). The person rarely knows whether their employer plan is
  fully or self insured, so both files are read into one range; when they differ the range is
  wider and both ends are cited (``Money.prov_high``).
* **Visit-code map** (``data/etl/tic_visit_codes.yaml``): how each payer prices an office visit
  (Aetna: urgent-care global code S9083).
* **Rules**: ``data/quote/engine.yaml``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from app.care_paths.loader import load_paths
from app.care_paths.models import CarePath
from app.etl.config import load_codes, load_sources
from app.etl.tic.networks import TicNetwork, VisitMap, load_networks, load_visit_map
from app.quote.store import REPO_ROOT, SourceMeta
from app.registries import all_hospitals
from app.sites.contracts import Site, SitesFile

DEFAULT_SITES = REPO_ROOT / "data" / "sites" / "sites.yaml"
FIXTURE_SITES = REPO_ROOT / "contracts" / "fixtures" / "sites.json"
RADIOLOGY_GROUPS = REPO_ROOT / "data" / "sites" / "radiology_groups.yaml"
DATA_NOTICES = REPO_ROOT / "data" / "etl" / "data_quality_notices.yaml"
ENGINE_CONFIG = REPO_ROOT / "data" / "quote" / "engine.yaml"
PAYER_ALIASES = REPO_ROOT / "data" / "etl" / "payer_aliases.yaml"
GLOSSARY = REPO_ROOT / "content" / "glossary" / "glossary.yaml"
CPT_REGISTRY = REPO_ROOT / "data" / "care_paths" / "cpt_registry_2026.json"


def sites_path() -> Path:
    return Path(os.environ.get("CARECOST_SITES_PATH") or DEFAULT_SITES)


def load_sites(path: Path | None = None) -> tuple[int, dict[str, Site]]:
    """-> (sites file version, {id: Site}). Fixture markers are stripped; everything else must
    pass ``SitesFile``."""
    p = path or sites_path()
    text = p.read_text()
    doc = json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)
    doc.pop("_fixture", None)
    doc.pop("_schema", None)
    f = SitesFile.model_validate(doc)
    return f.version, {s.id: s for s in f.sites}


def posted_source(site: Site) -> SourceMeta | None:
    """A site's own posted self-pay page as a source (clinic_posted). Its sha is the page's
    ``page_sha256`` when the weekly checker recorded one, else the sha256 of the normalized JSON
    of the price table as sites.yaml holds it (the same definition the checker uses)."""
    if not site.cash_prices:
        return None
    sha = next((p.page_sha256 for p in site.cash_prices if p.page_sha256), None)
    if sha is None:
        table = [
            p.model_dump(mode="json") for p in sorted(site.cash_prices, key=lambda p: p.item_id)
        ]
        sha = hashlib.sha256(json.dumps(table, sort_keys=True).encode()).hexdigest()
    url = site.cash_prices[0].source_url
    base = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "page"
    checked = max(p.checked_at for p in site.cash_prices).isoformat()
    return SourceMeta(
        source_id=f"posted_{site.id}",
        source_kind="clinic_posted",
        publisher=site.name,
        source_file=re.sub(r"[^A-Za-z0-9._-]", "_", base),
        source_sha256=sha,
        source_date=None,
        last_updated=None,  # the page prints no date: never "late" (posted_page_date_365_days)
        fetched_at=checked,
        source_rule="posted_page_date_365_days",
        our_rule="sites_weekly",
    )


@dataclass
class Registry:
    sites_version: int
    sites: dict[str, Site]
    paths: dict[str, CarePath]
    config: dict[str, Any]
    networks: list[TicNetwork]
    visit_map: VisitMap

    @classmethod
    def load(cls, sites_file: Path | None = None) -> Registry:
        version, sites = load_sites(sites_file)
        return cls(
            sites_version=version,
            sites=sites,
            paths=load_paths(),
            config=yaml.safe_load(ENGINE_CONFIG.read_text()),
            networks=load_networks(),
            visit_map=load_visit_map(),
        )

    # ------------------------------------------------------------------ derived lookups

    @cached_property
    def aliases(self) -> dict[str, Any]:
        return yaml.safe_load(PAYER_ALIASES.read_text())

    @cached_property
    def payer_labels(self) -> dict[str, str]:
        return {k: v["label"] for k, v in self.aliases["payers"].items()}

    @cached_property
    def products(self) -> set[str]:
        return set(self.aliases["products"])

    @cached_property
    def glossary(self) -> set[str]:
        return set(yaml.safe_load(GLOSSARY.read_text())["terms"])

    @cached_property
    def codes(self):
        return load_codes()

    @cached_property
    def pc_tc_codes(self) -> set[str]:
        """Codes with a professional / technical split in the CMS PFS file (imaging, pathology):
        at a hospital the doctor's part is the reading, billed with modifier 26."""
        d = json.loads(CPT_REGISTRY.read_text())["codes"]
        out = {c for c, v in d.items() if v.get("has_professional_technical_split")}
        # codes outside the registry: radiology (7xxxx) and surgical pathology (88xxx) split too
        return out | {c for c in self.codes.codes if c[:1] == "7" or c.startswith("88")}

    @cached_property
    def hospital_source(self) -> dict[str, str]:
        """hospitals.yaml entity id -> its hospital MRF source id."""
        return {
            s.entity_id: s.source_id
            for s in load_sources().sources
            if s.kind.value == "hospital_mrf" and s.entity_id
        }

    @cached_property
    def hospital_names(self) -> dict[str, str]:
        return {k: v.name for k, v in all_hospitals().items()}

    @cached_property
    def radiology_tins(self) -> dict[str, list[str]]:
        """hospitals.yaml id -> the billing TINs of the radiologists who read there, most
        radiologists first (radiology_groups.yaml; every listed TIN holds >= 25% of a group)."""
        doc = yaml.safe_load(RADIOLOGY_GROUPS.read_text()) if RADIOLOGY_GROUPS.exists() else {}
        out: dict[str, list[str]] = {}
        for hosp, groups in (doc.get("hospitals") or {}).items():
            share: dict[str, int] = {}
            for g in groups:
                for t in g["tins"]:
                    tin = t["tin"]
                    if not (isinstance(tin, str) and re.fullmatch(r"[0-9]{9}", tin)):
                        raise ValueError(f"radiology_groups.yaml {hosp}: TIN {tin!r} (quote it)")
                    share[tin] = share.get(tin, 0) + int(t["radiologists"])
            out[hosp] = sorted(share, key=lambda t: (-share[t], t))
        return out

    @cached_property
    def data_notices(self) -> dict[str, list[dict[str, Any]]]:
        """source_id -> its data-quality notices (data_quality_notices.yaml)."""
        doc = yaml.safe_load(DATA_NOTICES.read_text()) if DATA_NOTICES.exists() else {}
        out: dict[str, list[dict[str, Any]]] = {}
        for n in doc.get("notices") or []:
            out.setdefault(n["source_id"], []).append({
                "id": n["id"], "kind": n["kind"], "source_id": n["source_id"],
                "observed": str(n["observed"]), "detail": n["detail"],
                "effect": n.get("effect"),
            })  # fmt: skip
        return out

    def site_tins(self, s: Site) -> list[str]:
        """A site's own billing TINs / NPIs, in a stable order."""
        out = [*s.tins, *s.tin_npis, *s.type_2_npis]
        return list(dict.fromkeys(out))

    @cached_property
    def tins(self) -> set[str]:
        """Every billing TIN / NPI the registry links to a quotable site, plus the hospitals'
        radiology groups (the pack load filter; census-linked TINs are added by the loader)."""
        out: set[str] = set()
        for s in self.sites.values():
            out |= set(self.site_tins(s))
            if s.hospital_entity_id:
                out |= set(self.radiology_tins.get(s.hospital_entity_id, ()))
        return out

    @cached_property
    def census_ids(self) -> set[str]:
        return {s.census_id for s in self.sites.values() if s.census_id}

    def medicare_locality(self, site: Site) -> str:
        """CMS PFS locality of a site: 01 Metropolitan Boston = Middlesex, Norfolk and Suffolk
        counties (RVU26D 26LOCCO.csv line 84), else 99 rest of Massachusetts. engine.yaml lists
        the registry's cities outside those counties."""
        cfg = self.config["medicare_locality"]
        return cfg["rest_of_state"] if site.address.city in cfg["rest_of_state_cities"] else (
            cfg["default"])  # fmt: skip

    def networks_for(self, payer_id: str, product: str, network: str | None) -> list[str]:
        """TiC files for an insurance payment, in a stable order (P1 problem 3)."""
        out = []
        for n in self.networks:
            if n.payer_id != payer_id or (n.product or product) != product:
                continue
            if network is not None and f"_{network}_" not in f"{n.source_id}_":
                continue
            out.append(n.source_id)
        return sorted(out)

    def area_ok(self, site: Site, areas: set[str]) -> bool:
        return bool(set(site.service_areas) & areas)

    def path_areas(self, path: CarePath) -> set[str]:
        return set(self.config["areas"][path.scope.area])

    def code_areas(self, code: str) -> set[str]:
        out: set[str] = set()
        for d in self.codes.domains_for(code):
            out |= set(self.config["code_domains"][d])
        if self.pctc.get(code) == "9" and code[:1] == "8":  # C4b item 6: a clinical lab code
            out |= set(self.config.get("clinical_lab_areas") or ())
        return out

    @cached_property
    def pctc(self) -> dict[str, str]:
        from app.quote.pctc import load_pctc

        return load_pctc(REPO_ROOT / self.config["pctc_file"])

    def describe(self, code: str) -> str | None:
        return self.codes.description(code) or None
