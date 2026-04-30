"""Map intake insurance_carrier strings to price row `payer` keys."""

from __future__ import annotations

from app.registries import carrier_to_payer_id


def insurance_carrier_to_payer(carrier: str | None) -> str:
    return carrier_to_payer_id(carrier)
