"""Deterministic out-of-pocket estimates (demo)."""

from __future__ import annotations

from typing import Any


def compute_oop_range_cents(
    allowed_min_cents: int,
    allowed_max_cents: int,
    deductible_cents: int | None,
    oop_max_cents: int | None,
    coinsurance_pct: int | None,
    copay_cents: int | None,
    deductible_remaining_unknown: bool,
) -> tuple[int, int, list[str]]:
    """
    Returns (oop_min, oop_max, assumptions).
    If deductible remaining is unknown, return a wide band with two labeled scenarios in assumptions.
    """
    assumptions: list[str] = []
    copay = copay_cents or 0
    coinsurance = (coinsurance_pct or 0) / 100.0

    def band_after_deductible_met(amax: int) -> int:
        # simplified: copay + coinsurance of allowed after deductible exhausted at high end
        spend = max(0, amax - (deductible_cents or 0))
        return int(copay + spend * coinsurance)

    if deductible_remaining_unknown:
        assumptions.append(
            "Deductible remaining unknown — showing min/max across met vs not met scenarios (ASSUMED)."
        )
        # Not met: patient pays up to allowed (capped by OOP max conceptually); met: copay+coinsurance
        oop_low = copay
        oop_high = max(allowed_max_cents, band_after_deductible_met(allowed_max_cents))
        if oop_max_cents:
            oop_high = min(oop_high, oop_max_cents)
        return oop_low, oop_high, assumptions

    ded = deductible_cents or 0
    oop_min = copay + int(max(0, allowed_min_cents - ded) * coinsurance)
    oop_max = copay + int(max(0, allowed_max_cents - ded) * coinsurance)
    if oop_max_cents:
        oop_min = min(oop_min, oop_max_cents)
        oop_max = min(oop_max, oop_max_cents)
    assumptions.append("OOP computed from plan inputs where provided (FACT); call insurer to verify.")
    return oop_min, oop_max, assumptions


def deductible_remaining_unknown_from_intake(intake: dict[str, Any]) -> bool:
    """If user did not supply deductible tracking, treat remaining as unknown."""
    if intake.get("deductible_remaining_cents") is not None:
        return False
    # No explicit remaining field in onboarding — unknown unless we infer met
    return True
