"""CMS Physician Fee Schedule RVU parser.

Parses PPRRVU CSV files (CY2026+). These files have 9 copyright header rows,
with the actual column header at row 10 and data starting at row 11.

Column names are duplicated in the CSV (e.g., "PE RVU" appears twice),
so we use positional indexing.

Public API:
    parse_rvu_file(file_path, target_cpts) -> list[RvuRecord]
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

HEADER_ROW_INDEX = 9
COL_HCPCS = 0
COL_MOD = 1
COL_DESCRIPTION = 2
COL_STATUS = 3
COL_WORK_RVU = 5
COL_NON_FAC_PE_RVU = 6
COL_FAC_PE_RVU = 8
COL_MP_RVU = 10
COL_NON_FAC_TOTAL = 11
COL_FAC_TOTAL = 12
COL_GLOB_DAYS = 14
COL_CONV_FACTOR = 25


@dataclass
class RvuRecord:
    cpt: str
    modifier: str
    description: str
    work_rvu: float | None
    facility_pe_rvu: float | None
    non_facility_pe_rvu: float | None
    malpractice_rvu: float | None
    facility_total_rvu: float | None
    non_facility_total_rvu: float | None
    conversion_factor: float | None
    global_surgery: str
    pfs_year: int
    source_file: str


def _safe_float(val: str) -> float | None:
    val = val.strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def parse_rvu_file(
    file_path: Path,
    target_cpts: set[str],
    pfs_year: int = 2026,
) -> list[RvuRecord]:
    """Parse CMS PPRRVU CSV, filtering to target CPTs."""
    records: list[RvuRecord] = []
    source_name = file_path.name

    with open(file_path, newline="", encoding="latin-1") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i <= HEADER_ROW_INDEX:
                continue
            if len(row) < COL_CONV_FACTOR + 1:
                continue

            cpt = row[COL_HCPCS].strip()
            if cpt not in target_cpts:
                continue

            modifier = row[COL_MOD].strip()
            records.append(
                RvuRecord(
                    cpt=cpt,
                    modifier=modifier,
                    description=row[COL_DESCRIPTION].strip(),
                    work_rvu=_safe_float(row[COL_WORK_RVU]),
                    facility_pe_rvu=_safe_float(row[COL_FAC_PE_RVU]),
                    non_facility_pe_rvu=_safe_float(row[COL_NON_FAC_PE_RVU]),
                    malpractice_rvu=_safe_float(row[COL_MP_RVU]),
                    facility_total_rvu=_safe_float(row[COL_FAC_TOTAL]),
                    non_facility_total_rvu=_safe_float(row[COL_NON_FAC_TOTAL]),
                    conversion_factor=_safe_float(row[COL_CONV_FACTOR]),
                    global_surgery=row[COL_GLOB_DAYS].strip(),
                    pfs_year=pfs_year,
                    source_file=source_name,
                )
            )

    logger.info(
        "Parsed %d RVU records for %d target CPTs from %s",
        len(records),
        len(target_cpts),
        source_name,
    )
    return records
