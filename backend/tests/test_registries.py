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
    assert counts["bundles"] >= 29
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
    assert gi.default_scenario == "colonoscopy_screening"


def test_all_bundle_ids():
    ids = all_bundle_ids()
    assert len(ids) >= 29
    assert "egd_with_biopsy" in ids
    assert "skin_biopsy_punch" in ids


def test_no_gi_general_bundle():
    ids = all_bundle_ids()
    assert "gi_general" not in ids


def test_no_gi_general_in_payment_table():
    import json
    from pathlib import Path

    table = json.loads(
        (Path(__file__).resolve().parent.parent.parent / "data" / "seed" / "plan_payment_table.json").read_text()
    )
    gi_general_rows = [r for r in table if r.get("scenario_id") == "gi_general"]
    assert len(gi_general_rows) == 0, f"Found {len(gi_general_rows)} orphaned gi_general rows"


def test_hospital_npi_uniqueness():
    from app.registries import hospital_npi_map

    npi_map = hospital_npi_map()
    npis = list(npi_map.values())
    assert len(npis) == len(set(npis)), "Duplicate NPIs found"
    assert len(npis) >= 10


def test_source_name_aliases_valid_keys():
    valid_sources = {"tic", "turquoise", "masscomparecare", "mrf"}
    for hid, h in all_hospitals().items():
        if h.source_name_aliases:
            for key in h.source_name_aliases:
                assert key in valid_sources, f"{hid} has unknown source alias key: {key}"


def test_hospital_name_for_source():
    from app.registries import hospital_name_for_source

    assert hospital_name_for_source("mgh", "tic") == "Massachusetts General Hospital"
    assert hospital_name_for_source("mgh", "masscomparecare") == "Mass General Brigham Hospital"
    assert hospital_name_for_source("mgh", "nonexistent") is None


def test_etl_config_loads():
    from app.registries import load_etl_config

    config = load_etl_config()
    assert "gi" in config.cpt_extraction_sets
    assert len(config.cpt_extraction_sets["gi"]) >= 17
    assert "standard_csv" in config.mrf_formats
