"""Integration tests for pre-computed payment table JSON.

These verify the generated plan_payment_table.json without needing MongoDB.
Run generate_payment_table.py first.
"""

import json
from pathlib import Path

import pytest

DATA_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "az-data"
    / "plan_payment_table.json"
)


@pytest.fixture
def payment_table() -> list[dict]:
    if not DATA_PATH.exists():
        pytest.skip(f"Payment table not found at {DATA_PATH} — run generate_payment_table.py first")
    return json.loads(DATA_PATH.read_text())


class TestPaymentTable:
    def test_row_count(self, payment_table: list[dict]) -> None:
        """Expect ~1812 rows (6 plans x 12 hospitals x ~29 scenarios)."""
        assert len(payment_table) >= 1500, f"Only {len(payment_table)} rows — expected ~1812"

    def test_preventive_rows_are_zero(self, payment_table: list[dict]) -> None:
        """Every colonoscopy_screening row should have $0 OOP."""
        screening = [r for r in payment_table if r.get("scenario_id") == "colonoscopy_screening"]
        assert len(screening) > 0, "No screening rows found"
        for row in screening:
            assert row.get("scenario_a_cents", -1) == 0, (
                f"{row['plan_id']}@{row.get('hospital_name', '?')}: screening OOP should be $0, "
                f"got {row.get('scenario_a_cents')}"
            )

    def test_copay_rows_have_flat_values(self, payment_table: list[dict]) -> None:
        """Copay-only rows should have scenario_a == scenario_b (no deductible variance)."""
        copay_rows = [r for r in payment_table if r.get("rule_type") == "copay_only"]
        for row in copay_rows:
            assert row["scenario_a_cents"] == row["scenario_b_cents"], (
                f"{row['plan_id']}@{row.get('hospital_name', '?')}: copay should be flat, "
                f"got A={row['scenario_a_cents']} B={row['scenario_b_cents']}"
            )
