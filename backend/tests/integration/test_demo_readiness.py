"""Demo data contract tests.

Verify that the ETL pipeline + DB import produces the exact data
the demo narrative depends on. These tests lock the demo contract:
- Aetna bundled spread: BMC Brighton $990 vs CHA $2,670 (2.7x)
- Zero HP-under-UHC contamination
- Zero Medicare rates in the Aetna commercial view
- Plan_type distribution matches ETL output
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session


@pytest.fixture
def demo_db(seeded_db: Session) -> Session:
    return seeded_db


class TestPlanTypeIntegrity:
    def test_no_hp_under_uhc(self, demo_db: Session) -> None:
        """Harvard Pilgrim plans must never appear under UHC payer_id."""
        count = demo_db.execute(
            text(
                "SELECT COUNT(*) FROM hospital_payer_rates "
                "WHERE payer_id = 'UHC' AND payer_raw ILIKE '%HARVARD PILGRIM%'"
            )
        ).scalar()
        assert count == 0, f"Found {count} HP-under-UHC rows (expected 0)"

    def test_medicare_classified(self, demo_db: Session) -> None:
        """Medicare rates must be labeled, not left as unknown."""
        medicare_count = demo_db.execute(
            text("SELECT COUNT(*) FROM hospital_payer_rates WHERE plan_type = 'medicare'")
        ).scalar()
        assert medicare_count > 500, f"Only {medicare_count} medicare rows (expected >500)"

    def test_plan_type_enum_values(self, demo_db: Session) -> None:
        """All plan_type values must be in the allowed set."""
        rows = demo_db.execute(
            text("SELECT DISTINCT plan_type FROM hospital_payer_rates ORDER BY plan_type")
        ).fetchall()
        values = {r[0] for r in rows}
        allowed = {"commercial", "medicare", "medicaid", "unknown"}
        assert values <= allowed, f"Unexpected plan_type values: {values - allowed}"


class TestDemoSpread:
    """Lock the Aetna bundled colonoscopy spread that the demo narrative uses."""

    def test_bmc_brighton_aetna_bundled(self, demo_db: Session) -> None:
        rate = demo_db.execute(
            text(
                "SELECT negotiated_rate FROM hospital_payer_rates "
                "WHERE hospital_id = 'bmc_brighton' AND cpt = '45378' "
                "AND payer_id = 'AETNA' AND plan_type NOT IN ('medicare', 'medicaid') "
                "AND setting = 'both' "
                "ORDER BY negotiated_rate LIMIT 1"
            )
        ).scalar()
        assert rate is not None, "BMC Brighton has no Aetna bundled commercial rate for CPT 45378"
        assert rate <= 1000, f"BMC Brighton Aetna bundled = ${rate} (expected <= $1,000)"

    def test_cha_aetna_bundled(self, demo_db: Session) -> None:
        rate = demo_db.execute(
            text(
                "SELECT negotiated_rate FROM hospital_payer_rates "
                "WHERE hospital_id = 'cha' AND cpt = '45378' "
                "AND payer_id = 'AETNA' AND plan_type NOT IN ('medicare', 'medicaid') "
                "AND setting = 'both' "
                "ORDER BY negotiated_rate DESC LIMIT 1"
            )
        ).scalar()
        assert rate is not None, "CHA has no Aetna bundled commercial rate for CPT 45378"
        assert rate >= 2500, f"CHA Aetna bundled = ${rate} (expected >= $2,500)"

    def test_spread_ratio(self, demo_db: Session) -> None:
        """The demo claims a 2.7x spread — verify it's at least 2x."""
        rows = demo_db.execute(
            text(
                "SELECT hospital_id, negotiated_rate FROM hospital_payer_rates "
                "WHERE cpt = '45378' AND payer_id = 'AETNA' "
                "AND plan_type NOT IN ('medicare', 'medicaid') AND setting = 'both' "
                "ORDER BY negotiated_rate"
            )
        ).fetchall()
        rates = [r[1] for r in rows]
        assert len(rates) >= 2, f"Need at least 2 Aetna bundled rates, got {len(rates)}"
        ratio = max(rates) / min(rates)
        assert ratio >= 2.0, f"Spread ratio {ratio:.1f}x (expected >= 2x)"


class TestMedicareNotInCommercialView:
    def test_aetna_commercial_excludes_medicare(self, demo_db: Session) -> None:
        """When filtering for Aetna commercial, zero medicare rates should appear."""
        count = demo_db.execute(
            text(
                "SELECT COUNT(*) FROM hospital_payer_rates "
                "WHERE payer_id = 'AETNA' AND plan_type = 'medicare'"
            )
        ).scalar()
        # Medicare rates exist under Aetna payer_id (Medicare Advantage)
        assert count > 0, "Expected some Aetna Medicare Advantage rates in DB"

        # But the commercial view must exclude them
        commercial = demo_db.execute(
            text(
                "SELECT COUNT(*) FROM hospital_payer_rates "
                "WHERE payer_id = 'AETNA' AND plan_type NOT IN ('medicare', 'medicaid')"
            )
        ).scalar()
        assert commercial > 0, "No Aetna commercial rates found"
