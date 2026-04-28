from fastapi import APIRouter

from app.api.deps import DbDep
from app.models.api import EstimateRequest, EstimateResponse
from app.modules.pricing.application.use_cases import estimate_from_intake

router = APIRouter()


@router.post("", response_model=EstimateResponse)
def post_estimate(body: EstimateRequest, db: DbDep) -> EstimateResponse:
    return estimate_from_intake(
        db,
        intake=body.intake,
        confirmed=body.confirmed,
        bundle_id=body.bundle_id,
        scenario_id=body.scenario_id,
    )
