from app.services.scenario_to_bundle import infer_scenario_id, scenario_to_bundle_id


def test_screening_keywords() -> None:
    sid = infer_scenario_id({"free_text": "routine screening colonoscopy"}, None)
    assert sid == "colonoscopy_screening"


def test_bundle_mapping() -> None:
    assert scenario_to_bundle_id("colonoscopy_diagnostic") == "colonoscopy_diagnostic"


def test_derm_scenario_returns_itself() -> None:
    assert scenario_to_bundle_id("derm_office_visit_detailed") == "derm_office_visit_detailed"


def test_unknown_scenario_returns_itself_not_gi_default() -> None:
    """Unknown scenario_id should pass through, not silently become colonoscopy_screening."""
    assert scenario_to_bundle_id("some_future_scenario") == "some_future_scenario"
    assert scenario_to_bundle_id("some_future_scenario") != "colonoscopy_screening"
