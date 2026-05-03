"""Cost component decomposition service.

Decomposes a negotiated rate into work/PE/MP components using CMS RVU ratios.
Each component carries provenance metadata for the frontend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import CptRvuComponent, HospitalPayerRate

logger = logging.getLogger(__name__)

BOSTON_GPCI = {
    "work": 1.041,
    "pe": 1.194,
    "mp": 0.890,
}


@dataclass
class Provenance:
    source: str
    source_display: str
    effective_date: str = ""
    rate_year: int | None = None
    data_vintage: str = ""


@dataclass
class CostComponent:
    name: str
    amount: float
    rvu: float
    gpci: float
    pct_of_total: float
    provenance: Provenance


@dataclass
class CostComponentResponse:
    hospital_id: str
    cpt: str
    payer_id: str | None
    negotiated_rate: float | None
    rate_provenance: Provenance | None
    components: list[CostComponent] = field(default_factory=list)
    data_tier: str = "full"


def get_cost_components(
    db: Session,
    hospital_id: str,
    cpt: str,
    payer_id: str | None = None,
) -> CostComponentResponse:
    """Decompose negotiated rate into work/PE/MP using RVU ratios."""
    rate_row = _get_latest_rate(db, hospital_id, cpt, payer_id)

    if rate_row is None:
        return CostComponentResponse(
            hospital_id=hospital_id,
            cpt=cpt,
            payer_id=payer_id,
            negotiated_rate=None,
            rate_provenance=None,
            data_tier="no_rate",
        )

    rate_prov = Provenance(
        source=rate_row.source_origin,
        source_display=_source_display(rate_row.source_origin),
        effective_date=rate_row.effective_date,
        rate_year=rate_row.rate_year,
    )

    rvu_row = _get_rvu(db, cpt)
    if rvu_row is None or (rvu_row.facility_total_rvu or 0) == 0:
        return CostComponentResponse(
            hospital_id=hospital_id,
            cpt=cpt,
            payer_id=payer_id,
            negotiated_rate=rate_row.negotiated_rate,
            rate_provenance=rate_prov,
            data_tier="gross_only",
        )

    total_rvu = rvu_row.facility_total_rvu
    neg_rate = rate_row.negotiated_rate or 0
    rvu_prov = Provenance(
        source="cms_pfs",
        source_display="CMS Fee Schedule (RVU)",
        data_vintage=f"CY{rvu_row.pfs_year}",
    )

    components = []
    for name, rvu_val, gpci_key in [
        ("physician_work", rvu_row.work_rvu, "work"),
        ("practice_expense", rvu_row.facility_pe_rvu, "pe"),
        ("malpractice", rvu_row.malpractice_rvu, "mp"),
    ]:
        rvu_val = rvu_val or 0
        gpci = BOSTON_GPCI[gpci_key]
        pct = rvu_val / total_rvu if total_rvu else 0
        amount = round(neg_rate * pct, 2)
        components.append(CostComponent(
            name=name,
            amount=amount,
            rvu=rvu_val,
            gpci=gpci,
            pct_of_total=round(pct * 100, 1),
            provenance=rvu_prov,
        ))

    return CostComponentResponse(
        hospital_id=hospital_id,
        cpt=cpt,
        payer_id=payer_id,
        negotiated_rate=neg_rate,
        rate_provenance=rate_prov,
        components=components,
        data_tier="full",
    )


def _get_latest_rate(
    db: Session, hospital_id: str, cpt: str, payer_id: str | None,
) -> HospitalPayerRate | None:
    stmt = (
        select(HospitalPayerRate)
        .where(HospitalPayerRate.hospital_id == hospital_id)
        .where(HospitalPayerRate.cpt == cpt)
    )
    if payer_id:
        stmt = stmt.where(HospitalPayerRate.payer_id == payer_id)
    stmt = stmt.order_by(HospitalPayerRate.rate_year.desc().nullslast()).limit(1)
    return db.execute(stmt).scalar_one_or_none()


def _get_rvu(db: Session, cpt: str) -> CptRvuComponent | None:
    stmt = (
        select(CptRvuComponent)
        .where(CptRvuComponent.cpt == cpt)
        .where(CptRvuComponent.modifier == "")
        .order_by(CptRvuComponent.pfs_year.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _source_display(source_origin: str) -> str:
    return {
        "mrf": "Hospital Price Transparency File",
        "tic": "Insurer Transparency in Coverage",
        "masscomparecare": "MassCompareCare (MA APCD)",
        "turquoise": "Turquoise Health",
        "fair_health": "FAIR Health",
        "cms_pfs": "CMS Fee Schedule (RVU)",
    }.get(source_origin, source_origin)
