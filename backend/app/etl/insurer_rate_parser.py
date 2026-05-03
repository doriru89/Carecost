"""Two-pass stream parser for insurer Transparency in Coverage (TiC) files.

Matches negotiated rates to Boston hospitals via NPI lookup against the
hospital registry. Uses ijson for memory-efficient streaming — these files
are 111MB+ in production.

Public API:
    parse_insurer_rates(file_path, insurer_key, target_cpts) -> list[RawTicRecord]
    build_hospital_npi_map() -> dict[str, str]   # NPI -> hospital_name
"""

from __future__ import annotations

import gzip
import logging
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import ijson

from app.etl.types import RawTicRecord
from app.registries import get_hospital, hospital_all_npis

logger = logging.getLogger(__name__)

# Rate type priority: higher = preferred when deduplicating
_RATE_TYPE_PRIORITY = {
    "fee schedule": 2,
    "negotiated": 1,
    "derived": 0,
}


@dataclass
class _PendingRate:
    """Intermediate rate record before NPI resolution."""

    billing_code: str
    name: str
    negotiated_rate: float
    negotiated_type: str
    billing_class: str
    provider_group_ids: list[int]
    source_file: str


def build_hospital_npi_map() -> dict[str, str]:
    """NPI -> hospital_name. Wraps hospital_all_npis() with name resolution."""
    npi_to_id = hospital_all_npis()
    return {npi: get_hospital(hid).name for npi, hid in npi_to_id.items()}


def parse_insurer_rates(
    file_path: Path,
    insurer_key: str,
    target_cpts: set[str],
) -> list[RawTicRecord]:
    """Two-pass stream parse of TiC file. Returns matched rates for Boston hospitals."""
    if not target_cpts:
        logger.warning("Empty CPT target set — nothing to extract")
        return []

    npi_to_name = build_hospital_npi_map()
    npi_to_id = hospital_all_npis()
    source_name = file_path.name

    # Pass 1: collect rates for matching CPTs
    pending_rates = _pass1_collect_rates(file_path, target_cpts, source_name)
    if not pending_rates:
        return []

    # Pass 2: build provider_group_id -> NPI map
    pgid_to_npis = _pass2_collect_npis(file_path)

    # Join: resolve NPIs to hospitals
    raw_records = _join_rates_to_hospitals(
        pending_rates,
        pgid_to_npis,
        npi_to_name,
        npi_to_id,
        insurer_key,
        source_name,
    )

    # Deduplicate: prefer fee_schedule over negotiated for same (hospital, CPT)
    return _deduplicate_rates(raw_records)


def _open_tic_stream(path: Path) -> IO[bytes]:
    """Open .json.gz or .zip for ijson streaming."""
    suffix = path.suffix.lower()
    if suffix == ".gz" or path.name.endswith(".json.gz"):
        return gzip.open(path, "rb")  # type: ignore[return-value]
    elif suffix == ".zip":
        zf = zipfile.ZipFile(path)
        json_files = [n for n in zf.namelist() if n.endswith(".json")]
        if not json_files:
            raise ValueError(f"No .json file found in {path}")
        return zf.open(json_files[0])
    else:
        # Plain JSON
        return open(path, "rb")


def _pass1_collect_rates(
    path: Path,
    target_cpts: set[str],
    source_name: str,
) -> list[_PendingRate]:
    """Pass 1: scan in_network items, collect rates for matching CPTs."""
    pending: list[_PendingRate] = []

    with _open_tic_stream(path) as stream:
        for item in ijson.items(stream, "in_network.item"):
            billing_code = str(item.get("billing_code", ""))
            if billing_code not in target_cpts:
                continue

            name = item.get("name", "")
            for neg_rate_group in item.get("negotiated_rates", []):
                provider_ref_ids = neg_rate_group.get("provider_references", [])
                for price in neg_rate_group.get("negotiated_prices", []):
                    neg_type = price.get("negotiated_type", "")
                    # Skip percentage type (Dana-Farber artifact)
                    if neg_type == "percentage":
                        continue

                    pending.append(
                        _PendingRate(
                            billing_code=billing_code,
                            name=name,
                            negotiated_rate=float(price.get("negotiated_rate", 0)),
                            negotiated_type=neg_type,
                            billing_class=price.get("billing_class", ""),
                            provider_group_ids=[int(x) for x in provider_ref_ids],
                            source_file=source_name,
                        )
                    )

    logger.info("Pass 1: collected %d pending rates from %s", len(pending), source_name)
    return pending


def _pass2_collect_npis(path: Path) -> dict[int, list[str]]:
    """Pass 2: build provider_group_id -> list of NPIs."""
    pgid_to_npis: dict[int, list[str]] = defaultdict(list)

    with _open_tic_stream(path) as stream:
        for item in ijson.items(stream, "provider_references.item"):
            pgid = int(item.get("provider_group_id", 0))
            for group in item.get("provider_groups", []):
                for npi in group.get("npi", []):
                    pgid_to_npis[pgid].append(str(npi))

    logger.info("Pass 2: found %d provider groups", len(pgid_to_npis))
    return dict(pgid_to_npis)


def _join_rates_to_hospitals(
    pending_rates: list[_PendingRate],
    pgid_to_npis: dict[int, list[str]],
    npi_to_name: dict[str, str],
    npi_to_id: dict[str, str],
    insurer_key: str,
    source_name: str,
) -> list[RawTicRecord]:
    """Join rate records to hospital NPIs, producing RawTicRecords."""
    records: list[RawTicRecord] = []

    for rate in pending_rates:
        for pgid in rate.provider_group_ids:
            npis = pgid_to_npis.get(pgid, [])
            for npi in npis:
                if npi not in npi_to_name:
                    continue

                records.append(
                    RawTicRecord(
                        hospital_name=npi_to_name[npi],
                        matched_npi=npi,
                        cpt=rate.billing_code,
                        cpt_desc=rate.name,
                        negotiated_rate=rate.negotiated_rate,
                        negotiated_type=rate.negotiated_type,
                        billing_class=rate.billing_class,
                        setting=_infer_setting(rate.billing_class),
                        plan="",
                        insurer_key=insurer_key,
                        source_file=source_name,
                    )
                )

    logger.info("Join: produced %d matched records", len(records))
    return records


def _infer_setting(billing_class: str) -> str:
    """Map billing_class to a display setting."""
    if billing_class == "institutional":
        return "facility"
    elif billing_class == "professional":
        return "office"
    return billing_class


def _deduplicate_rates(records: list[RawTicRecord]) -> list[RawTicRecord]:
    """When multiple rate types exist for same (hospital, CPT), prefer fee_schedule."""
    best: dict[tuple[str, str], RawTicRecord] = {}
    for rec in records:
        key = (rec.hospital_name, rec.cpt)
        existing = best.get(key)
        if existing is None:
            best[key] = rec
        else:
            existing_priority = _RATE_TYPE_PRIORITY.get(existing.negotiated_type, 0)
            new_priority = _RATE_TYPE_PRIORITY.get(rec.negotiated_type, 0)
            if new_priority > existing_priority:
                best[key] = rec

    return list(best.values())
