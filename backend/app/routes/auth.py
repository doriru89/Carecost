
from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbDep
from app.db.tables import User
from app.models.api import LoginRequest, RegisterRequest, TokenResponse
from app.services.jwt_auth import create_access_token
from app.services.passwords import hash_password, verify_password

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: DbDep) -> TokenResponse:
    existing = db.query(User).filter(User.email == body.email.lower()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    pw_hash = hash_password(body.password)
    u = User(email=body.email.lower(), password_hash=pw_hash)
    db.add(u)
    db.flush()
    token = create_access_token(user_id=str(u.id), email=u.email)
    return TokenResponse(access_token=token, sub=str(u.id), email=u.email)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: DbDep) -> TokenResponse:
    u = db.query(User).filter(User.email == body.email.lower()).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token(user_id=str(u.id), email=u.email)
    return TokenResponse(access_token=token, sub=str(u.id), email=u.email)
