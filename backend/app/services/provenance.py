"""Provenance tags for estimate fields."""

from __future__ import annotations

from typing import Literal

from app.models.api import ProvenanceItem


def allowed_amount_provenance(
    source: str, confidence: float, kind: Literal["FACT", "ASSUMED"] = "FACT"
) -> list[ProvenanceItem]:
    return [
        ProvenanceItem(
            field="allowed_amount_range",
            source=source,
            confidence=confidence,
            kind=kind,
        )
    ]
