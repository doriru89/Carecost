"""Specialty configuration — data-driven routing for multi-specialty support.

Each specialty declares its taxonomy code, scenario→CPT mapping, default
scenario, and data file paths. Adding a new specialty = adding a dict entry.
"""

from __future__ import annotations

from typing import Any

SPECIALTY_CONFIG: dict[str, dict[str, Any]] = {
    "Gastroenterology": {
        "taxonomy": "207RG0100X",
        "bundle_cpt": {
            "colonoscopy_screening": "45378",
            "colonoscopy_diagnostic": "45378",
            "colonoscopy_with_biopsy": "45380",
            "colonoscopy_polyp": "45385",
            "egd_with_biopsy": "43239",
            "egd_bleeding": "43255",
            "egd_dilation": "43249",
            "gi_imaging_ct": "74177",
            "capsule_endoscopy": "91110",
            "gi_general": "45378",
        },
        "default_scenario": "gi_general",
        "data_file": "hospital_rates_clean.csv",
        "providers_file": "providers.csv",
    },
    "Dermatology": {
        "taxonomy": "207N00000X",
        "bundle_cpt": {
            "skin_biopsy_tangential": "11102",
            "skin_biopsy_punch": "11104",
            "skin_biopsy_incisional": "11106",
            "mole_removal_benign_small": "11400",
            "mole_removal_benign_medium": "11401",
            "mole_removal_benign_large": "11402",
            "mole_removal_malignant_small": "11600",
            "mole_removal_malignant_medium": "11601",
            "mole_removal_malignant_large": "11602",
            "lesion_destruction_first": "17000",
            "lesion_destruction_additional": "17003",
            "wart_removal": "17110",
            "mohs_surgery_head_neck": "17311",
            "mohs_surgery_additional_block": "17312",
            "mohs_surgery_trunk": "17313",
            "derm_pathology": "88305",
            "phototherapy": "96910",
            "derm_office_visit_established": "99213",
            "derm_office_visit_detailed": "99214",
        },
        "default_scenario": "derm_office_visit_detailed",
        "data_file": "hospital_rates_derm.csv",
        "providers_file": "providers_derm.csv",
    },
}


def get_specialty_config(specialty: str) -> dict[str, Any]:
    """Lookup config by specialty name (case-insensitive match)."""
    for name, config in SPECIALTY_CONFIG.items():
        if name.lower() == specialty.lower():
            return config
    raise KeyError(f"Unknown specialty: {specialty}. Available: {list(SPECIALTY_CONFIG.keys())}")


def get_cpt_for_bundle(specialty: str, bundle_id: str) -> str | None:
    """Resolve a bundle_id to its CPT code for a given specialty."""
    config = get_specialty_config(specialty)
    return config["bundle_cpt"].get(bundle_id)


def all_specialty_names() -> list[str]:
    return list(SPECIALTY_CONFIG.keys())
