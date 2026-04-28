from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.db.postgres import get_engine
from app.modules.shared.domain.health import database_mode_from_url

logger = logging.getLogger(__name__)


def build_health_payload() -> dict[str, Any]:
    settings = get_settings()
    db_ok = False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.warning("Health check: database connectivity failed", exc_info=True)
    return {
        "status": "ok" if db_ok else "degraded",
        "db_mode": database_mode_from_url(settings.database_url),
        "database_connected": db_ok,
        "lava_configured": bool(settings.lava_api_key),
    }
