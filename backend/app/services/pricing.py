"""Aggregate allowed amounts from price rows."""

from __future__ import annotations

from typing import Any


def min_max_allowed_for_provider_prices(price_docs: list[dict[str, Any]]) -> tuple[int, int]:
    if not price_docs:
        return 0, 0
    mins = [p["min_rate_cents"] for p in price_docs]
    maxs = [p["max_rate_cents"] for p in price_docs]
    return min(mins), max(maxs)


def pick_primary_source(price_docs: list[dict[str, Any]]) -> str:
    priority = ("mrf_sample", "mrf", "turquoise_cache", "fair_health_cache", "mock")
    sources = [p.get("source", "") for p in price_docs]
    for pr in priority:
        if pr in sources:
            return pr
    return price_docs[0].get("source", "unknown")


def avg_confidence(price_docs: list[dict[str, Any]]) -> float:
    if not price_docs:
        return 0.0
    return sum(float(p.get("confidence", 0)) for p in price_docs) / len(price_docs)
