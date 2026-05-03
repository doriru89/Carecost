"""Normalize raw hospital names and payer names to registry IDs.

Uses hospitals.yaml source_name_aliases + payers.yaml normalization_patterns.
Falls back to exact name match for hospitals, non_canonical_payers for unknown payers.
"""

from __future__ import annotations

import logging

from app.etl.types import NormalizedRecord, RawMrfRecord, RawTicRecord
from app.registries import (
    all_hospitals,
    all_payers,
    load_etl_config,
)

logger = logging.getLogger(__name__)


def normalize_payer_name(raw_payer: str) -> tuple[str | None, bool]:
    """Resolve raw payer string to (payer_id, include_in_output).

    Returns (payer_id, True) for canonical payers.
    Returns (None, True) for non-canonical but includable (Medicare, Cash).
    Returns (None, False) for excluded payers (Cigna, etc.).
    """
    if not raw_payer or not raw_payer.strip():
        return None, False

    upper = raw_payer.upper()

    for pid, p in all_payers().items():
        if p.normalization_patterns:
            for pat in p.normalization_patterns:
                if pat.upper() in upper:
                    return pid, True

    config = load_etl_config()
    for name, rule in config.non_canonical_payers.items():
        if name.upper() in upper or upper in name.upper():
            return None, bool(rule.get("include_in_output", False))

    return None, False


def normalize_hospital_name(raw_name: str, source: str) -> str | None:
    """Resolve raw hospital name to hospital_id.

    Checks source_name_aliases first (source-specific), then exact name match.
    """
    if not raw_name or not raw_name.strip():
        return None

    hospitals = all_hospitals()

    for hid, h in hospitals.items():
        if h.source_name_aliases:
            alias = h.source_name_aliases.get(source)
            if alias and alias == raw_name:
                return hid

    for hid, h in hospitals.items():
        if h.name == raw_name:
            return hid

    return None


def normalize_records(
    records: list[RawMrfRecord | RawTicRecord],
) -> list[NormalizedRecord]:
    """Batch-normalize raw records. Drops records with unmatched hospitals."""
    result: list[NormalizedRecord] = []

    for rec in records:
        if isinstance(rec, RawMrfRecord):
            source = "mrf"
            hospital_id = normalize_hospital_name(rec.hospital_name, source)
            if hospital_id is None:
                logger.warning(
                    "Dropping MRF record: unmatched hospital '%s' (CPT=%s, payer='%s', file=%s)",
                    rec.hospital_name,
                    rec.cpt,
                    rec.payer_raw,
                    rec.source_file,
                )
                continue
            payer_id, include = normalize_payer_name(rec.payer_raw)
            if not include and payer_id is None:
                payer_id_val = None
            else:
                payer_id_val = payer_id

            result.append(
                NormalizedRecord(
                    hospital_id=hospital_id,
                    cpt=rec.cpt,
                    cpt_desc=rec.cpt_desc,
                    description=rec.description,
                    payer_id=payer_id_val,
                    payer_raw=rec.payer_raw,
                    plan=rec.plan,
                    setting=rec.setting,
                    gross=rec.gross,
                    cash=rec.cash,
                    negotiated_dollar=rec.negotiated_dollar,
                    estimated_amount=rec.estimated_amount,
                    de_id_min=rec.de_id_min,
                    de_id_max=rec.de_id_max,
                    billing_class=rec.billing_class,
                    source_file=rec.source_file,
                    source_origin="mrf",
                    mrf_format=rec.mrf_format,
                )
            )

        elif isinstance(rec, RawTicRecord):
            hospital_id = normalize_hospital_name(rec.hospital_name, "tic")
            if hospital_id is None:
                logger.warning(
                    "Dropping TiC record: unmatched hospital '%s' (CPT=%s, insurer=%s, file=%s)",
                    rec.hospital_name,
                    rec.cpt,
                    rec.insurer_key,
                    rec.source_file,
                )
                continue

            payer_id, _ = normalize_payer_name(rec.insurer_key.upper())
            result.append(
                NormalizedRecord(
                    hospital_id=hospital_id,
                    cpt=rec.cpt,
                    cpt_desc=rec.cpt_desc,
                    description="",
                    payer_id=payer_id,
                    payer_raw=rec.insurer_key,
                    plan=rec.plan,
                    setting=rec.setting,
                    gross=None,
                    cash=None,
                    negotiated_dollar=rec.negotiated_rate,
                    estimated_amount=None,
                    de_id_min=None,
                    de_id_max=None,
                    billing_class=rec.billing_class,
                    source_file=rec.source_file,
                    source_origin="tic",
                )
            )

    return result
