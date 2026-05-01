"""Unit tests for the legacy wide-format flattening shim."""

from app.services.hospital_legacy import flatten_to_legacy


def _make_normalized(**overrides):
    base = {
        "hospital_id": "bmc",
        "cpt": "45378",
        "cpt_desc": "Colonoscopy",
        "gross_charge": 12500.0,
        "discounted_cash": 8000.0,
        "de_identified_min": 3000.0,
        "de_identified_max": 15000.0,
        "billing_class": "professional",
        "setting": "outpatient",
        "rate_methodology": "fee schedule",
        "payer_rates": [],
        "benchmarks": [],
    }
    base.update(overrides)
    return base


def test_flatten_preserves_all_fields():
    norm = _make_normalized(
        payer_rates=[
            {"payer_id": "BCBS_MA", "negotiated_rate": 4200.0, "plan_name": "PPO",
             "source": "mrf_bmc", "source_origin": "mrf", "billing_class": "professional"},
            {"payer_id": "AETNA", "negotiated_rate": 3800.0, "plan_name": "HMO",
             "source": "mrf_bmc", "source_origin": "mrf", "billing_class": "professional"},
        ],
        benchmarks=[
            {"benchmark_source": "turquoise", "component": "total",
             "price": 5100.0, "quality_rating": 4.2},
            {"benchmark_source": "fair_health", "component": "physician_in_network",
             "price": 1200.0, "quality_rating": None},
        ],
    )
    d = flatten_to_legacy(norm)
    assert d["bcbs_price"] == 4200.0
    assert d["bcbs_source"] == "mrf_bmc"
    assert d["bcbs_plan"] == "PPO"
    assert d["aetna_price"] == 3800.0
    assert d["turquoise_bundled_price"] == 5100.0
    assert d["turquoise_quality_rating"] == 4.2
    assert d["fh_physician_in_network"] == 1200.0
    assert d["gross_charge"] == 12500.0
    assert d["cpt"] == "45378"


def test_flatten_missing_payer():
    norm = _make_normalized()
    d = flatten_to_legacy(norm)
    assert d["bcbs_price"] is None
    assert d["aetna_price"] is None
    assert d["harvard_pilgrim_price"] is None
    assert d["uhc_price"] is None
    assert d["bcbs_source"] == ""
    assert d["bcbs_tic_rate"] is None


def test_flatten_tic_cross_validation():
    norm = _make_normalized(
        payer_rates=[
            {"payer_id": "BCBS_MA", "negotiated_rate": 4200.0, "plan_name": "PPO",
             "source": "mrf_bmc", "source_origin": "mrf", "billing_class": "professional"},
            {"payer_id": "BCBS_MA", "negotiated_rate": 4100.0, "plan_name": "",
             "source": "", "source_origin": "tic", "billing_class": "institutional"},
        ],
    )
    d = flatten_to_legacy(norm)
    assert d["bcbs_price"] == 4200.0
    assert d["bcbs_tic_rate"] == 4100.0
    assert d["bcbs_tic_billing_class"] == "institutional"


def test_flatten_uhc_source_plan_mapping():
    norm = _make_normalized(
        payer_rates=[
            {"payer_id": "UHC", "negotiated_rate": 5000.0, "plan_name": "Choice Plus",
             "source": "mrf_bmc", "source_origin": "mrf", "billing_class": "professional"},
        ],
    )
    d = flatten_to_legacy(norm)
    assert d["uhc_price"] == 5000.0
    assert d["uhc_source"] == "mrf_bmc"
