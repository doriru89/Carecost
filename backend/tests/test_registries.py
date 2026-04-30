"""Registry validation tests — load all YAML, validate schemas, check cross-references."""

from app.registries import (
    all_bundle_ids,
    all_hospitals,
    all_payers,
    all_specialty_names,
    bundles_for_specialty,
    carrier_to_payer_id,
    default_payer_id,
    get_bundle,
    get_cpt_for_bundle,
    get_hospital,
    get_payer,
    get_specialty,
    hospital_id_by_name,
    infer_hospital_from_address,
    validate_all_registries,
)


def test_validate_all_registries():
    counts = validate_all_registries()
    assert counts["bundles"] >= 30
    assert counts["hospitals"] >= 12
    assert counts["payers"] >= 4
    assert counts["specialties"] >= 2


def test_cpt_egd_with_biopsy_is_43239():
    assert get_cpt_for_bundle("egd_with_biopsy") == "43239"


def test_cpt_gi_imaging_ct_is_74177():
    assert get_cpt_for_bundle("gi_imaging_ct") == "74177"


def test_bundles_for_gastroenterology():
    gi = bundles_for_specialty("Gastroenterology")
    assert "colonoscopy_screening" in gi
    assert "egd_with_biopsy" in gi
    assert "gi_imaging_ct" in gi
    assert all(b.specialty == "Gastroenterology" for b in gi.values())


def test_bundles_for_dermatology():
    derm = bundles_for_specialty("Dermatology")
    assert "skin_biopsy_punch" in derm
    assert "mohs_surgery_head_neck" in derm
    assert all(b.specialty == "Dermatology" for b in derm.values())


def test_hospital_lookup():
    h = get_hospital("mgh")
    assert h.name == "Massachusetts General Hospital"
    assert h.lat > 42


def test_hospital_id_by_name():
    assert hospital_id_by_name("Massachusetts General Hospital") == "mgh"
    assert hospital_id_by_name("Nonexistent") is None


def test_infer_hospital_from_address():
    assert infer_hospital_from_address("55 FRUIT ST", "Boston") == "Massachusetts General Hospital"
    assert infer_hospital_from_address("330 BROOKLINE AVE", "Boston") == "Beth Israel Deaconess Medical Center"
    assert infer_hospital_from_address("unknown", "nowhere") == ""


def test_payer_defaults():
    assert default_payer_id() == "BCBS_MA"
    p = get_payer("BCBS_MA")
    assert p.slug == "bcbs"
    assert p.is_default is True


def test_carrier_to_payer():
    assert carrier_to_payer_id("Blue Cross Blue Shield") == "BCBS_MA"
    assert carrier_to_payer_id("Aetna") == "AETNA"
    assert carrier_to_payer_id("Harvard Pilgrim") == "HARVARD_PILGRIM"
    assert carrier_to_payer_id("UnitedHealthcare") == "UHC"
    assert carrier_to_payer_id(None) == "BCBS_MA"
    assert carrier_to_payer_id("") == "BCBS_MA"


def test_specialty_config():
    gi = get_specialty("Gastroenterology")
    assert gi.taxonomy == "207RG0100X"
    assert gi.default_scenario == "gi_general"


def test_all_bundle_ids():
    ids = all_bundle_ids()
    assert len(ids) >= 30
    assert "egd_with_biopsy" in ids
    assert "skin_biopsy_punch" in ids
