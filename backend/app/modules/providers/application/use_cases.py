from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.tables import Provider
from app.models.api import ProviderListItem


def _row_to_item(p: Provider) -> ProviderListItem:
    return ProviderListItem(
        id=p.npi,
        name=p.name,
        address=p.address,
        city=p.city,
        zip=p.zip,
        lat=p.lat,
        lng=p.lng,
        phone=p.phone,
        specialties=list(p.specialties),
        source=p.source,
        hospital=p.hospital,
    )


def list_providers(
    db: Session,
    *,
    bbox: str | None,
    zip_code: str | None,
    specialty: str | None,
    hospital: str | None,
) -> list[ProviderListItem]:
    q = db.query(Provider)
    if specialty and specialty.strip() and specialty.lower() != "all":
        q = q.filter(Provider.specialties.contains([specialty.strip()]))
    if hospital:
        q = q.filter(Provider.hospital == hospital.strip())
    if zip_code:
        q = q.filter(Provider.zip == zip_code.strip())

    providers = q.all()
    if bbox:
        try:
            parts = [float(x.strip()) for x in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError
            min_lng, min_lat, max_lng, max_lat = parts
        except ValueError:
            raise HTTPException(status_code=400, detail="bbox must be minLng,minLat,maxLng,maxLat")
        providers = [
            p for p in providers if min_lng <= p.lng <= max_lng and min_lat <= p.lat <= max_lat
        ]
    return [_row_to_item(p) for p in providers]


def get_provider(db: Session, provider_id: str) -> ProviderListItem:
    provider = db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="provider not found")
    return _row_to_item(provider)
