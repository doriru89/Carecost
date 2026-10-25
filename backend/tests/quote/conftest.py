"""Shared fixtures for the quote engine tests: the committed extract through the runtime pack."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.quote.engine import Engine
from app.quote.registry import Registry
from app.quote.store import store_from_extract

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "contracts" / "fixtures"
AS_OF = date(2026, 10, 25)  # the day the golden fixtures were generated (A3 fetched 10-25 UTC)


def fixture_doc(name: str) -> dict:
    doc = json.loads((FIX / f"{name}.json").read_text())
    doc.pop("_fixture")
    doc.pop("_schema")
    return doc


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry.load()


@pytest.fixture(scope="session")
def store():
    return store_from_extract()


@pytest.fixture(scope="session")
def engine(store, registry) -> Engine:
    return Engine(store, registry)
