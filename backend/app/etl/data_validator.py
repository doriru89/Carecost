"""Validate ETL output before CSV write.

10 checks aligned with the handoff specification.
Missing hospital = ERROR (healthcare data integrity).
"""

from __future__ import annotations

from app.etl.types import MergeResult, ValidationReport

_PRICE_MIN = 1.0
_PRICE_MAX = 500_000.0
_CROSS_VALIDATION_THRESHOLD = 0.15


def validate_etl_output(
    result: MergeResult,
    expected_hospitals: list[str] | None = None,
) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Non-empty
    if not result.procedures:
        errors.append("No procedure records produced")

    # 2. Hospital coverage
    if expected_hospitals:
        found = {p.hospital_id for p in result.procedures}
        for h in expected_hospitals:
            if h not in found:
                errors.append(f"Expected hospital '{h}' missing from output")

    for proc in result.procedures:
        # 3. CPT format
        if not proc.cpt or not proc.cpt.isdigit() or len(proc.cpt) != 5:
            errors.append(f"Invalid CPT '{proc.cpt}' for hospital {proc.hospital_id}")

        # 6. Required fields
        if not proc.hospital_id:
            errors.append("Empty hospital_id in procedure record")
        if not proc.cpt_desc:
            errors.append(f"Empty cpt_desc for {proc.hospital_id}:{proc.cpt}")

    # 10. Duplicate detection — procedures
    proc_keys = [(p.hospital_id, p.cpt) for p in result.procedures]
    seen: set[tuple[str, str]] = set()
    for key in proc_keys:
        if key in seen:
            errors.append(f"Duplicate procedure {key[0]}:{key[1]}")
        seen.add(key)

    # Payer rate checks
    rate_keys: set[tuple[str, str, str, str, str]] = set()
    for pr in result.payer_rates:
        # 5. No negative prices
        if pr.negotiated_rate is not None and pr.negotiated_rate < 0:
            errors.append(f"Negative rate {pr.negotiated_rate} for {pr.hospital_id}:{pr.cpt} payer {pr.payer_id}")

        # 6. Zero payer rate
        if pr.negotiated_rate is not None and pr.negotiated_rate == 0.0:
            errors.append(f"Zero rate for {pr.hospital_id}:{pr.cpt} payer {pr.payer_id}")

        # 7. Price range
        if pr.negotiated_rate is not None and (pr.negotiated_rate < _PRICE_MIN or pr.negotiated_rate > _PRICE_MAX):
            errors.append(
                f"Rate {pr.negotiated_rate} out of range [{_PRICE_MIN}, {_PRICE_MAX}] "
                f"for {pr.hospital_id}:{pr.cpt} payer {pr.payer_id}"
            )

        # 10. Duplicate detection — payer rates
        rk = (pr.hospital_id, pr.cpt, pr.payer_id, pr.source_origin, pr.plan_name)
        if rk in rate_keys:
            errors.append(f"Duplicate payer rate {rk}")
        rate_keys.add(rk)

    # 5. No negative benchmark prices
    for bm in result.benchmarks:
        if bm.price is not None and bm.price < 0:
            errors.append(f"Negative benchmark price {bm.price} for {bm.hospital_id}:{bm.cpt}")

    # 8. Gross > negotiated invariant (WARNING)
    proc_gross = {(p.hospital_id, p.cpt): p.gross_charge for p in result.procedures if p.gross_charge}
    for pr in result.payer_rates:
        gross = proc_gross.get((pr.hospital_id, pr.cpt))
        if gross and pr.negotiated_rate and pr.negotiated_rate > gross:
            warnings.append(
                f"Negotiated ({pr.negotiated_rate}) > gross ({gross}) "
                f"for {pr.hospital_id}:{pr.cpt} payer {pr.payer_id}"
            )

    # 9. MRF/TiC cross-validation at 15%
    mrf_rates: dict[tuple[str, str, str], float] = {}
    tic_rates: dict[tuple[str, str, str], float] = {}
    for pr in result.payer_rates:
        if pr.negotiated_rate is None:
            continue
        key = (pr.hospital_id, pr.cpt, pr.payer_id)
        if pr.source_origin == "mrf":
            mrf_rates[key] = pr.negotiated_rate
        elif pr.source_origin == "tic":
            tic_rates[key] = pr.negotiated_rate

    for key, mrf_val in mrf_rates.items():
        tic_val = tic_rates.get(key)
        if tic_val and mrf_val > 0:
            divergence = abs(mrf_val - tic_val) / mrf_val
            if divergence > _CROSS_VALIDATION_THRESHOLD:
                warnings.append(
                    f"MRF/TiC divergence {divergence:.0%} for {key[0]}:{key[1]} payer {key[2]} "
                    f"(MRF={mrf_val}, TiC={tic_val})"
                )

    return ValidationReport(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        cross_validation={"mrf_tic_pairs": len(set(mrf_rates) & set(tic_rates))},
    )
