"""Flatten normalized hospital dict to legacy wide format.

RETIREMENT TARGET: delete this file when frontend migrates to normalized API.
"""

from __future__ import annotations

from typing import Any

from app.etl.column_map import PAYER_RATE_MAP

# Current API returns 4 FH fields — match exactly, don't use full 6-field map.
_LEGACY_FH_FIELDS = {
    "physician_in_network": "fh_physician_in_network",
    "anesthesia_in_network": "fh_anesthesia_in_network",
    "facility_hosp_in_network": "fh_facility_hosp_in_network",
    "pathology_in_network": "fh_pathology_in_network",
}


def flatten_to_legacy(normalized: dict[str, Any]) -> dict[str, Any]:
    """Convert a normalized hospital dict to the legacy wide-format response.

    The wide format has per-payer columns (bcbs_price, aetna_price, etc.)
    instead of a payer_rates array. This exists solely for backward compat
    with the current frontend.
    """
    d: dict[str, Any] = {
        "hospital_id": normalized["hospital_id"],
        "cpt": normalized["cpt"],
        "cpt_desc": normalized["cpt_desc"],
        "gross_charge": normalized["gross_charge"],
        "discounted_cash": normalized["discounted_cash"],
        "de_identified_min": normalized["de_identified_min"],
        "de_identified_max": normalized["de_identified_max"],
        "billing_class": normalized["billing_class"],
        "setting": normalized["setting"],
        "rate_methodology": normalized["rate_methodology"],
    }

    # Initialize all payer columns to None/empty
    for payer_id, (price_col, source_col, plan_col) in PAYER_RATE_MAP.items():
        d[price_col] = None
        d[source_col] = ""
        if plan_col != source_col:
            d[plan_col] = ""
    d["bcbs_tic_rate"] = None
    d["bcbs_tic_billing_class"] = ""

    # Populate from payer_rates array
    for pr in normalized.get("payer_rates", []):
        payer_id = pr["payer_id"]
        mapping = PAYER_RATE_MAP.get(payer_id)
        if not mapping:
            continue
        price_col, source_col, plan_col = mapping

        if pr["source_origin"] == "tic" and payer_id == "BCBS_MA":
            d["bcbs_tic_rate"] = pr["negotiated_rate"]
            d["bcbs_tic_billing_class"] = pr["billing_class"]
        else:
            d[price_col] = pr["negotiated_rate"]
            d[source_col] = pr["source"]
            if plan_col != source_col:
                d[plan_col] = pr["plan_name"]

    # Initialize all benchmark columns to None
    d["turquoise_bundled_price"] = None
    d["turquoise_quality_rating"] = None
    d["masscomparecare_total_paid"] = None
    for col in _LEGACY_FH_FIELDS.values():
        d[col] = None

    # Populate from benchmarks array
    for bm in normalized.get("benchmarks", []):
        src = bm["benchmark_source"]
        comp = bm["component"]
        if src == "turquoise" and comp == "total":
            d["turquoise_bundled_price"] = bm["price"]
            d["turquoise_quality_rating"] = bm["quality_rating"]
        elif src == "masscomparecare" and comp == "total":
            d["masscomparecare_total_paid"] = bm["price"]
        elif src == "fair_health":
            fh_col = _LEGACY_FH_FIELDS.get(comp)
            if fh_col:
                d[fh_col] = bm["price"]

    return d
