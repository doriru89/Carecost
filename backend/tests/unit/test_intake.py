from app.services.intake import missing_required_fields, normalize_intake, validate_intake_payload


def test_missing_required_lists_zip_carrier_care_focus() -> None:
    n, miss = validate_intake_payload({})
    assert set(miss) == {"zip", "insurance_carrier", "care_focus"}


def test_normalize_strips_empty_strings() -> None:
    n = normalize_intake({"zip": "  02118  ", "insurance_carrier": ""})
    assert n["zip"] == "02118"
    assert "insurance_carrier" not in n
