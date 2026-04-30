"""Verify canonical seed data paths exist and contain expected files."""
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "seed"


def test_seed_directory_exists():
    assert SEED_DIR.is_dir(), "data/seed/ must exist"


def test_payment_table_in_seed():
    assert (SEED_DIR / "plan_payment_table.json").exists()


def test_hospital_rates_in_seed():
    assert (SEED_DIR / "hospital_rates_clean.csv").exists()


def test_providers_in_seed():
    assert (SEED_DIR / "providers.csv").exists()
