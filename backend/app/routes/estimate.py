from fastapi import APIRouter

from app.api.deps import DbDep
from app.models.api import EstimateRequest, EstimateResponse
from app.services.estimate_service import build_estimate_response

router = APIRouter()


@router.post("", response_model=EstimateResponse)
def post_estimate(body: EstimateRequest, db: DbDep) -> EstimateResponse:
    return build_estimate_response(
        db,
        body.intake,
        body.confirmed,
        body.bundle_id,
        body.scenario_id,
    )
