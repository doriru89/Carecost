"""ETL pipeline orchestrator.

Deterministic 10-step sequence. No AI intelligence — that goes on top via /refresh-data.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.etl.csv_builder import build_csvs
from app.etl.data_qualifier import qualify_batch
from app.etl.data_validator import validate_etl_output
from app.etl.hospital_rate_parser import parse_all_hospital_rates
from app.etl.insurer_rate_parser import parse_insurer_rates
from app.etl.merger import load_benchmarks, merge_records
from app.etl.rate_normalizer import normalize_records
from app.etl.types import EtlResult
from app.registries import load_etl_config


class EtlValidationError(Exception):
    """Raised when ETL validation finds errors and force=False."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"ETL validation failed with {len(errors)} error(s): {errors[0]}")

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    digest = h.hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n")
    return digest


_REGRESSION_THRESHOLD = 0.20


def _load_manifest(output_dir: Path) -> dict[str, int] | None:
    p = output_dir / "manifest.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("hospital_record_counts", {})


def _write_manifest(output_dir: Path, counts: dict[str, int]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps({"hospital_record_counts": counts}, indent=2, sort_keys=True) + "\n"
    )


def _check_regression(
    current: dict[str, int], previous: dict[str, int],
) -> list[str]:
    errors: list[str] = []
    for hospital_id, prev_count in previous.items():
        curr_count = current.get(hospital_id, 0)
        if prev_count == 0:
            continue
        drop = (prev_count - curr_count) / prev_count
        if drop >= _REGRESSION_THRESHOLD:
            errors.append(
                f"Record count regression for {hospital_id}: "
                f"{prev_count} → {curr_count} ({drop:.0%} drop, threshold {_REGRESSION_THRESHOLD:.0%})"
            )
    return errors


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
    expected_hospitals: list[str] | None = None,
    force: bool = False,
) -> EtlResult:
    # 0. Compute union of all CPT extraction sets (multi-specialty)
    config = load_etl_config()
    all_cpts: set[str] = set()
    for cpts in config.cpt_extraction_sets.values():
        all_cpts.update(cpts)
    logger.info(
        "Target CPTs: %d codes across %d specialties",
        len(all_cpts),
        len(config.cpt_extraction_sets),
    )

    # 1. Parse hospital MRFs
    mrf_records = parse_all_hospital_rates(mrf_dir, all_cpts)
    logger.info("Extracted %d MRF records", len(mrf_records))

    # 2. Parse insurer TiC files
    tic_records = []
    for tic_path, insurer_key in _discover_tic_files(tic_dir):
        batch = parse_insurer_rates(tic_path, insurer_key, all_cpts)
        tic_records.extend(batch)
        logger.info("Extracted %d TiC records from %s", len(batch), tic_path.name)

    # 3. Normalize
    all_raw = list(mrf_records) + list(tic_records)
    normalized = normalize_records(all_raw)
    logger.info("Normalized %d records", len(normalized))

    # 3.5. Check per-hospital CPT coverage against config thresholds
    per_hospital_cpts: dict[str, set[str]] = defaultdict(set)
    for rec in normalized:
        per_hospital_cpts[rec.hospital_id].add(rec.cpt)
    for hospital_id, source in config.hospital_mrf_sources.items():
        min_cpts = source.get("min_expected_cpts", 1)
        actual = len(per_hospital_cpts.get(hospital_id, set()))
        if actual < min_cpts:
            logger.error(
                "%s: %d unique CPTs < %d minimum (possible format mismatch)",
                hospital_id,
                actual,
                min_cpts,
            )

    # 4. Qualify
    qualified = qualify_batch(normalized)

    # 5. Load benchmarks
    benchmarks = load_benchmarks(data_dir)

    # 6. Merge
    merge_result = merge_records(qualified, benchmarks)
    logger.info(
        "Merged: %d procedures, %d payer rates, %d benchmarks",
        len(merge_result.procedures),
        len(merge_result.payer_rates),
        len(merge_result.benchmarks),
    )

    # 6.5. Record-count regression check
    current_counts = defaultdict(int)
    for p in merge_result.procedures:
        current_counts[p.hospital_id] += 1
    previous_counts = _load_manifest(output_dir)
    regression_errors: list[str] = []
    if previous_counts is not None:
        regression_errors = _check_regression(dict(current_counts), previous_counts)
        for err in regression_errors:
            logger.error("Regression: %s", err)

    # 7. Validate
    validation = validate_etl_output(merge_result, expected_hospitals)
    validation.errors.extend(regression_errors)
    for warn in validation.warnings:
        logger.warning("Validation warning: %s", warn)
    if validation.errors:
        for err in validation.errors:
            logger.error("Validation error: %s", err)
        if not force:
            raise EtlValidationError(validation.errors)
        logger.warning("--force: %d validation error(s) overridden", len(validation.errors))

    # 8. Build normalized CSVs
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_counts = build_csvs(merge_result, output_dir)

    # 9. SHA256 provenance + manifest
    for csv_file in output_dir.glob("*.csv"):
        _sha256_file(csv_file)
    _write_manifest(output_dir, dict(current_counts))

    return EtlResult(
        mrf_records_extracted=len(mrf_records),
        tic_records_extracted=len(tic_records),
        records_after_normalization=len(normalized),
        merged_rows=len(merge_result.procedures),
        csv_rows_written=sum(csv_counts.values()),
        hospitals_found=sorted({p.hospital_id for p in merge_result.procedures}),
        warnings=validation.warnings,
        validation_report=validation,
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )
