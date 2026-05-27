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

    Patterns are matched longest-first to avoid ambiguity (e.g., "HARVARD PILGRIM"
    must match before "UNITED" for strings containing both).
    """
    if not raw_payer or not raw_payer.strip():
        return None, False

    upper = raw_payer.upper()

    candidates: list[tuple[str, str]] = []
    for pid, p in all_payers().items():
        if p.normalization_patterns:
            for pat in p.normalization_patterns:
                candidates.append((pat.upper(), pid))
    candidates.sort(key=lambda x: len(x[0]), reverse=True)

    for pat, pid in candidates:
        if pat in upper:
            logger.debug("Resolved %r -> %s via pattern %r", raw_payer, pid, pat)
            return pid, True

    config = load_etl_config()
    for name, rule in config.non_canonical_payers.items():
        if name.upper() in upper or upper in name.upper():
            return None, bool(rule.get("include_in_output", False))

    return None, False


def classify_plan_type(plan_name: str) -> str:
    """Classify a plan as commercial/medicare/medicaid/unknown from its name.

    Uses patterns from etl_config.yaml plan_type_classification.
    Exclusions checked first (e.g., "MEDICARE ADVANTAGE" is NOT medicare).
    """
    if not plan_name or not plan_name.strip():
        return "unknown"

    upper = plan_name.upper()
    config = load_etl_config()
    ptc = config.plan_type_classification

    for excl in ptc.exclusions:
        if excl.upper() in upper:
            return "unknown"

    for pat in ptc.medicare:
        if pat.upper() in upper:
            return "medicare"

    for pat in ptc.medicaid:
        if pat.upper() in upper:
            return "medicaid"

    return "unknown"


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


def _reconcile_payer_from_plan(payer_id: str | None, plan_name: str) -> str | None:
    """Cross-check payer_id against plan_name for misattributed plans.

    Hospitals file the same plan under multiple payer entities in MRFs.
    When plan_name contains a more specific payer signal than payer_raw,
    override payer_id. E.g., payer_raw="UNITED [2025]" → payer_id=UHC,
    but plan="BMC HB HARVARD PILGRIM" → should be HARVARD_PILGRIM.
    """
    if not plan_name or not plan_name.strip():
        return payer_id

    plan_payer_id, _ = normalize_payer_name(plan_name)
    if plan_payer_id and plan_payer_id != payer_id:
        logger.info(
            "Reconciled payer_id: %s -> %s (plan_name=%r)",
            payer_id,
            plan_payer_id,
            plan_name,
        )
        return plan_payer_id
    return payer_id


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
                payer_id_val = _reconcile_payer_from_plan(payer_id, rec.plan)

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
                    plan_type=classify_plan_type(rec.plan),
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
                    plan_type=classify_plan_type(rec.plan),
                )
            )

    before = len(result)
    result = _deduplicate_normalized(result)
    if before > len(result):
        logger.info(
            "Post-normalization dedup: %d -> %d records (%d collapsed from payer alias convergence)",
            before,
            len(result),
            before - len(result),
        )
    return result


def _deduplicate_normalized(records: list[NormalizedRecord]) -> list[NormalizedRecord]:
    """Collapse records sharing (hospital_id, cpt, payer_id, plan) after payer normalization.

    Multiple payer_raw entities (e.g., "HARVARD PILGRIM [120001]" and
    "HARVARD PILGRIM ALTERNATE [120002]") map to the same payer_id under the same plan.
    Keep the record with the highest negotiated_dollar. On ties, prefer the record
    with more populated base fields to avoid gross/cash data loss.
    """
    best: dict[tuple[str, str, str | None, str, str], NormalizedRecord] = {}
    for rec in records:
        key = (rec.hospital_id, rec.cpt, rec.payer_id, rec.plan, rec.source_origin)
        existing = best.get(key)
        if existing is None:
            best[key] = rec
        else:
            new_rate = rec.negotiated_dollar or 0.0
            old_rate = existing.negotiated_dollar or 0.0
            if new_rate > old_rate:
                best[key] = rec
            elif new_rate == old_rate and _norm_field_richness(rec) > _norm_field_richness(existing):
                best[key] = rec
    return list(best.values())


def _norm_field_richness(rec: NormalizedRecord) -> int:
    """Count non-None base price fields for tiebreaking."""
    return sum(1 for v in (rec.gross, rec.cash, rec.de_id_min, rec.de_id_max) if v is not None)
