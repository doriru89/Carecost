"""Insurance dropdown options derived from hospital_rates (PostgreSQL)."""

from app.db.tables import HospitalRate
from app.services.insurance_options import build_insurance_options


def test_insurance_options_empty_collection(db_session):
    out = build_insurance_options(db_session)
    assert out["insurers"] == []
    assert out["bcbs_plan_options"] == []
    assert out["plan_options_by_insurer"] == {}


def test_insurance_options_from_rates(db_session):
    db_session.add_all(
        [
            HospitalRate(
                id="bmc:45378",
                hospital_id="bmc",
                cpt="45378",
                bcbs_price=100.0,
                aetna_price=200.0,
                bcbs_plan=" HMO Blue ",
                aetna_plan="Open Access",
                source="test",
            ),
            HospitalRate(
                id="bmc:45380",
                hospital_id="bmc",
                cpt="45380",
                harvard_pilgrim_price=50.0,
                uhc_price=75.0,
                bcbs_plan="PPO Blue",
                aetna_plan="Managed Choice",
                uhc_source="Choice Plus",
                source="test",
            ),
        ]
    )
    db_session.commit()

    out = build_insurance_options(db_session)
    keys = {i["key"] for i in out["insurers"]}
    assert keys == {"bcbs", "aetna", "harvard_pilgrim", "uhc"}
    assert out["bcbs_plan_options"] == ["HMO Blue", "PPO Blue"]
    assert out["plan_options_by_insurer"]["bcbs"] == ["HMO Blue", "PPO Blue"]
    assert out["plan_options_by_insurer"]["aetna"] == ["Managed Choice", "Open Access"]
    assert out["plan_options_by_insurer"]["harvard_pilgrim"] == []
    assert out["plan_options_by_insurer"]["uhc"] == ["Choice Plus"]
