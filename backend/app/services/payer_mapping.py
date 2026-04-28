"""Map intake insurance_carrier strings to price row `payer` keys."""

from __future__ import annotations


def insurance_carrier_to_payer(carrier: str | None) -> str:
    """
    Align with frontend insurer labels and `prices.payer` keys from csv_import.
    Unknown → BCBS_MA (demo default).
    """
    if not carrier or not str(carrier).strip():
        return "BCBS_MA"
    c = str(carrier).lower()
    if "blue cross" in c or "bcbs" in c:
        return "BCBS_MA"
    if "aetna" in c:
        return "AETNA"
    if "harvard" in c or "pilgrim" in c:
        return "HARVARD_PILGRIM"
    if "united" in c or "uhc" in c or "unitedhealth" in c:
        return "UHC"
    return "BCBS_MA"
