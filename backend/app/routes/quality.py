from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[3]
_QUALITY_JSON = _REPO_ROOT / "test-results" / "quality-status.json"


def _fallback_payload() -> dict[str, Any]:
    return {
        "status": "unknown",
        "backendCoveragePct": None,
        "frontendCoveragePct": None,
        "failingTests": [],
        "sha": "",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "fallback",
    }


@router.get("/quality")
def get_quality_status() -> dict[str, Any]:
    if not _QUALITY_JSON.exists():
        return _fallback_payload()
    try:
        payload = json.loads(_QUALITY_JSON.read_text(encoding="utf-8"))
    except Exception:
        return _fallback_payload()
    if isinstance(payload, dict):
        payload.setdefault("source", "test-results/quality-status.json")
        return payload
    return _fallback_payload()
