"""Tests for oop.py — the raw OOP math engine.

This function handles user financial inputs directly (deductible, coinsurance,
copay, OOP max). Every path must be tested with realistic plan data.
"""

from app.services.oop import compute_oop_range_cents


class TestComputeOopRangeCents:
    def test_basic_ded_coinsurance(self) -> None:
        """$1,279 allowed, $500 ded, $4K OOP max, 10% coinsurance, no copay."""
        oop_min, oop_max, assumptions = compute_oop_range_cents(
            127900, 127900, 50000, 400000, 10, 0, False
        )
        # (127900-50000)*0.10 = 7790 → copay(0)+7790 = 7790
        assert oop_min == 7790
        assert oop_max == 7790

    def test_zero_allowed_returns_zero_oop(self) -> None:
        """Rate=0 (ACA preventive via hospital data) → $0 OOP."""
        oop_min, oop_max, _ = compute_oop_range_cents(
            0, 0, 50000, 400000, 10, 0, False
        )
        assert oop_min == 0
        assert oop_max == 0

    def test_deductible_unknown_widens_band(self) -> None:
        oop_min, oop_max, assumptions = compute_oop_range_cents(
            127900, 127900, 50000, 400000, 10, 0, True
        )
        assert oop_min < oop_max
        assert any("unknown" in a.lower() for a in assumptions)

    def test_oop_max_caps_high_rate(self) -> None:
        """$50,000 rate with $4K OOP max → capped."""
        _, oop_max, _ = compute_oop_range_cents(
            5000000, 5000000, 50000, 400000, 10, 0, False
        )
        assert oop_max <= 400000

    def test_copay_included_in_calculation(self) -> None:
        """$40 copay + coinsurance should exceed coinsurance-only."""
        with_copay, _, _ = compute_oop_range_cents(
            127900, 127900, 50000, 400000, 10, 4000, False
        )
        without_copay, _, _ = compute_oop_range_cents(
            127900, 127900, 50000, 400000, 10, 0, False
        )
        assert with_copay > without_copay

    def test_zero_deductible_plan(self) -> None:
        """$0 deductible → full coinsurance on entire allowed amount."""
        oop_min, _, _ = compute_oop_range_cents(
            127900, 127900, 0, 400000, 10, 0, False
        )
        # 127900 * 0.10 = 12790
        assert oop_min == 12790

    def test_none_values_treated_as_zero(self) -> None:
        """No plan data (all None) → should still compute without error."""
        oop_min, oop_max, _ = compute_oop_range_cents(
            127900, 127900, None, None, None, None, False
        )
        # copay=0, coinsurance=0 → 0
        assert oop_min == 0
        assert oop_max == 0

    def test_min_max_range_with_different_allowed(self) -> None:
        """Different min/max allowed amounts produce a range."""
        oop_min, oop_max, _ = compute_oop_range_cents(
            100000, 200000, 50000, 400000, 20, 0, False
        )
        assert oop_min < oop_max
