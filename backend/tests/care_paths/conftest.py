"""Shared fixtures for care-path content tests (no database needed)."""

from __future__ import annotations

import copy

import pytest

from app.care_paths.loader import ContentBundle, load_bundle


@pytest.fixture(scope="session")
def bundle() -> ContentBundle:
    return load_bundle()


@pytest.fixture
def mutable_bundle(bundle: ContentBundle) -> ContentBundle:
    """Deep copy for negative tests that break one rule on purpose."""
    return copy.deepcopy(bundle)
