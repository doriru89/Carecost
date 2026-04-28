
from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbDep
from app.db.tables import Provider
from app.models.api import ProviderListItem

router = APIRouter()


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


@router.get("", response_model=list[ProviderListItem])
def list_providers(
    db: DbDep,
    bbox: str | None = Query(None, description="minLng,minLat,maxLng,maxLat"),
    zip: str | None = Query(None),
    specialty: str | None = Query(None),
    in_network_only: bool | None = Query(None),
    hospital: str | None = Query(None),
) -> list[ProviderListItem]:
    _ = in_network_only
    q = db.query(Provider)
    if specialty and specialty.strip() and specialty.lower() != "all":
        q = q.filter(Provider.specialties.contains([specialty.strip()]))
    if hospital:
        q = q.filter(Provider.hospital == hospital.strip())
    if zip:
        q = q.filter(Provider.zip == zip.strip())

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


@router.get("/{provider_id}", response_model=ProviderListItem)
def get_provider(provider_id: str, db: DbDep) -> ProviderListItem:
    p = db.get(Provider, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="provider not found")
    return _row_to_item(p)
