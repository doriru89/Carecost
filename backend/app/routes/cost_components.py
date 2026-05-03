"""Cost components API — RVU-based rate decomposition with provenance."""

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbDep
from app.services.cost_components import get_cost_components

router = APIRouter()


@router.get("/{hospital_id}/{cpt}")
def cost_components(
    hospital_id: str,
    cpt: str,
    db: DbDep,
    payer_id: str | None = Query(None, description="Payer ID for specific rate"),
) -> dict[str, Any]:
    result = get_cost_components(db, hospital_id, cpt, payer_id)
    return {
        "hospital_id": result.hospital_id,
        "cpt": result.cpt,
        "payer_id": result.payer_id,
        "negotiated_rate": result.negotiated_rate,
        "data_tier": result.data_tier,
        "rate_provenance": _prov_dict(result.rate_provenance) if result.rate_provenance else None,
        "components": [
            {
                "name": c.name,
                "amount": c.amount,
                "rvu": c.rvu,
                "gpci": c.gpci,
                "pct_of_total": c.pct_of_total,
                "provenance": _prov_dict(c.provenance),
            }
            for c in result.components
        ],
    }


def _prov_dict(p) -> dict[str, Any]:
    return {
        "source": p.source,
        "source_display": p.source_display,
        "effective_date": p.effective_date,
        "rate_year": p.rate_year,
        "data_vintage": p.data_vintage,
    }
