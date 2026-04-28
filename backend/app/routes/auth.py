
from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbDep
from app.models.api import LoginRequest, RegisterRequest, TokenResponse
from app.modules.auth.application.use_cases import login_user, register_user

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: DbDep) -> TokenResponse:
    try:
        return register_user(db, email=body.email, password=body.password)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_409_CONFLICT:
            raise
        raise


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: DbDep) -> TokenResponse:
    try:
        return login_user(db, email=body.email, password=body.password)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise
        raise
