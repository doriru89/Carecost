from fastapi import APIRouter

from app.routes import (
    auth,
    confirm,
    estimate,
    gi_assistant,
    health,
    hospitals,
    hospitals_v2,
    intake,
    providers,
    quality,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(intake.router, prefix="/intake", tags=["intake"])
api_router.include_router(confirm.router, prefix="/confirm", tags=["confirm"])
api_router.include_router(estimate.router, prefix="/estimate", tags=["estimate"])
api_router.include_router(providers.router, prefix="/providers", tags=["providers"])
api_router.include_router(hospitals.router, prefix="/hospitals", tags=["hospitals"])
api_router.include_router(hospitals_v2.router, prefix="/v2", tags=["hospitals-v2"])
api_router.include_router(gi_assistant.router, tags=["gi-assistant"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(quality.router, tags=["quality"])
