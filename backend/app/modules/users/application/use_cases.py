from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_deps import AuthUser
from app.db.repositories.user_repository import UserRepository
from app.models.api import UserMePatch, UserMeResponse


def get_user_me(db: Session, auth_user: AuthUser) -> UserMeResponse:
    repo = UserRepository(db)
    user = repo.find_by_id(auth_user.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserMeResponse(
        sub=str(user.id),
        email=user.email,
        user_profile=user.user_profile,
        insurance_profile=user.insurance_profile,
    )


def patch_user_me(db: Session, auth_user: AuthUser, body: UserMePatch) -> UserMeResponse:
    if body.user_profile is None and body.insurance_profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide user_profile and/or insurance_profile",
        )

    repo = UserRepository(db)
    user = repo.patch_profiles(
        auth_user.sub,
        user_profile=body.user_profile,
        insurance_profile=body.insurance_profile,
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserMeResponse(
        sub=str(user.id),
        email=user.email,
        user_profile=user.user_profile,
        insurance_profile=user.insurance_profile,
    )
