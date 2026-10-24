"""ETL configuration: file locations and the typed views of ``data/etl/*.yaml``.

Data root resolution (same rule locally and in GitHub Actions):
``--data-dir`` flag > ``CARECOST_DATA_DIR`` env var > ``<repo>/data``.

Layout under the data root::

    etl/*.yaml                                   committed config (sources, codes, payers, gates)
    raw/store/<source_id>/<sha256><ext>          content-addressed downloads (gitignored)
    raw/store/fetch_manifest.jsonl               one line per fetch/import
    intermediate/staging/<source_id>/<sha>.parquet   lossless staged rows (gitignored)
    intermediate/normalized/<source_id>/<sha>.parquet rate_row for the target codes
    build/<build_id>/                            rate_row.parquet + .sqlite + manifest + report
"""

from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.etl.contracts import SourceKind, StrEnum

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "data" / "etl"


@dataclass(frozen=True)
class Paths:
    data: Path

    @classmethod
    def resolve(cls, data_dir: str | Path | None = None) -> Paths:
        d = data_dir or os.environ.get("CARECOST_DATA_DIR") or (REPO_ROOT / "data")
        return cls(Path(d).resolve())

    @property
    def store(self) -> Path:
        return self.data / "raw" / "store"

    @property
    def fetch_manifest(self) -> Path:
        return self.store / "fetch_manifest.jsonl"

    @property
    def staging(self) -> Path:
        return self.data / "intermediate" / "staging"

    @property
    def normalized(self) -> Path:
        return self.data / "intermediate" / "normalized"

    @property
    def builds(self) -> Path:
        return self.data / "build"


class FetchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_domains: list[str]
    default_max_bytes: int = Field(gt=0)
    timeout_s: float = 600


class ReferenceKind(StrEnum):
    """Sources that carry no consumer price: who a provider is, where, who bills for whom.

    Kept out of ``SourceKind`` on purpose: ``SourceKind`` is the price provenance a ``Money``
    can carry (the source chip); a reference row never becomes a ``Money``.
    """

    provider_registry = "provider_registry"  # NPPES (NPI -> name, taxonomy, practice locations)
    provider_directory = (
        "provider_directory"  # payer public FHIR Provider Directory (network membership)
    )
    facility_registry = "facility_registry"  # DPH licensed facilities, CMS Provider of Services
    clinician_directory = (
        "clinician_directory"  # CMS Doctors & Clinicians (NPI -> group PAC id, affiliations)
    )
    billing_relationship = (
        "billing_relationship"  # CMS Reassignment (individual NPI -> billing group)
    )
    utilization = "utilization"  # CMS Physician & Other Practitioners by Provider and Service
    plan_benefits = "plan_benefits"  # CMS QHP PUF (deductibles, plan ids)


SourceFormat = Literal[
    # hospital price transparency files (the rate_row pipeline: stage -> normalize -> build)
    "cms_v3_csv_tall",
    "cms_v3_csv_wide",
    "cms_v3_json",
    # insurer Transparency in Coverage
    "tic_table_of_contents",  # the index JSON that lists in_network file URLs
    "tic_in_network",  # one in_network .json.gz, read with HTTP Range against a seek index
    # registries and directories (no prices)
    "nppes_monthly",  # NPPES monthly zip: main + pl_pfile + othername_pfile + endpoint_pfile CSVs
    "dph_xlsx",  # MA DPH facility lists
    "fhir_provider_directory",  # payer public Provider Directory FHIR API, paged Bundles, no auth
    "cms_dataset_csv",  # data.cms.gov dataset as a CSV download
    "cms_dataset_api",  # data.cms.gov data API (paged JSON, filters e.g. state=MA)
    # government fee schedules
    "cms_pfs_rvu",  # PFS relative value file (PPRRVU + GPCI), zip of csv/xlsx
    "cms_pfs_anes",  # PFS anesthesia conversion factors (ANES)
    "cms_opps_addendum",  # OPPS Addendum B / AA
    "cms_asc_addendum",  # ASC Addendum AA / BB
    "masshealth_fee_schedule",  # 101 CMR 316/317/318 tables (pdf or xlsx)
    # a clinic's own posted self-pay page
    "html_price_page",
]

MRF_FORMATS: frozenset[str] = frozenset({"cms_v3_csv_tall", "cms_v3_csv_wide", "cms_v3_json"})
"""The only formats the rate_row pipeline (stage / normalize / build / report) reads today."""

Media = Literal["csv", "json", "xlsx", "pdf", "html"]
Access = Literal["download", "http_range", "paged_api"]
AnyKind = SourceKind | ReferenceKind

# format -> (allowed kinds, allowed media (first = default), allowed containers, allowed access)
_FORMAT_RULES: dict[str, tuple[set[str], tuple[str, ...], set[str], set[str]]] = {
    "cms_v3_csv_tall": ({"hospital_mrf"}, ("csv",), {"zip", "plain"}, {"download"}),
    "cms_v3_csv_wide": ({"hospital_mrf"}, ("csv",), {"zip", "plain"}, {"download"}),
    "cms_v3_json": ({"hospital_mrf"}, ("json",), {"zip", "plain"}, {"download"}),
    "tic_table_of_contents": ({"insurer_tic"}, ("json",), {"plain", "gzip"}, {"download"}),
    "tic_in_network": ({"insurer_tic"}, ("json",), {"gzip", "plain"}, {"http_range", "download"}),
    "nppes_monthly": ({"provider_registry"}, ("csv",), {"zip"}, {"download"}),
    "dph_xlsx": ({"facility_registry"}, ("xlsx",), {"plain"}, {"download"}),
    "fhir_provider_directory": ({"provider_directory"}, ("json",), {"plain"}, {"paged_api"}),
    "cms_dataset_csv": (
        {
            "clinician_directory",
            "billing_relationship",
            "facility_registry",
            "utilization",
            "plan_benefits",
        },
        ("csv",),
        {"plain", "zip"},
        {"download"},
    ),
    "cms_dataset_api": (
        {
            "clinician_directory",
            "billing_relationship",
            "facility_registry",
            "utilization",
            "plan_benefits",
        },
        ("json",),
        {"plain"},
        {"paged_api"},
    ),
    "cms_pfs_rvu": ({"medicare_pfs"}, ("csv", "xlsx"), {"zip", "plain"}, {"download"}),
    "cms_pfs_anes": ({"medicare_pfs"}, ("csv", "xlsx"), {"zip", "plain"}, {"download"}),
    "cms_opps_addendum": ({"medicare_opps"}, ("csv", "xlsx"), {"zip", "plain"}, {"download"}),
    "cms_asc_addendum": ({"medicare_asc"}, ("csv", "xlsx"), {"zip", "plain"}, {"download"}),
    "masshealth_fee_schedule": ({"masshealth_fs"}, ("pdf", "xlsx"), {"plain"}, {"download"}),
    "html_price_page": ({"clinic_posted"}, ("html",), {"plain"}, {"download"}),
}

NPPES_MEMBERS = frozenset({"main", "pl_pfile", "othername_pfile", "endpoint_pfile"})
_PAYER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SourceSpec(BaseModel):
    """One source file / dataset / API. ``format`` names the reader; rules per format are in
    ``_FORMAT_RULES``. Only hospital MRFs need ``entity_id`` + ``npis`` (checked against the
    file's type_2_npi); only payer-specific sources need ``payer_id``."""

    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    kind: AnyKind
    format: SourceFormat
    entity_id: str | None = Field(
        default=None,
        description="hospitals.yaml id (hospital_mrf) or sites.yaml id (clinic_posted)",
    )
    payer_id: str | None = Field(
        default=None, description="payer_aliases.yaml id (insurer_tic, provider_directory)"
    )
    container: Literal["zip", "gzip", "plain"] = "plain"
    media: Media | None = Field(default=None, description="None -> the format's default")
    access: Access = "download"
    encoding: str = "utf-8"
    npis: list[str] = []
    url: str | None
    discovery: str | None = None
    legacy_filename: str | None = None
    max_bytes: int | None = None
    members: dict[str, str] = Field(
        default_factory=dict, description="zip member role -> filename glob (nppes_monthly)"
    )
    filters: dict[str, str] = Field(
        default_factory=dict, description="API query filters, e.g. {state: MA} (paged_api)"
    )
    release: str | None = Field(default=None, description="e.g. RVU26A, 2026-11, CY2026 Q4")

    @field_validator("npis")
    @classmethod
    def _npi10(cls, v: list[str]) -> list[str]:
        for n in v:
            if not (len(n) == 10 and n.isdigit()):
                raise ValueError(f"bad NPI {n!r}")
        return v

    @model_validator(mode="after")
    def _format_rules(self) -> SourceSpec:
        kinds, media, containers, access = _FORMAT_RULES[self.format]
        sid, k = self.source_id, self.kind.value
        if k not in kinds:
            raise ValueError(f"{sid}: format {self.format} needs kind in {sorted(kinds)}, got {k}")
        if self.media is None:
            self.media = media[0]  # type: ignore[assignment]
        elif self.media not in media:
            raise ValueError(f"{sid}: format {self.format} is {media}, not {self.media}")
        if self.container not in containers:
            raise ValueError(
                f"{sid}: format {self.format} container must be in {sorted(containers)}"
            )
        if self.access not in access:
            raise ValueError(f"{sid}: format {self.format} access must be in {sorted(access)}")
        if k == "hospital_mrf":
            if not self.entity_id or not self.npis:
                raise ValueError(f"{sid}: hospital_mrf needs entity_id and npis")
        elif self.npis:
            raise ValueError(f"{sid}: npis are only checked for hospital_mrf files")
        if k == "clinic_posted" and not self.entity_id:
            raise ValueError(f"{sid}: clinic_posted needs entity_id (the sites.yaml id)")
        if k in ("insurer_tic", "provider_directory"):
            if not self.payer_id or not _PAYER_RE.match(self.payer_id):
                raise ValueError(f"{sid}: {k} needs payer_id (payer_aliases.yaml id)")
        elif self.payer_id is not None:
            raise ValueError(f"{sid}: payer_id only applies to insurer_tic / provider_directory")
        if self.format == "nppes_monthly" and set(self.members) != NPPES_MEMBERS:
            raise ValueError(f"{sid}: nppes_monthly needs members {sorted(NPPES_MEMBERS)}")
        if self.format != "nppes_monthly" and self.members and self.container != "zip":
            raise ValueError(f"{sid}: members only apply to zip containers")
        if self.filters and self.access != "paged_api":
            raise ValueError(f"{sid}: filters only apply to paged_api sources")
        if self.url is not None and not self.url.startswith("https://"):
            raise ValueError(f"{sid}: url must be https")
        return self

    @property
    def hospital_entity(self) -> str:
        """entity_id of a hospital MRF (required for that kind, so never None here)."""
        if not self.entity_id:
            raise ValueError(f"{self.source_id}: no entity_id")
        return self.entity_id

    @property
    def is_rate_row_source(self) -> bool:
        """Read by the hospital-MRF rate_row pipeline (stage / normalize / build / report)."""
        return self.format in MRF_FORMATS


class SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    fetch: FetchSettings
    sources: list[SourceSpec]

    @field_validator("sources")
    @classmethod
    def _unique(cls, v: list[SourceSpec]) -> list[SourceSpec]:
        ids = [s.source_id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source_id in sources.yaml")
        return v

    def get(self, source_id: str) -> SourceSpec:
        for s in self.sources:
            if s.source_id == source_id:
                return s
        raise KeyError(f"unknown source_id {source_id!r} (see data/etl/sources.yaml)")

    @property
    def rate_row_sources(self) -> list[SourceSpec]:
        """Hospital MRFs only. Other streams' sources live in the same registry (sources.d) but
        are read by their own pipelines, so the rate_row build never waits on them."""
        return [s for s in self.sources if s.is_rate_row_source]

    def select(self, which: str | None) -> list[SourceSpec]:
        if which is None or which == "all":
            return list(self.sources)
        return [self.get(s.strip()) for s in which.split(",")]


def _yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(((config_dir or CONFIG_DIR) / name).read_text())
    return doc


class SourcesFragment(BaseModel):
    """One ``sources.d/*.yaml`` file. Each wave-2 stream owns its own file, so no two streams
    edit the same YAML. A fragment may add sources and fetch domains; it may not change the
    other fetch settings (those stay in ``sources.yaml``)."""

    model_config = ConfigDict(extra="forbid")
    version: int = 1
    allowed_domains: list[str] = []
    sources: list[SourceSpec] = []


SOURCES_D = "sources.d"


def _merge_sources(config_dir: Path) -> dict[str, Any]:
    """``sources.yaml`` + ``sources.d/*.yaml`` (sorted by name). Duplicate ids fail loudly."""
    doc = _yaml("sources.yaml", config_dir)
    origin: dict[str, str] = {}
    for s in doc.get("sources") or []:
        sid = s.get("source_id")
        if sid in origin:
            raise ValueError(f"duplicate source_id {sid!r} in sources.yaml")
        origin[sid] = "sources.yaml"
    domains: list[str] = list((doc.get("fetch") or {}).get("allowed_domains") or [])
    frag_dir = config_dir / SOURCES_D
    for path in sorted(frag_dir.glob("*.yaml")) if frag_dir.is_dir() else []:
        frag = SourcesFragment(**(yaml.safe_load(path.read_text()) or {}))
        rel = f"{SOURCES_D}/{path.name}"
        for spec in frag.sources:
            if spec.source_id in origin:
                raise ValueError(
                    f"duplicate source_id {spec.source_id!r}: in {origin[spec.source_id]} and {rel}"
                )
            origin[spec.source_id] = rel
            doc.setdefault("sources", []).append(spec.model_dump())
        for d in frag.allowed_domains:
            if d not in domains:
                domains.append(d)
    if "fetch" in doc:
        doc["fetch"]["allowed_domains"] = domains
    return doc


@functools.lru_cache(maxsize=4)
def load_sources(config_dir: Path | None = None) -> SourcesFile:
    """``data/etl/sources.yaml`` plus every ``data/etl/sources.d/*.yaml`` fragment."""
    return SourcesFile(**_merge_sources(config_dir or CONFIG_DIR))


class CodeList(BaseModel):
    version: int
    domains: dict[str, dict[str, str]]
    code_types: list[str]
    rev_code_components: dict[str, list[str]] = {}

    def component_for_rc(self, rc: str) -> str:
        if not rc.isdigit():
            return "facility"
        n = int(rc)
        for comp, ranges in self.rev_code_components.items():
            for r in ranges:
                lo, _, hi = r.partition("-")
                if int(lo) <= n <= int(hi or lo):
                    return comp
        return "facility"

    @property
    def codes(self) -> set[str]:
        return {c for d in self.domains.values() for c in d}

    def domains_for(self, code: str) -> list[str]:
        return [name for name, codes in self.domains.items() if code in codes]

    def description(self, code: str) -> str:
        for codes in self.domains.values():
            if code in codes:
                return codes[code]
        return ""


@functools.lru_cache(maxsize=4)
def load_codes(config_dir: Path | None = None) -> CodeList:
    return CodeList(**_yaml("codes.yaml", config_dir))


def load_yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    return _yaml(name, config_dir)
