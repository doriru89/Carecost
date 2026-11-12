"""File locations (one place)."""

from __future__ import annotations

from pathlib import Path

from app.etl.config import Paths as _DataPaths

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "sites" / "site_facts"
# Fetched page text is a raw download, so it lives under the data root
# ($CARECOST_DATA_DIR, else <repo>/data) next to raw/store, not in the code tree:
# a worktree removed with its gitignored files cannot take the only copy with it.
CACHE_DIR = _DataPaths.resolve().data / "raw" / "site_pages"  # gitignored (data/raw/)
MANIFEST = DATA / "manifest.yaml"
PAGES = DATA / "pages.yaml"
CAPABILITIES = DATA / "capabilities.yaml"
FACTS = DATA / "facts.yaml"
RUNS_DIR = DATA / "runs"
REVIEWS = DATA / "reviews.yaml"
REVIEW_DIR = DATA / "review"
SITES_YAML = REPO / "data" / "sites" / "sites.yaml"
CENSUS_CSV = REPO / "data" / "sites" / "census" / "clinic-census-2026-10-24.csv"
