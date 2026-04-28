from app.services.confirmation_llm import validate_llm_confirm


def test_validate_llm_confirm_strips_bad_keys() -> None:
    out = validate_llm_confirm(
        {
            "missing_fields": ["zip"],
            "follow_up_questions": [{"id": "1", "text": "What ZIP?"}],
            "suggested_updates": {"zip": "02118", "evil": "x"},
        }
    )
    assert "evil" not in out.suggested_updates
    assert out.suggested_updates.get("zip") == "02118"
