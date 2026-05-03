"""Tests for plan_rules wiring in estimate_service.

The key invariant: ACA preventive scenarios must return $0 OOP
regardless of the user's deductible, coinsurance, or copay inputs.
"""



from app.services.estimate_service import build_estimate_response


class TestEstimateServicePlanRulesWiring:
    """Verify that plan_rules short-circuits OOP for preventive scenarios."""

    def test_preventive_screening_returns_zero_oop(self, seeded_db) -> None:
        """ACA preventive colonoscopy = $0 OOP regardless of deductible."""
        response = build_estimate_response(
            seeded_db,
            {
                "zip": "02101",
                "care_focus": "Gastroenterology",
                "insurance_carrier": "BCBS",
                "deductible_cents": 50000,
                "coinsurance_pct": 20,
                "copay_cents": 4000,
            },
            None,
            None,
            "colonoscopy_screening",
        )
        for est in response.estimates:
            assert est.oop_range.min == 0, (
                f"Preventive OOP min should be $0, got {est.oop_range.min} "
                f"for provider {est.provider_id}"
            )
            assert est.oop_range.max == 0, (
                f"Preventive OOP max should be $0, got {est.oop_range.max} "
                f"for provider {est.provider_id}"
            )

    def test_diagnostic_colonoscopy_nonzero_oop(self, seeded_db) -> None:
        """Diagnostic colonoscopy should have non-zero OOP when prices exist."""
        response = build_estimate_response(
            seeded_db,
            {
                "zip": "02101",
                "care_focus": "Gastroenterology",
                "insurance_carrier": "BCBS",
                "deductible_cents": 50000,
                "coinsurance_pct": 20,
            },
            None,
            None,
            "colonoscopy_diagnostic",
        )
        estimates_with_prices = [
            e for e in response.estimates if e.allowed_amount_range.max > 0
        ]
        if estimates_with_prices:
            has_nonzero = any(e.oop_range.max > 0 for e in estimates_with_prices)
            assert has_nonzero, "Diagnostic with prices should have non-zero OOP"

    def test_preventive_overrides_high_deductible(self, seeded_db) -> None:
        """Even with $10K deductible, preventive screening = $0."""
        response = build_estimate_response(
            seeded_db,
            {
                "zip": "02101",
                "care_focus": "Gastroenterology",
                "insurance_carrier": "BCBS",
                "deductible_cents": 1000000,  # $10,000
                "coinsurance_pct": 50,
                "copay_cents": 10000,
                "oop_max_cents": 2000000,
            },
            None,
            None,
            "colonoscopy_screening",
        )
        for est in response.estimates:
            assert est.oop_range.min == 0
            assert est.oop_range.max == 0
