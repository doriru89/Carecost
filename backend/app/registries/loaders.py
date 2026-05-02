"""Registry loaders — parse YAML, validate with Pydantic, cache at first call.

Usage:
    from app.registries import get_bundle, get_hospital, get_payer
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml
from pydantic import BaseModel

_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "registries"


class BundleEntry(BaseModel):
    cpt: str
    label: str
    specialty: str
    description: str
    tags: list[str] = []
    aliases_to: str | None = None


class HospitalEntry(BaseModel):
    name: str
    system: str
    neighborhood: str
    lat: float
    lng: float
    npi: str | None = None
    alternate_npis: list[str] = []
    address_patterns: list[str] = []
    source_name_aliases: dict[str, str] | None = None


class PayerEntry(BaseModel):
    slug: str
    label: str
    carrier_patterns: list[str]
    is_default: bool = False
    normalization_patterns: list[str] | None = None
    tic_portal: str | None = None
    legal_basis: str | None = None


class SpecialtyEntry(BaseModel):
    taxonomy: str
    default_scenario: str
    data_file: str = ""
    providers_file: str = ""
    is_default: bool = False


@functools.lru_cache(maxsize=1)
def _load_bundles() -> dict[str, BundleEntry]:
    raw = yaml.safe_load((_DATA_DIR / "cpt_bundles.yaml").read_text())
    return {k: BundleEntry(**v) for k, v in raw["bundles"].items()}


@functools.lru_cache(maxsize=1)
def _load_hospitals() -> dict[str, HospitalEntry]:
    raw = yaml.safe_load((_DATA_DIR / "hospitals.yaml").read_text())
    return {k: HospitalEntry(**v) for k, v in raw["hospitals"].items()}


@functools.lru_cache(maxsize=1)
def _load_payers() -> dict[str, PayerEntry]:
    raw = yaml.safe_load((_DATA_DIR / "payers.yaml").read_text())
    return {k: PayerEntry(**v) for k, v in raw["payers"].items()}


@functools.lru_cache(maxsize=1)
def _load_specialties() -> dict[str, SpecialtyEntry]:
    raw = yaml.safe_load((_DATA_DIR / "specialties.yaml").read_text())
    return {k: SpecialtyEntry(**v) for k, v in raw["specialties"].items()}


def get_bundle(bundle_id: str) -> BundleEntry:
    bundles = _load_bundles()
    if bundle_id not in bundles:
        raise KeyError(f"Unknown bundle_id: {bundle_id}. Available: {list(bundles.keys())}")
    return bundles[bundle_id]


def get_cpt_for_bundle(bundle_id: str) -> str:
    return get_bundle(bundle_id).cpt


def bundles_for_specialty(specialty: str) -> dict[str, BundleEntry]:
    return {k: v for k, v in _load_bundles().items() if v.specialty == specialty}


def all_bundle_ids() -> list[str]:
    return list(_load_bundles().keys())


def get_hospital(hospital_id: str) -> HospitalEntry:
    hospitals = _load_hospitals()
    if hospital_id not in hospitals:
        raise KeyError(f"Unknown hospital_id: {hospital_id}. Available: {list(hospitals.keys())}")
    return hospitals[hospital_id]


def all_hospitals() -> dict[str, HospitalEntry]:
    return dict(_load_hospitals())


def hospital_id_by_name(name: str) -> str | None:
    for hid, h in _load_hospitals().items():
        if h.name == name:
            return hid
    return None


def infer_hospital_from_address(address: str, city: str) -> str:
    text = f"{address} {city}".upper()
    for hid, h in _load_hospitals().items():
        if any(p.upper() in text for p in h.address_patterns):
            return h.name
    return ""


def get_payer(payer_id: str) -> PayerEntry:
    payers = _load_payers()
    if payer_id not in payers:
        raise KeyError(f"Unknown payer_id: {payer_id}. Available: {list(payers.keys())}")
    return payers[payer_id]


def all_payers() -> dict[str, PayerEntry]:
    return dict(_load_payers())


def default_payer_id() -> str:
    for pid, p in _load_payers().items():
        if p.is_default:
            return pid
    return next(iter(_load_payers()))


def carrier_to_payer_id(carrier: str | None) -> str:
    if not carrier or not str(carrier).strip():
        return default_payer_id()
    c = str(carrier).lower()
    for pid, p in _load_payers().items():
        if any(pat in c for pat in p.carrier_patterns):
            return pid
    return default_payer_id()


def payer_id_to_slug(payer_id: str) -> str:
    return get_payer(payer_id).slug


def slug_to_payer_id(slug: str) -> str:
    for pid, p in _load_payers().items():
        if p.slug == slug:
            return pid
    return default_payer_id()


def get_specialty(name: str) -> SpecialtyEntry:
    specialties = _load_specialties()
    for key, s in specialties.items():
        if key.lower() == name.lower():
            return s
    raise KeyError(f"Unknown specialty: {name}. Available: {list(specialties.keys())}")


def all_specialty_names() -> list[str]:
    return list(_load_specialties().keys())


def default_specialty() -> str:
    for name, s in _load_specialties().items():
        if s.is_default:
            return name
    return next(iter(_load_specialties()))


class EtlConfig(BaseModel):
    mrf_formats: dict[str, dict]
    cpt_extraction_sets: dict[str, list[str]]
    hospital_mrf_sources: dict[str, dict] = {}
    non_canonical_payers: dict[str, dict]


@functools.lru_cache(maxsize=1)
def _load_etl_config() -> EtlConfig:
    raw = yaml.safe_load((_DATA_DIR / "etl_config.yaml").read_text())
    return EtlConfig(**raw["etl"])


def load_etl_config() -> EtlConfig:
    return _load_etl_config()


def hospital_npi_map() -> dict[str, str]:
    return {hid: h.npi for hid, h in _load_hospitals().items() if h.npi}


def hospital_all_npis() -> dict[str, str]:
    """Map NPI -> hospital_id for primary and alternate NPIs."""
    result: dict[str, str] = {}
    for hid, h in _load_hospitals().items():
        if h.npi:
            result[h.npi] = hid
        for alt in h.alternate_npis:
            result[alt] = hid
    return result


def hospital_name_for_source(hospital_id: str, source: str) -> str | None:
    h = _load_hospitals().get(hospital_id)
    if not h or not h.source_name_aliases:
        return None
    return h.source_name_aliases.get(source)


def validate_all_registries() -> dict[str, int]:
    """Load and validate all registries. Returns counts. Raises on any error."""
    bundles = _load_bundles()
    hospitals = _load_hospitals()
    payers = _load_payers()
    specialties = _load_specialties()

    for bid, b in bundles.items():
        if b.specialty not in specialties:
            raise ValueError(f"Bundle '{bid}' references unknown specialty '{b.specialty}'")
        if b.aliases_to and b.aliases_to not in bundles:
            raise ValueError(f"Bundle '{bid}' aliases_to unknown bundle '{b.aliases_to}'")

    npis = [h.npi for h in hospitals.values() if h.npi]
    if len(npis) != len(set(npis)):
        dupes = [n for n in npis if npis.count(n) > 1]
        raise ValueError(f"Duplicate hospital NPIs: {set(dupes)}")

    valid_sources = {"tic", "turquoise", "masscomparecare", "mrf"}
    for hid, h in hospitals.items():
        if h.source_name_aliases:
            for key in h.source_name_aliases:
                if key not in valid_sources:
                    raise ValueError(f"Hospital '{hid}' has unknown source alias key: {key}")

    defaults = [pid for pid, p in payers.items() if p.is_default]
    if len(defaults) != 1:
        raise ValueError(f"Expected exactly 1 default payer, found {len(defaults)}: {defaults}")

    return {
        "bundles": len(bundles),
        "hospitals": len(hospitals),
        "payers": len(payers),
        "specialties": len(specialties),
    }
