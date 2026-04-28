"""Regression contracts for auth, profile, providers, and estimate flows."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_login_and_profile_patch_flow(client: TestClient) -> None:
    register = client.post(
        "/api/auth/register",
        json={"email": "tester@example.com", "password": "supersecure"},
    )
    assert register.status_code == 200
    token = register.json()["access_token"]
    assert token

    login = client.post(
        "/api/auth/login",
        json={"email": "tester@example.com", "password": "supersecure"},
    )
    assert login.status_code == 200
    assert login.json()["email"] == "tester@example.com"

    me_before = client.get("/api/users/me", headers=_bearer(token))
    assert me_before.status_code == 200
    assert me_before.json()["user_profile"] is None

    patch = client.patch(
        "/api/users/me",
        headers=_bearer(token),
        json={
            "user_profile": {
                "fullName": "Test User",
                "zip": "02118",
                "dob": "2000-01-01",
                "onboarding_completed": True,
            },
            "insurance_profile": {
                "carrier": "Blue Cross Blue Shield of Massachusetts",
                "planName": "PPO",
                "planType": "PPO",
                "deductible": 1000,
                "oopMax": 5000,
                "coinsurance": 20,
            },
        },
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["user_profile"]["fullName"] == "Test User"
    assert body["insurance_profile"]["carrier"] == "Blue Cross Blue Shield of Massachusetts"


def test_register_duplicate_email_returns_409(client: TestClient) -> None:
    payload = {"email": "dupe@example.com", "password": "supersecure"}
    first = client.post("/api/auth/register", json=payload)
    second = client.post("/api/auth/register", json=payload)
    assert first.status_code == 200
    assert second.status_code == 409


def test_users_me_requires_auth(client: TestClient) -> None:
    response = client.get("/api/users/me")
    assert response.status_code == 401


def test_providers_invalid_bbox_returns_400(client: TestClient) -> None:
    response = client.get("/api/providers?bbox=not,a,bbox")
    assert response.status_code == 400
    assert "bbox" in response.json()["detail"]


def test_estimate_contract_accepts_bundle_and_scenario(client: TestClient) -> None:
    payload = {
        "intake": {
            "zip": "02118",
            "insurance_carrier": "Blue Cross Blue Shield of Massachusetts",
            "care_focus": "Gastroenterology",
            "deductible_cents": 200000,
            "oop_max_cents": 800000,
            "coinsurance_pct": 20,
            "copay_cents": 2500,
        },
        "bundle_id": "colonoscopy_screening",
        "scenario_id": "colonoscopy_screening",
    }
    response = client.post("/api/estimate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["bundle_id"] == "colonoscopy_screening"
    assert body["scenario_id"] == "colonoscopy_screening"
    assert len(body["estimates"]) > 0
