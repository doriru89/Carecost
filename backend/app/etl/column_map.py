"""SSOT mapping between payer_id and legacy wide-format column names.

The wide format used inconsistent naming (harvard_pilgrim_price but hp_source).
These names are baked into the legacy CSV and ORM. All consumers that translate
between normalized and wide formats import from here.
"""

from __future__ import annotations

PAYER_RATE_MAP: dict[str, tuple[str, str, str]] = {
    "BCBS_MA": ("bcbs_price", "bcbs_source", "bcbs_plan"),
    "AETNA": ("aetna_price", "aetna_source", "aetna_plan"),
    "HARVARD_PILGRIM": ("harvard_pilgrim_price", "hp_source", "hp_plan_name"),
    "UHC": ("uhc_price", "uhc_source", "uhc_source"),
}

FH_COMPONENT_MAP: dict[str, str] = {
    "physician_in_network": "fh_physician_in_network",
    "physician_oon": "fh_physician_oon",
    "anesthesia_in_network": "fh_anesthesia_in_network",
    "facility_hosp_in_network": "fh_facility_hosp_in_network",
    "facility_asc_in_network": "fh_facility_asc_in_network",
    "pathology_in_network": "fh_pathology_in_network",
}
