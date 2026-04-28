"""Intake validation and normalization (no LLM)."""

from __future__ import annotations

from typing import Any

REQUIRED_FOR_ESTIMATE = ("zip", "insurance_carrier", "care_focus")


def normalize_intake(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if v is None:
            continue
        if isinstance(v, str):
            s = v.strip()
            if s:
                out[k] = s
        elif isinstance(v, list):
            out[k] = v
        else:
            out[k] = v
    return out


def missing_required_fields(normalized: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in REQUIRED_FOR_ESTIMATE:
        if key not in normalized or normalized[key] in (None, "", []):
            missing.append(key)
    return missing


def validate_intake_payload(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized = normalize_intake(raw)
    return normalized, missing_required_fields(normalized)
