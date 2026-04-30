"""ETL pipeline orchestrator.

Deterministic 10-step sequence. No AI intelligence — that goes on top via /refresh-data.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.etl.csv_builder import build_csvs, build_legacy_wide_csv
from app.etl.data_qualifier import qualify_batch
from app.etl.data_validator import validate_etl_output
from app.etl.hospital_rate_parser import parse_all_hospital_rates
from app.etl.insurer_rate_parser import parse_insurer_rates
from app.etl.merger import load_benchmarks, merge_records
from app.etl.rate_normalizer import normalize_records
from app.etl.types import EtlResult

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    digest = h.hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n")
    return digest


def _discover_tic_files(tic_dir: Path) -> list[tuple[Path, str]]:
    result = []
    for f in sorted(tic_dir.iterdir()):
        if not f.is_file():
            continue
        stem = f.stem.split("_tic")[0].split("_TiC")[0]
        if stem:
            result.append((f, stem))
    return result


def run_etl(
    mrf_dir: Path,
    tic_dir: Path,
    data_dir: Path,
    output_dir: Path,
    specialty: str = "gi",
    expected_hospitals: list[str] | None = None,
) -> EtlResult:
    # 1. Parse hospital MRFs
    mrf_records = parse_all_hospital_rates(mrf_dir, specialty)
    logger.info("Extracted %d MRF records", len(mrf_records))

    # 2. Parse insurer TiC files
    tic_records = []
    for tic_path, insurer_key in _discover_tic_files(tic_dir):
        batch = parse_insurer_rates(tic_path, insurer_key, specialty)
        tic_records.extend(batch)
        logger.info("Extracted %d TiC records from %s", len(batch), tic_path.name)

    # 3. Normalize
    all_raw = list(mrf_records) + list(tic_records)
    normalized = normalize_records(all_raw)
    logger.info("Normalized %d records", len(normalized))

    # 4. Qualify
    qualified = qualify_batch(normalized)

    # 5. Load benchmarks
    benchmarks = load_benchmarks(data_dir, specialty)

    # 6. Merge
    merge_result = merge_records(qualified, benchmarks)
    logger.info(
        "Merged: %d procedures, %d payer rates, %d benchmarks",
        len(merge_result.procedures), len(merge_result.payer_rates), len(merge_result.benchmarks),
    )

    # 7. Validate
    validation = validate_etl_output(merge_result, expected_hospitals)
    if validation.errors:
        for err in validation.errors:
            logger.error("Validation error: %s", err)
    for warn in validation.warnings:
        logger.warning("Validation warning: %s", warn)

    # 8. Build normalized CSVs
    output_dir.mkdir(parents=True, exist_ok=True)
    build_csvs(merge_result, output_dir)

    # 9. Build legacy wide CSV
    legacy_path = output_dir / "hospital_rates.csv"
    legacy_count = build_legacy_wide_csv(merge_result, legacy_path)

    # 10. SHA256 provenance
    for csv_file in output_dir.glob("*.csv"):
        _sha256_file(csv_file)

    return EtlResult(
        specialty=specialty,
        mrf_records_extracted=len(mrf_records),
        tic_records_extracted=len(tic_records),
        records_after_normalization=len(normalized),
        merged_rows=len(merge_result.procedures),
        csv_rows_written=legacy_count,
        hospitals_found=sorted({p.hospital_id for p in merge_result.procedures}),
        warnings=validation.warnings,
        validation_report=validation,
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )
