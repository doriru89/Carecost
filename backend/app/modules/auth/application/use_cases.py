from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.tables import User
from app.models.api import TokenResponse
from app.services.jwt_auth import create_access_token
from app.services.passwords import hash_password, verify_password


def register_user(db: Session, *, email: str, password: str) -> TokenResponse:
    normalized_email = email.lower()
    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    pw_hash = hash_password(password)
    user = User(email=normalized_email, password_hash=pw_hash)
    db.add(user)
    db.flush()
    token = create_access_token(user_id=str(user.id), email=user.email)
    return TokenResponse(access_token=token, sub=str(user.id), email=user.email)


def login_user(db: Session, *, email: str, password: str) -> TokenResponse:
    normalized_email = email.lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token(user_id=str(user.id), email=user.email)
    return TokenResponse(access_token=token, sub=str(user.id), email=user.email)
