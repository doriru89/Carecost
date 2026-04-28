from __future__ import annotations

from typing import Literal


def database_mode_from_url(db_url: str) -> Literal["railway", "local", "custom"]:
    lowered = db_url.lower()
    if "railway" in lowered:
        return "railway"
    if "localhost" in lowered or "127.0.0.1" in lowered:
        return "local"
    return "custom"
