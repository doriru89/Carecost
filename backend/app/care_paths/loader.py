"""Load all clinical content from data/ and content/ into typed objects (fail loudly on bad data)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.care_paths.models import (
    CarePath,
    ConnectCheck,
    CptRegistry,
    Glossary,
    QuestionSet,
    RedFlagSet,
    Source,
    SourceRegistry,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = REPO_ROOT / "data"
CARE_PATHS_DIR = DATA_ROOT / "care_paths"
GLOSSARY_FILE = REPO_ROOT / "content" / "glossary" / "glossary.yaml"


@dataclass
class ContentBundle:
    sources: dict[str, Source]
    paths: dict[str, CarePath]
    questions: QuestionSet
    redflags: RedFlagSet
    glossary: Glossary
    cpt_registry: CptRegistry
    connect: ConnectCheck


def _yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_paths(directory: Path = CARE_PATHS_DIR / "paths") -> dict[str, CarePath]:
    out: dict[str, CarePath] = {}
    for f in sorted(directory.glob("*.yaml")):
        path = CarePath.model_validate(_yaml(f))
        if f.stem != path.id:
            raise ValueError(f"{f.name}: file name must equal path id {path.id!r}")
        out[path.id] = path
    return out


def load_bundle(repo_root: Path | None = None) -> ContentBundle:
    root = repo_root or REPO_ROOT
    data = root / "data"
    cp = data / "care_paths"
    return ContentBundle(
        sources=SourceRegistry.model_validate(_yaml(cp / "sources.yaml")).sources,
        paths=load_paths(cp / "paths"),
        questions=QuestionSet.model_validate(_yaml(data / "questions" / "questions.yaml")),
        redflags=RedFlagSet.model_validate(
            json.loads((data / "redflags" / "redflags.json").read_text(encoding="utf-8"))
        ),
        glossary=Glossary.model_validate(_yaml(root / "content" / "glossary" / "glossary.yaml")),
        cpt_registry=CptRegistry.model_validate(
            json.loads((cp / "cpt_registry_2026.json").read_text(encoding="utf-8"))
        ),
        connect=ConnectCheck.model_validate(
            json.loads((cp / "medlineplus_connect_check.json").read_text(encoding="utf-8"))
        ),
    )
