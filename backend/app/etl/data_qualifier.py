"""Qualify NormalizedRecords with provenance metadata.

Canonical source for rate_quality and source_type derivation.
Replaces _derive_rate_quality() in csv_import.py.
"""

from __future__ import annotations

from app.etl.types import NormalizedRecord, QualifiedRecord
from app.models.provenance import RateQuality, SourceType


def qualify_record(rec: NormalizedRecord) -> QualifiedRecord:
    source_type = SourceType.TIC.value if rec.source_origin == "tic" else SourceType.MRF.value

    if rec.negotiated_dollar is not None and rec.negotiated_dollar > 0:
        rate_quality = RateQuality.NEGOTIATED.value
        price_source = "negotiated_dollar"
    elif rec.estimated_amount is not None and rec.estimated_amount > 0:
        rate_quality = RateQuality.NEGOTIATED.value
        price_source = "estimated_amount"
    elif rec.gross is not None and rec.gross > 0:
        rate_quality = RateQuality.GROSS_ONLY.value
        price_source = "gross"
    else:
        rate_quality = RateQuality.UNKNOWN.value
        price_source = ""

    return QualifiedRecord(
        hospital_id=rec.hospital_id,
        cpt=rec.cpt,
        cpt_desc=rec.cpt_desc,
        description=rec.description,
        payer_id=rec.payer_id,
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
        source_origin=rec.source_origin,
        mrf_format=rec.mrf_format,
        source_type=source_type,
        rate_quality=rate_quality,
        price_source=price_source,
        price_granularity="itemized",
    )


def qualify_batch(records: list[NormalizedRecord]) -> list[QualifiedRecord]:
    return [qualify_record(r) for r in records]


def derive_data_completeness(
    records: list[QualifiedRecord], hospital_id: str,
) -> str:
    hospital_records = [r for r in records if r.hospital_id == hospital_id]
    if not hospital_records:
        return "unknown"

    has_negotiated = any(
        r.rate_quality == RateQuality.NEGOTIATED.value and r.payer_id is not None
        for r in hospital_records
    )
    if has_negotiated:
        return "full"

    has_gross = any(r.gross is not None and r.gross > 0 for r in hospital_records)
    if has_gross:
        return "gross_only"

    return "unknown"


def compute_compliance_score(
    *, has_gross: bool, has_cash: bool, has_de_id: bool, payer_count: int,
) -> str:
    if not has_gross:
        return "non_compliant"
    if has_cash and payer_count >= 2 and has_de_id:
        return "full"
    if payer_count >= 1 or has_cash:
        return "partial"
    return "minimal"


def derive_rate_quality_from_csv_row(row: dict[str, str]) -> str:
    from app.services.csv_import import _parse_float_cell

    payer_keys = ("bcbs_price", "aetna_price", "harvard_pilgrim_price", "uhc_price")
    benchmark_keys = ("turquoise_bundled_price", "masscomparecare_total_paid", "fh_physician_in_network")

    if any(_parse_float_cell(row.get(k, "")) for k in payer_keys):
        return RateQuality.NEGOTIATED.value
    if _parse_float_cell(row.get("gross_charge", "")):
        return RateQuality.GROSS_ONLY.value
    if any(_parse_float_cell(row.get(k, "")) for k in benchmark_keys):
        return RateQuality.BENCHMARK_ONLY.value
    return RateQuality.UNKNOWN.value
