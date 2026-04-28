from app.services.scenario_to_bundle import infer_scenario_id, scenario_to_bundle_id


def test_screening_keywords() -> None:
    sid = infer_scenario_id({"free_text": "routine screening colonoscopy"}, None)
    assert sid == "colonoscopy_screening"


def test_bundle_mapping() -> None:
    assert scenario_to_bundle_id("colonoscopy_diagnostic") == "colonoscopy_diagnostic"
