"""Deterministic scenario → CPT bundle mapping (multi-specialty)."""

from __future__ import annotations

from typing import Any

from app.services.specialty_config import SPECIALTY_CONFIG

# All valid scenario IDs across specialties
SCENARIO_IDS: tuple[str, ...] = tuple(
    sid for config in SPECIALTY_CONFIG.values() for sid in config["bundle_cpt"]
)


def _get_text(intake: dict[str, Any], confirmed: dict[str, Any] | None) -> str:
    merged = {**(confirmed or {}), **intake}
    return " ".join(
        [
            str(merged.get("free_text") or ""),
            " ".join(merged.get("symptoms") or [])
            if isinstance(merged.get("symptoms"), list)
            else "",
        ]
    ).lower()


def _detect_specialty(merged: dict[str, Any]) -> str:
    """Detect specialty from intake fields."""
    explicit = merged.get("specialty") or merged.get("care_focus") or ""
    s = explicit.lower()
    if "derm" in s or "skin" in s:
        return "Dermatology"
    return "Gastroenterology"


def infer_scenario_id(intake: dict[str, Any], confirmed: dict[str, Any] | None) -> str:
    merged = {**(confirmed or {}), **intake}
    explicit = merged.get("scenario_id")
    if isinstance(explicit, str) and explicit in SCENARIO_IDS:
        return explicit

    specialty = _detect_specialty(merged)
    text = _get_text(intake, confirmed)

    if specialty == "Dermatology":
        return _infer_derm_scenario(text)
    return _infer_gi_scenario(text, merged)


def _infer_gi_scenario(text: str, merged: dict[str, Any]) -> str:
    if any(x in text for x in ("screening", "preventive", "routine colon")):
        return "colonoscopy_screening"
    if any(x in text for x in ("bleeding", "pain", "diagnostic", "symptom")):
        return "colonoscopy_diagnostic"
    if "egd" in text or "endoscopy" in text or "biopsy" in text:
        return "egd_with_biopsy"
    if merged.get("care_focus") and "gastro" in str(merged.get("care_focus")).lower():
        return "colonoscopy_screening"
    return "gi_general"


def _infer_derm_scenario(text: str) -> str:
    if any(x in text for x in ("mohs",)):
        return "mohs_surgery_head_neck"
    if any(x in text for x in ("wart", "cryo", "freeze", "destroy")):
        return "lesion_destruction_first"
    if any(x in text for x in ("mole", "excision")):
        if "malig" in text:
            return "mole_removal_malignant_small"
        return "mole_removal_benign_small"
    if any(x in text for x in ("biopsy", "suspicious", "lesion")):
        if "punch" in text:
            return "skin_biopsy_punch"
        return "skin_biopsy_tangential"
    if any(x in text for x in ("laser", "phototherapy", "light")):
        return "phototherapy"
    if any(x in text for x in ("rash", "eczema", "acne", "consult", "visit")):
        return "derm_office_visit_detailed"
    return "derm_office_visit_detailed"


def scenario_to_bundle_id(scenario_id: str) -> str:
    if scenario_id == "gi_general":
        return "colonoscopy_screening"
    if scenario_id in SCENARIO_IDS:
        return scenario_id
    return "colonoscopy_screening"
