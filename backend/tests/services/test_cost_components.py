"""Tests for cost components decomposition service."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.cost_components import (
    get_cost_components,
)


def _mock_rate(*, negotiated_rate=1850.0, source_origin="mrf", effective_date="2026-01-01", rate_year=2026):
    rate = MagicMock()
    rate.negotiated_rate = negotiated_rate
    rate.source_origin = source_origin
    rate.effective_date = effective_date
    rate.rate_year = rate_year
    return rate


def _mock_rvu(*, work=3.18, fac_pe=1.34, mp=0.41, fac_total=4.93, pfs_year=2026):
    rvu = MagicMock()
    rvu.work_rvu = work
    rvu.facility_pe_rvu = fac_pe
    rvu.malpractice_rvu = mp
    rvu.facility_total_rvu = fac_total
    rvu.pfs_year = pfs_year
    return rvu


class TestGetCostComponents:
    @patch("app.services.cost_components._get_rvu")
    @patch("app.services.cost_components._get_latest_rate")
    def test_full_decomposition(self, mock_rate_fn, mock_rvu_fn):
        mock_rate_fn.return_value = _mock_rate()
        mock_rvu_fn.return_value = _mock_rvu()
        db = MagicMock()

        result = get_cost_components(db, "mgh", "45378", "BCBS_MA")

        assert result.data_tier == "full"
        assert result.negotiated_rate == 1850.0
        assert len(result.components) == 3
        names = [c.name for c in result.components]
        assert names == ["physician_work", "practice_expense", "malpractice"]
        total_amount = sum(c.amount for c in result.components)
        assert total_amount == pytest.approx(1850.0, abs=1.0)

    @patch("app.services.cost_components._get_rvu")
    @patch("app.services.cost_components._get_latest_rate")
    def test_no_rate_returns_no_rate_tier(self, mock_rate_fn, mock_rvu_fn):
        mock_rate_fn.return_value = None
        db = MagicMock()

        result = get_cost_components(db, "mgh", "45378")

        assert result.data_tier == "no_rate"
        assert result.negotiated_rate is None
        assert result.components == []

    @patch("app.services.cost_components._get_rvu")
    @patch("app.services.cost_components._get_latest_rate")
    def test_no_rvu_returns_gross_only_tier(self, mock_rate_fn, mock_rvu_fn):
        mock_rate_fn.return_value = _mock_rate()
        mock_rvu_fn.return_value = None
        db = MagicMock()

        result = get_cost_components(db, "mgh", "45378")

        assert result.data_tier == "gross_only"
        assert result.negotiated_rate == 1850.0
        assert result.components == []

    @patch("app.services.cost_components._get_rvu")
    @patch("app.services.cost_components._get_latest_rate")
    def test_zero_total_rvu_returns_gross_only(self, mock_rate_fn, mock_rvu_fn):
        mock_rate_fn.return_value = _mock_rate()
        mock_rvu_fn.return_value = _mock_rvu(fac_total=0)
        db = MagicMock()

        result = get_cost_components(db, "mgh", "45378")

        assert result.data_tier == "gross_only"

    @patch("app.services.cost_components._get_rvu")
    @patch("app.services.cost_components._get_latest_rate")
    def test_provenance_populated(self, mock_rate_fn, mock_rvu_fn):
        mock_rate_fn.return_value = _mock_rate()
        mock_rvu_fn.return_value = _mock_rvu()
        db = MagicMock()

        result = get_cost_components(db, "mgh", "45378", "BCBS_MA")

        assert result.rate_provenance is not None
        assert result.rate_provenance.source == "mrf"
        assert result.rate_provenance.source_display == "Hospital Price Transparency File"
        assert result.rate_provenance.rate_year == 2026
        for c in result.components:
            assert c.provenance.source == "cms_pfs"
            assert c.provenance.data_vintage == "CY2026"

    @patch("app.services.cost_components._get_rvu")
    @patch("app.services.cost_components._get_latest_rate")
    def test_component_percentages_sum_to_100(self, mock_rate_fn, mock_rvu_fn):
        mock_rate_fn.return_value = _mock_rate()
        mock_rvu_fn.return_value = _mock_rvu()
        db = MagicMock()

        result = get_cost_components(db, "mgh", "45378", "BCBS_MA")

        total_pct = sum(c.pct_of_total for c in result.components)
        assert total_pct == pytest.approx(100.0, abs=0.5)
