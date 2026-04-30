"""TDD tests for rate_normalizer — written BEFORE implementation."""

from app.etl.types import NormalizedRecord, RawMrfRecord, RawTicRecord


def _make_mrf(hospital_name="Massachusetts General Hospital", cpt="45378",
              payer_raw="BLUE CROSS BLUE SHIELD OF MA", **kwargs):
    defaults = dict(
        hospital_name=hospital_name, cpt=cpt, cpt_desc="Colonoscopy",
        description="HC COLONOSCOPY", payer_raw=payer_raw, plan="HMO Blue",
        setting="outpatient", gross=3883.0, cash=2912.0,
        negotiated_dollar=3411.0, estimated_amount=None,
        de_id_min=2200.0, de_id_max=5500.0, billing_class="institutional",
        source_file="mgh_charges.zip", mrf_format="standard_csv",
    )
    defaults.update(kwargs)
    return RawMrfRecord(**defaults)


def _make_tic(hospital_name="Massachusetts General Hospital", cpt="45378",
              insurer_key="bcbs", **kwargs):
    defaults = dict(
        hospital_name=hospital_name, matched_npi="1023049236", cpt=cpt,
        cpt_desc="Colonoscopy", negotiated_rate=487.50,
        negotiated_type="negotiated", billing_class="professional",
        setting="office", plan="HMO Blue", insurer_key=insurer_key,
        source_file="bcbs_tic.json.gz",
    )
    defaults.update(kwargs)
    return RawTicRecord(**defaults)


class TestNormalizePayer:
    def test_bcbs_full_name(self):
        from app.etl.rate_normalizer import normalize_payer_name
        payer_id, include = normalize_payer_name("BLUE CROSS BLUE SHIELD OF MA")
        assert payer_id == "BCBS_MA"
        assert include is True

    def test_bcbs_abbreviation(self):
        from app.etl.rate_normalizer import normalize_payer_name
        payer_id, _ = normalize_payer_name("BCBS MA")
        assert payer_id == "BCBS_MA"

    def test_aetna(self):
        from app.etl.rate_normalizer import normalize_payer_name
        payer_id, _ = normalize_payer_name("Aetna Choice POS II")
        assert payer_id == "AETNA"

    def test_harvard_pilgrim(self):
        from app.etl.rate_normalizer import normalize_payer_name
        payer_id, _ = normalize_payer_name("Harvard Pilgrim Health Care")
        assert payer_id == "HARVARD_PILGRIM"

    def test_uhc(self):
        from app.etl.rate_normalizer import normalize_payer_name
        payer_id, _ = normalize_payer_name("UnitedHealthcare Choice Plus")
        assert payer_id == "UHC"

    def test_non_canonical_excluded(self):
        from app.etl.rate_normalizer import normalize_payer_name
        payer_id, include = normalize_payer_name("Cigna")
        assert payer_id is None
        assert include is False

    def test_medicare_included(self):
        from app.etl.rate_normalizer import normalize_payer_name
        payer_id, include = normalize_payer_name("Medicare")
        assert payer_id is None
        assert include is True

    def test_cash_included(self):
        from app.etl.rate_normalizer import normalize_payer_name
        payer_id, include = normalize_payer_name("Cash/Self-Pay")
        assert payer_id is None
        assert include is True

    def test_unknown_payer_returns_none(self):
        from app.etl.rate_normalizer import normalize_payer_name
        payer_id, include = normalize_payer_name("Some Random Insurer ABC")
        assert payer_id is None
        assert include is False


class TestNormalizeHospital:
    def test_by_source_alias_tic(self):
        from app.etl.rate_normalizer import normalize_hospital_name
        hid = normalize_hospital_name("Brigham and Women's Hospital", "tic")
        assert hid == "brigham"

    def test_by_source_alias_masscomparecare(self):
        from app.etl.rate_normalizer import normalize_hospital_name
        hid = normalize_hospital_name("Brigham & Womens Hospital, Inc.", "masscomparecare")
        assert hid == "brigham"

    def test_by_exact_name(self):
        from app.etl.rate_normalizer import normalize_hospital_name
        hid = normalize_hospital_name("Massachusetts General Hospital", "mrf")
        assert hid == "mgh"

    def test_unknown_hospital(self):
        from app.etl.rate_normalizer import normalize_hospital_name
        hid = normalize_hospital_name("Random Hospital XYZ", "mrf")
        assert hid is None

    def test_cha_primary_name(self):
        from app.etl.rate_normalizer import normalize_hospital_name
        hid = normalize_hospital_name("CHA Cambridge Hospital", "tic")
        assert hid == "cha"


class TestNormalizeRecords:
    def test_mrf_records_normalized(self):
        from app.etl.rate_normalizer import normalize_records
        records = [_make_mrf()]
        result = normalize_records(records)
        assert len(result) == 1
        assert result[0].hospital_id == "mgh"
        assert result[0].payer_id == "BCBS_MA"
        assert result[0].source_origin == "mrf"

    def test_tic_records_normalized(self):
        from app.etl.rate_normalizer import normalize_records
        records = [_make_tic()]
        result = normalize_records(records)
        assert len(result) == 1
        assert result[0].hospital_id == "mgh"
        assert result[0].source_origin == "tic"

    def test_unknown_hospital_dropped(self):
        from app.etl.rate_normalizer import normalize_records
        records = [_make_mrf(hospital_name="Unknown Hospital")]
        result = normalize_records(records)
        assert len(result) == 0

    def test_preserves_payer_raw(self):
        from app.etl.rate_normalizer import normalize_records
        records = [_make_mrf(payer_raw="BLUE CROSS BLUE SHIELD OF MA")]
        result = normalize_records(records)
        assert result[0].payer_raw == "BLUE CROSS BLUE SHIELD OF MA"

    def test_mixed_mrf_and_tic(self):
        from app.etl.rate_normalizer import normalize_records
        records = [_make_mrf(), _make_tic()]
        result = normalize_records(records)
        assert len(result) == 2
        origins = {r.source_origin for r in result}
        assert origins == {"mrf", "tic"}
