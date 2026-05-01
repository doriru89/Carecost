"""Insurance dropdown options derived from HospitalPayerRate (normalized)."""

from app.db.tables import HospitalPayerRate
from app.services.insurance_options import build_insurance_options


def test_insurance_options_empty_collection(db_session):
    out = build_insurance_options(db_session)
    assert out["insurers"] == []
    assert out["bcbs_plan_options"] == []
    assert out["plan_options_by_insurer"] == {}


def test_insurance_options_from_rates(db_session):
    db_session.add_all(
        [
            HospitalPayerRate(
                hospital_id="bmc", cpt="45378", payer_id="BCBS_MA",
                negotiated_rate=100.0, plan_name="HMO Blue",
                source="test", source_origin="mrf", billing_class="", price_source="",
            ),
            HospitalPayerRate(
                hospital_id="bmc", cpt="45378", payer_id="AETNA",
                negotiated_rate=200.0, plan_name="Open Access",
                source="test", source_origin="mrf", billing_class="", price_source="",
            ),
            HospitalPayerRate(
                hospital_id="bmc", cpt="45380", payer_id="BCBS_MA",
                negotiated_rate=90.0, plan_name="PPO Blue",
                source="test", source_origin="mrf", billing_class="", price_source="",
            ),
            HospitalPayerRate(
                hospital_id="bmc", cpt="45380", payer_id="HARVARD_PILGRIM",
                negotiated_rate=50.0, plan_name="",
                source="test", source_origin="mrf", billing_class="", price_source="",
            ),
            HospitalPayerRate(
                hospital_id="bmc", cpt="45380", payer_id="UHC",
                negotiated_rate=75.0, plan_name="Choice Plus",
                source="test", source_origin="mrf", billing_class="", price_source="",
            ),
        ]
    )
    db_session.commit()

    out = build_insurance_options(db_session)
    keys = {i["key"] for i in out["insurers"]}
    assert keys == {"bcbs", "aetna", "harvard_pilgrim", "uhc"}
    assert out["bcbs_plan_options"] == ["HMO Blue", "PPO Blue"]
    assert out["plan_options_by_insurer"]["bcbs"] == ["HMO Blue", "PPO Blue"]
    assert out["plan_options_by_insurer"]["aetna"] == ["Open Access"]
    assert out["plan_options_by_insurer"]["harvard_pilgrim"] == []
    assert out["plan_options_by_insurer"]["uhc"] == ["Choice Plus"]
