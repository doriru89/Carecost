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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.etl.contracts import SourceKind

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


SourceFormat = Literal["cms_v3_csv_tall", "cms_v3_csv_wide", "cms_v3_json"]


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    kind: SourceKind
    entity_id: str
    format: SourceFormat
    container: Literal["zip", "plain"]
    encoding: str
    npis: list[str]
    url: str | None
    discovery: str | None = None
    legacy_filename: str | None = None
    max_bytes: int | None = None

    @field_validator("npis")
    @classmethod
    def _npi10(cls, v: list[str]) -> list[str]:
        for n in v:
            if not (len(n) == 10 and n.isdigit()):
                raise ValueError(f"bad NPI {n!r}")
        return v


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

    def select(self, which: str | None) -> list[SourceSpec]:
        if which is None or which == "all":
            return list(self.sources)
        return [self.get(s.strip()) for s in which.split(",")]


def _yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(((config_dir or CONFIG_DIR) / name).read_text())
    return doc


@functools.lru_cache(maxsize=4)
def load_sources(config_dir: Path | None = None) -> SourcesFile:
    return SourcesFile(**_yaml("sources.yaml", config_dir))


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
