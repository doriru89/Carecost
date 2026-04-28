from typing import Any

from fastapi import APIRouter

from app.modules.shared.application.health_use_cases import build_health_payload

router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    return build_health_payload()
