"""HS256 access token create/verify."""

import uuid

import jwt
import pytest

from app.services.jwt_auth import create_access_token, decode_access_token


def test_create_and_decode_roundtrip(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-jwt")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://x/x")
    uid = str(uuid.uuid4())
    token = create_access_token(user_id=uid, email="u@example.com")
    out = decode_access_token(token)
    assert out["sub"] == uid
    assert out["email"] == "u@example.com"


def test_decode_rejects_wrong_secret(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "secret-a")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://x/x")
    token = create_access_token(user_id=str(uuid.uuid4()), email=None)
    monkeypatch.setenv("JWT_SECRET_KEY", "secret-b")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token)
