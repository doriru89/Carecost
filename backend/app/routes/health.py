import logging
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db.postgres import get_engine

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    db_url = s.database_url
    mode = (
        "railway"
        if "railway" in db_url
        else ("local" if "localhost" in db_url or "127.0.0.1" in db_url else "custom")
    )
    db_ok = False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.warning("Health check: database connectivity failed", exc_info=True)
    return {
        "status": "ok" if db_ok else "degraded",
        "db_mode": mode,
        "database_connected": db_ok,
        "lava_configured": bool(s.lava_api_key),
    }
