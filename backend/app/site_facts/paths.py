"""File locations (one place)."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "sites" / "site_facts"
CACHE_DIR = DATA / "cache"  # gitignored
MANIFEST = DATA / "manifest.yaml"
PAGES = DATA / "pages.yaml"
CAPABILITIES = DATA / "capabilities.yaml"
FACTS = DATA / "facts.yaml"
RUNS_DIR = DATA / "runs"
REVIEWS = DATA / "reviews.yaml"
REVIEW_DIR = DATA / "review"
SITES_YAML = REPO / "data" / "sites" / "sites.yaml"
CENSUS_CSV = REPO / "data" / "sites" / "census" / "clinic-census-2026-10-24.csv"
