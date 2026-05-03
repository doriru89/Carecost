from fastapi import APIRouter, Depends

from app.api.auth_deps import AuthUser, get_current_user_required
from app.api.deps import DbDep
from app.models.api import UserMePatch, UserMeResponse
from app.modules.users.application.use_cases import get_user_me, patch_user_me

router = APIRouter()


@router.get("/me", response_model=UserMeResponse)
def get_me(db: DbDep, user: AuthUser = Depends(get_current_user_required)) -> UserMeResponse:
    return get_user_me(db, user)


@router.patch("/me", response_model=UserMeResponse)
def patch_me(
    body: UserMePatch,
    db: DbDep,
    user: AuthUser = Depends(get_current_user_required),
) -> UserMeResponse:
    return patch_user_me(db, user, body)
