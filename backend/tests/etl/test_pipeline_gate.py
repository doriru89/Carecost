"""Tests for ETL validation gate (P0) and record-count regression (P1)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.etl.pipeline import (
    EtlValidationError,
    _check_regression,
    _load_manifest,
    _write_manifest,
    run_etl,
)
from app.etl.types import ValidationReport


def _setup_dirs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    mrf_dir = tmp_path / "mrfs"
    mrf_dir.mkdir()
    tic_dir = tmp_path / "tic"
    tic_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    (data_dir / "plan_payment_table.json").write_text(json.dumps([]))
    return mrf_dir, tic_dir, data_dir, output_dir


class TestValidationGate:
    def test_empty_input_raises_validation_error(self, tmp_path: Path) -> None:
        """Empty input triggers 'No procedure records produced' error — gate catches it."""
        mrf_dir, tic_dir, data_dir, output_dir = _setup_dirs(tmp_path)
        with pytest.raises(EtlValidationError, match="No procedure records"):
            run_etl(mrf_dir=mrf_dir, tic_dir=tic_dir, data_dir=data_dir, output_dir=output_dir)

    def test_empty_input_writes_with_force(self, tmp_path: Path) -> None:
        mrf_dir, tic_dir, data_dir, output_dir = _setup_dirs(tmp_path)
        result = run_etl(mrf_dir=mrf_dir, tic_dir=tic_dir, data_dir=data_dir, output_dir=output_dir, force=True)
        assert (output_dir / "hospital_procedures.csv").exists()
        assert result.validation_report is not None

    def test_errors_raise_without_force(self, tmp_path: Path) -> None:
        mrf_dir, tic_dir, data_dir, output_dir = _setup_dirs(tmp_path)
        fake_report = ValidationReport(passed=False, errors=["Test error: bad data"])
        with patch("app.etl.pipeline.validate_etl_output", return_value=fake_report):
            with pytest.raises(EtlValidationError, match="1 error"):
                run_etl(mrf_dir=mrf_dir, tic_dir=tic_dir, data_dir=data_dir, output_dir=output_dir)
        assert not output_dir.exists() or not (output_dir / "hospital_procedures.csv").exists()

    def test_errors_write_csvs_with_force(self, tmp_path: Path) -> None:
        mrf_dir, tic_dir, data_dir, output_dir = _setup_dirs(tmp_path)
        fake_report = ValidationReport(passed=False, errors=["Test error: bad data"])
        with patch("app.etl.pipeline.validate_etl_output", return_value=fake_report):
            result = run_etl(
                mrf_dir=mrf_dir, tic_dir=tic_dir, data_dir=data_dir, output_dir=output_dir, force=True,
            )
        assert (output_dir / "hospital_procedures.csv").exists()
        assert result.validation_report.errors == ["Test error: bad data"]

    def test_error_exception_contains_errors(self, tmp_path: Path) -> None:
        mrf_dir, tic_dir, data_dir, output_dir = _setup_dirs(tmp_path)
        errors = ["Error 1", "Error 2", "Error 3"]
        fake_report = ValidationReport(passed=False, errors=errors)
        with patch("app.etl.pipeline.validate_etl_output", return_value=fake_report):
            with pytest.raises(EtlValidationError) as exc_info:
                run_etl(mrf_dir=mrf_dir, tic_dir=tic_dir, data_dir=data_dir, output_dir=output_dir)
        assert exc_info.value.errors == errors
        assert "3 error(s)" in str(exc_info.value)


    def test_duplicate_payer_rate_raises_without_force(self, tmp_path: Path) -> None:
        """Duplicate payer rates are now ERROR — pipeline must raise when force=False."""
        from app.etl.types import MergeResult, PayerRateRecord, ProcedureRecord

        mrf_dir, tic_dir, data_dir, output_dir = _setup_dirs(tmp_path)

        dupe_result = MergeResult(
            procedures=[ProcedureRecord(
                hospital_id="mgh", cpt="45378", cpt_desc="Colonoscopy",
                gross_charge=5000.0, discounted_cash=3000.0,
                de_identified_min=2000.0, de_identified_max=6000.0,
            )],
            payer_rates=[
                PayerRateRecord(
                    hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
                    negotiated_rate=3411.0, source_origin="mrf", plan_name="PPO",
                ),
                PayerRateRecord(
                    hospital_id="mgh", cpt="45378", payer_id="BCBS_MA",
                    negotiated_rate=3411.0, source_origin="mrf", plan_name="PPO",
                ),
            ],
            benchmarks=[],
        )
        with patch("app.etl.pipeline.merge_records", return_value=dupe_result):
            with patch("app.etl.pipeline.parse_all_hospital_rates", return_value=[]):
                with patch("app.etl.pipeline.normalize_records", return_value=[]):
                    with patch("app.etl.pipeline.qualify_batch", return_value=[]):
                        with pytest.raises(EtlValidationError, match="Duplicate payer rate"):
                            run_etl(
                                mrf_dir=mrf_dir, tic_dir=tic_dir,
                                data_dir=data_dir, output_dir=output_dir,
                            )


class TestRecordCountRegression:
    def test_no_regression_no_errors(self) -> None:
        previous = {"mgh": 30, "bmc": 20, "tufts": 15}
        current = {"mgh": 28, "bmc": 20, "tufts": 15}
        assert _check_regression(current, previous) == []

    def test_drop_over_threshold(self) -> None:
        previous = {"mgh": 50, "bmc": 20}
        current = {"mgh": 30, "bmc": 20}
        errors = _check_regression(current, previous)
        assert len(errors) == 1
        assert "mgh" in errors[0]
        assert "40%" in errors[0]

    def test_hospital_disappears(self) -> None:
        previous = {"mgh": 50, "bmc": 20}
        current = {"bmc": 20}
        errors = _check_regression(current, previous)
        assert len(errors) == 1
        assert "mgh" in errors[0]
        assert "100%" in errors[0]

    def test_zero_previous_skipped(self) -> None:
        previous = {"mgh": 0}
        current = {"mgh": 0}
        assert _check_regression(current, previous) == []

    def test_new_hospital_ignored(self) -> None:
        previous = {"mgh": 30}
        current = {"mgh": 30, "new_hospital": 15}
        assert _check_regression(current, previous) == []

    def test_manifest_roundtrip(self, tmp_path: Path) -> None:
        counts = {"mgh": 30, "bmc": 20}
        _write_manifest(tmp_path, counts)
        loaded = _load_manifest(tmp_path)
        assert loaded == counts

    def test_manifest_missing_returns_none(self, tmp_path: Path) -> None:
        assert _load_manifest(tmp_path) is None
