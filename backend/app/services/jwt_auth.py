"""HS256 JWTs for first-party API authentication."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.config import get_settings


def create_access_token(*, user_id: str, email: str | None) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=s.jwt_access_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "iss": s.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, s.JWT_SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    return jwt.decode(
        token,
        s.JWT_SECRET_KEY,
        algorithms=["HS256"],
        issuer=s.jwt_issuer,
        options={"require": ["exp", "iat", "sub"]},
    )
