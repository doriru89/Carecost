"""Generate pre-computed plan payment table.

For each plan × hospital × scenario, pre-compute:
  - scenario_a: OOP if deductible fully remaining (worst case)
  - scenario_b: OOP if deductible fully met (best case)

Usage:
    cd backend && uv run python ../scripts/generate_payment_table.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# Add backend to path for imports
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.plan_rules import estimate_patient_cost_cents
from app.services.specialty_config import SPECIALTY_CONFIG

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "az-data"
PIPELINE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "hospital_mrfs"

PLAN_CONFIGS_PATH = PIPELINE_DIR / "plan_configs.json"
GI_CSV = DATA_DIR / "hospital_rates_clean.csv"
DERM_CSV = DATA_DIR / "hospital_rates_derm.csv"
OUTPUT = DATA_DIR / "plan_payment_table.json"

# Map plan carrier key to CSV column name
CARRIER_TO_FIELD = {
    "bcbs": "bcbs_price",
    "aetna": "aetna_price",
    "harvard_pilgrim": "harvard_pilgrim_price",
    "uhc": "uhc_price",
}

CARRIER_KEY_FROM_PAYER = {
    "Blue Cross Blue Shield of Massachusetts": "bcbs",
    "Aetna": "aetna",
    "Harvard Pilgrim Health Care": "harvard_pilgrim",
    "UnitedHealthcare": "uhc",
}

CARRIER_LABEL = {
    "bcbs": "BCBS",
    "aetna": "Aetna",
    "harvard_pilgrim": "Harvard Pilgrim",
    "uhc": "UHC",
}


def _parse_float(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _dollars_to_cents(x: float | None) -> int | None:
    return int(round(x * 100)) if x is not None else None


def load_plan_configs() -> list[dict]:
    data = json.loads(PLAN_CONFIGS_PATH.read_text())
    return data["plans"]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_scenario_to_cpt(specialty: str) -> dict[str, str]:
    """Map scenario_id → CPT code for a specialty."""
    config = SPECIALTY_CONFIG[specialty]
    return dict(config["bundle_cpt"])


def detect_specialty_for_cpt(cpt: str) -> str | None:
    for specialty, config in SPECIALTY_CONFIG.items():
        if cpt in config["bundle_cpt"].values():
            return specialty
    return None


def generate():
    plans = load_plan_configs()
    gi_rows = load_csv(GI_CSV)
    derm_rows = load_csv(DERM_CSV)
    all_rows = gi_rows + derm_rows

    # Build reverse map: CPT → list of scenario_ids (a CPT can appear in multiple scenarios)
    cpt_to_scenarios: dict[str, list[tuple[str, str]]] = {}  # cpt → [(scenario_id, specialty)]
    for specialty, config in SPECIALTY_CONFIG.items():
        for scenario_id, cpt in config["bundle_cpt"].items():
            cpt_to_scenarios.setdefault(cpt, []).append((scenario_id, specialty))

    table = []
    seen_keys = set()

    for plan in plans:
        carrier_key = CARRIER_KEY_FROM_PAYER.get(plan["payer"], "")
        if not carrier_key:
            continue
        price_field = CARRIER_TO_FIELD.get(carrier_key, "")
        if not price_field:
            continue

        for row in all_rows:
            cpt = row["cpt"].strip()
            hospital_id = row["hospital_id"].strip()

            scenarios = cpt_to_scenarios.get(cpt, [])
            if not scenarios:
                continue

            # Get negotiated rate for this payer
            rate_dollars = _parse_float(row.get(price_field, ""))
            rate_cents = _dollars_to_cents(rate_dollars)

            # FAIR Health benchmarks
            fh_physician = _parse_float(row.get("fh_physician_in_network", ""))
            fh_facility = _parse_float(row.get("fh_facility_hosp_in_network", ""))
            fh_anesthesia = _parse_float(row.get("fh_anesthesia_in_network", ""))
            fh_pathology = _parse_float(row.get("fh_pathology_in_network", ""))

            # Determine data completeness
            if rate_cents is not None:
                data_completeness = "full"
                effective_rate_cents = rate_cents
            elif fh_physician is not None and fh_facility is not None:
                data_completeness = "benchmark_only"
                effective_rate_cents = _dollars_to_cents(fh_physician + fh_facility)
            else:
                data_completeness = "no_data"
                effective_rate_cents = None

            for scenario_id, specialty in scenarios:
                key = f"{plan['id']}:{hospital_id}:{scenario_id}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                # Compute OOP for both scenarios
                if effective_rate_cents is not None:
                    result = estimate_patient_cost_cents(
                        effective_rate_cents,
                        plan,
                        scenario_id=scenario_id,
                        cpt_code=cpt,
                    )
                    scenario_a = result["scenario_a"]
                    scenario_b = result["scenario_b"]
                    rule_type = result["rule_type"]
                    rule_summary = result["summary"]
                    note = result.get("note", "")
                else:
                    scenario_a = None
                    scenario_b = None
                    rule_type = "unknown"
                    rule_summary = "No price data available"
                    note = (
                        "No negotiated rate or benchmark available for this payer at this hospital."
                    )

                table.append(
                    {
                        "key": key,
                        "plan_id": plan["id"],
                        "plan_name": plan["plan_name"],
                        "payer": CARRIER_LABEL.get(carrier_key, carrier_key),
                        "hospital_id": hospital_id,
                        "hospital_name": row.get("hospital_name", "").strip(),
                        "scenario_id": scenario_id,
                        "cpt": cpt,
                        "cpt_desc": row.get("cpt_desc", "").strip(),
                        "specialty": specialty,
                        "negotiated_rate_cents": rate_cents,
                        "rule_type": rule_type,
                        "scenario_a_cents": scenario_a,
                        "scenario_b_cents": scenario_b,
                        "rule_summary": rule_summary,
                        "note": note,
                        "plan_deductible_cents": plan["deductible_individual"] * 100,
                        "plan_coinsurance_pct": int(plan["coinsurance_in_network"] * 100),
                        "plan_copay_specialist_cents": plan["copay_specialist"] * 100,
                        "plan_oop_max_cents": plan["oop_max_individual"] * 100,
                        "fh_physician_in_network": fh_physician,
                        "fh_anesthesia_in_network": fh_anesthesia,
                        "fh_facility_hosp_in_network": fh_facility,
                        "fh_pathology_in_network": fh_pathology,
                        "data_completeness": data_completeness,
                        "billing_class": row.get("billing_class", "unknown").strip(),
                    }
                )

    # Sort for stable output
    table.sort(key=lambda r: r["key"])

    OUTPUT.write_text(json.dumps(table, indent=2))
    print(f"Generated {len(table)} rows to {OUTPUT}")
    print(f"  Size: {OUTPUT.stat().st_size / 1024:.0f} KB")

    # Summary
    by_completeness = {}
    for r in table:
        dc = r["data_completeness"]
        by_completeness[dc] = by_completeness.get(dc, 0) + 1
    print(f"  Data completeness: {by_completeness}")

    by_rule = {}
    for r in table:
        rt = r["rule_type"]
        by_rule[rt] = by_rule.get(rt, 0) + 1
    print(f"  Rule types: {by_rule}")

    # Spot checks
    for check_key, expected_a, expected_b in [
        ("bcbs_ppo:bmc:colonoscopy_screening", 0, 0),
        ("bcbs_hmo:bmc:derm_office_visit_detailed", 4000, 4000),
    ]:
        match = next((r for r in table if r["key"] == check_key), None)
        if match:
            ok_a = match["scenario_a_cents"] == expected_a
            ok_b = match["scenario_b_cents"] == expected_b
            status = "PASS" if (ok_a and ok_b) else "FAIL"
            print(
                f"  Check {check_key}: a={match['scenario_a_cents']} b={match['scenario_b_cents']} [{status}]"
            )
        else:
            print(f"  Check {check_key}: NOT FOUND")


if __name__ == "__main__":
    generate()
