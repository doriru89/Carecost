"""Confirm endpoint uses fake LLM when no API key."""

from fastapi.testclient import TestClient


def test_confirm_returns_questions(client: TestClient) -> None:
    r = client.post(
        "/api/confirm",
        json={"fields": {"zip": "02118", "insurance_carrier": "BCBS MA", "care_focus": "Gastroenterology"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert "missing_fields" in body
    assert isinstance(body["follow_up_questions"], list)
