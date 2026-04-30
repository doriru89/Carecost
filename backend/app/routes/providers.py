
from fastapi import APIRouter, Query

from app.api.deps import DbDep
from app.models.api import ProviderListItem
from app.modules.providers.application.use_cases import get_provider as get_provider_use_case
from app.modules.providers.application.use_cases import list_providers as list_providers_use_case

router = APIRouter()

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
    return list_providers_use_case(
        db,
        bbox=bbox,
        zip_code=zip,
        specialty=specialty,
        hospital=hospital,
    )


@router.get("/{provider_id}", response_model=ProviderListItem)
def get_provider(provider_id: str, db: DbDep) -> ProviderListItem:
    return get_provider_use_case(db, provider_id)
