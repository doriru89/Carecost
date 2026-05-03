"""TDD tests for pipeline — written BEFORE implementation."""

import json


def _setup_synthetic_data(tmp_path):
    """Create minimal synthetic MRF + benchmark data for end-to-end test."""
    mrf_dir = tmp_path / "mrfs"
    mrf_dir.mkdir()
    tic_dir = tmp_path / "tic"
    tic_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    (data_dir / "plan_payment_table.json").write_text(json.dumps([]))

    return mrf_dir, tic_dir, data_dir, output_dir


class TestRunEtl:
    def test_empty_dirs(self, tmp_path):
        from app.etl.pipeline import run_etl

        mrf_dir, tic_dir, data_dir, output_dir = _setup_synthetic_data(tmp_path)
        result = run_etl(
            mrf_dir=mrf_dir,
            tic_dir=tic_dir,
            data_dir=data_dir,
            output_dir=output_dir,
        )
        assert result.mrf_records_extracted == 0
        assert result.tic_records_extracted == 0
        assert result.merged_rows == 0

    def test_result_populated(self, tmp_path):
        from app.etl.pipeline import run_etl

        mrf_dir, tic_dir, data_dir, output_dir = _setup_synthetic_data(tmp_path)
        result = run_etl(
            mrf_dir=mrf_dir,
            tic_dir=tic_dir,
            data_dir=data_dir,
            output_dir=output_dir,
        )
        assert result.validation_report is not None
        assert result.run_timestamp != ""

    def test_csvs_written(self, tmp_path):
        from app.etl.pipeline import run_etl

        mrf_dir, tic_dir, data_dir, output_dir = _setup_synthetic_data(tmp_path)
        run_etl(
            mrf_dir=mrf_dir,
            tic_dir=tic_dir,
            data_dir=data_dir,
            output_dir=output_dir,
        )
        assert (output_dir / "hospital_procedures.csv").exists()
        assert (output_dir / "hospital_payer_rates.csv").exists()
        assert (output_dir / "hospital_benchmarks.csv").exists()

    def test_sha256_sidecar(self, tmp_path):
        from app.etl.pipeline import run_etl

        mrf_dir, tic_dir, data_dir, output_dir = _setup_synthetic_data(tmp_path)
        run_etl(
            mrf_dir=mrf_dir,
            tic_dir=tic_dir,
            data_dir=data_dir,
            output_dir=output_dir,
        )
        assert (output_dir / "hospital_procedures.csv.sha256").exists()

    def test_validation_report_in_result(self, tmp_path):
        from app.etl.pipeline import run_etl

        mrf_dir, tic_dir, data_dir, output_dir = _setup_synthetic_data(tmp_path)
        result = run_etl(
            mrf_dir=mrf_dir,
            tic_dir=tic_dir,
            data_dir=data_dir,
            output_dir=output_dir,
        )
        assert result.validation_report is not None
        assert isinstance(result.validation_report.errors, list)

    def test_no_specialty_parameter(self, tmp_path):
        """run_etl() no longer accepts a 'specialty' parameter — it processes all."""
        import inspect
        from app.etl.pipeline import run_etl

        sig = inspect.signature(run_etl)
        assert "specialty" not in sig.parameters
