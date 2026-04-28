"""FastAPI dependencies for HS256 JWT (Bearer access tokens)."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.jwt_auth import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    sub: str
    email: str | None


def get_current_user_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthUser | None:
    if creds is None or not creds.credentials:
        return None
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from None
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing sub",
        )
    return AuthUser(sub=str(sub), email=claims.get("email"))


def get_current_user_required(
    user: AuthUser | None = Depends(get_current_user_optional),
) -> AuthUser:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user
