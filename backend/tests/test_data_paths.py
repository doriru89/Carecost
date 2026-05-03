"""Verify canonical seed data paths exist and contain expected files."""

import pytest
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "seed"
ETL_OUTPUT = Path(__file__).resolve().parent.parent.parent / "data" / "intermediate" / "etl_output"


def test_seed_directory_exists():
    assert SEED_DIR.is_dir(), "data/seed/ must exist"


def test_providers_in_seed():
    assert (SEED_DIR / "providers.csv").exists()


@pytest.mark.skipif(
    not ETL_OUTPUT.is_dir(),
    reason="ETL output not available (run ETL pipeline first)",
)
def test_etl_output_has_normalized_csvs():
    assert (ETL_OUTPUT / "hospital_procedures.csv").exists()
    assert (ETL_OUTPUT / "hospital_payer_rates.csv").exists()
