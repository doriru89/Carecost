"""Merge qualified records into normalized output (procedures, payer rates, benchmarks).

Groups QualifiedRecords by (hospital_id, cpt) and produces 3 record types.
No payer pivot — the output is long-format, matching the CMS data shape.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.etl.data_qualifier import compute_compliance_score, derive_data_completeness
from app.etl.types import (
    BenchmarkRecord,
    MergeResult,
    PayerRateRecord,
    ProcedureRecord,
    QualifiedRecord,
)
from app.registries import get_hospital

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkData:
    turquoise: dict[tuple[str, str], dict] = field(default_factory=dict)
    masscomparecare: dict[tuple[str, str], dict] = field(default_factory=dict)


def load_benchmarks(data_dir: Path) -> BenchmarkData:
    """Load benchmark JSON files produced by Phase 60 scraping skills."""
    bd = BenchmarkData()

    turq_path = data_dir / "turquoise_data.json"
    if turq_path.exists():
        for row in json.loads(turq_path.read_text()):
            key = (row.get("hospital_id", ""), row.get("cpt", ""))
            if key[0] and key[1]:
                bd.turquoise[key] = row

    mcc_path = data_dir / "masscomparecare_data.json"
    if mcc_path.exists():
        for row in json.loads(mcc_path.read_text()):
            key = (row.get("hospital_id", ""), row.get("cpt", ""))
            if key[0] and key[1]:
                bd.masscomparecare[key] = row

    logger.info(
        "Loaded benchmarks: turquoise=%d, mcc=%d",
        len(bd.turquoise),
        len(bd.masscomparecare),
    )
    return bd


def merge_records(
    qualified: list[QualifiedRecord],
    benchmarks: BenchmarkData | None = None,
) -> MergeResult:
    groups: dict[tuple[str, str], list[QualifiedRecord]] = {}
    for rec in qualified:
        key = (rec.hospital_id, rec.cpt)
        groups.setdefault(key, []).append(rec)

    result = MergeResult()

    for (hospital_id, cpt), recs in groups.items():
        try:
            get_hospital(hospital_id)
        except KeyError:
            logger.error(
                "Hospital '%s' not in registry, skipping %d records", hospital_id, len(recs)
            )
            continue

        mrf_recs = [r for r in recs if r.source_origin == "mrf"]
        first_mrf = mrf_recs[0] if mrf_recs else recs[0]

        payer_rates: list[PayerRateRecord] = []
        canonical_payer_count = 0
        for rec in recs:
            if rec.payer_id is None:
                continue
            rate = rec.negotiated_dollar
            ps = rec.price_source
            if rate is None and rec.estimated_amount is not None and rec.estimated_amount > 0:
                rate = rec.estimated_amount
                ps = "estimated_amount"
            if rate is None or rate <= 0:
                continue
            canonical_payer_count += 1
            payer_rates.append(
                PayerRateRecord(
                    hospital_id=hospital_id,
                    cpt=cpt,
                    payer_id=rec.payer_id,
                    negotiated_rate=rate,
                    plan_name=rec.plan,
                    source=rec.price_source,
                    source_origin=rec.source_origin,
                    billing_class=rec.billing_class,
                    price_source=ps,
                    setting=rec.setting,
                    source_file=rec.source_file,
                    rate_methodology=rec.rate_methodology,
                )
            )

        has_gross = first_mrf.gross is not None and first_mrf.gross > 0
        has_cash = first_mrf.cash is not None and first_mrf.cash > 0
        has_de_id = first_mrf.de_id_min is not None and first_mrf.de_id_max is not None

        data_comp = derive_data_completeness(recs, hospital_id)
        comp_score = compute_compliance_score(
            has_gross=has_gross,
            has_cash=has_cash,
            has_de_id=has_de_id,
            payer_count=canonical_payer_count,
        )

        best_quality = "unknown"
        if any(r.rate_quality == "negotiated" for r in recs):
            best_quality = "negotiated"
        elif has_gross:
            best_quality = "gross_only"

        proc = ProcedureRecord(
            hospital_id=hospital_id,
            cpt=cpt,
            cpt_desc=first_mrf.cpt_desc,
            gross_charge=first_mrf.gross,
            discounted_cash=first_mrf.cash,
            de_identified_min=first_mrf.de_id_min,
            de_identified_max=first_mrf.de_id_max,
            billing_class=first_mrf.billing_class,
            setting=first_mrf.setting,
            data_completeness=data_comp,
            compliance_score=comp_score,
            rate_quality=best_quality,
        )
        result.procedures.append(proc)
        result.payer_rates.extend(payer_rates)

        if benchmarks:
            key = (hospital_id, cpt)
            turq = benchmarks.turquoise.get(key)
            if turq:
                result.benchmarks.append(
                    BenchmarkRecord(
                        hospital_id=hospital_id,
                        cpt=cpt,
                        benchmark_source="turquoise",
                        component="total",
                        price=turq.get("bundled_price"),
                        quality_rating=turq.get("quality_rating"),
                        source_file=turq.get("source_file", ""),
                        effective_date=turq.get("effective_date", ""),
                        data_vintage=turq.get("data_vintage", ""),
                    )
                )

            mcc = benchmarks.masscomparecare.get(key)
            if mcc:
                result.benchmarks.append(
                    BenchmarkRecord(
                        hospital_id=hospital_id,
                        cpt=cpt,
                        benchmark_source="masscomparecare",
                        component="total",
                        price=mcc.get("total_paid"),
                        source_file=mcc.get("source_file", ""),
                        effective_date=mcc.get("scraped_date", ""),
                        data_vintage=mcc.get("data_vintage", ""),
                    )
                )

    return result
