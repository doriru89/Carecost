"""A5 item 3 (R7, P9): billing type through the health system's public structure."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.sites import billing

REPO = Path(__file__).resolve().parents[3]
META = {"file_date": "2026-09-08", "sha256": "163b9697" * 8}


def _site(name, street, zipc, system="mgb", src="", npis=()):
    return {"id": "x", "census_id": "GB9999", "name": name, "system_id": system,
            "address": {"street": street, "zip": zipc}, "billing_type": "unknown",
            "billing_type_source": src, "type_2_npis": list(npis)}  # fmt: skip


def _dph(*rows):
    out: dict = {}
    for t, i, n, st, z in rows:
        out.setdefault(billing.akey(st, z), []).append(
            {"type": t, "id": i, "name": n, "street": st, "city": "", "zip": z}
        )
    return out


def test_main_campus_licence_of_own_system_makes_it_hospital_outpatient():
    s = _site("BRIGHAM AND WOMENS PHYSICIANS ORGANIZATION INC", "75 FRANCIS ST", "02115")
    d = billing.decide(s, _dph(("Acute Hospital", "2341", "BRIGHAM AND WOMEN'S HOSPITAL",
                                "75 FRANCIS STREET", "02115")), META, {})  # fmt: skip
    assert d["billing_type"] == "hospital_outpatient" and d["rules"] == ["dph_hospital_campus"]
    assert "2341" in d["source"] and "2026-09-08" in d["source"]


def test_satellite_needs_the_site_to_be_that_department():
    dph = _dph(("Hospital Satellite", "21Y1", "SPAULDING OUTPATIENT CTR - WELLESLE",
                "65 WALNUT STREET", "02481"))  # fmt: skip
    private = billing.decide(
        _site("DERMATOLOGY PARTNERS INC", "65 WALNUT ST", "02481"), dph, META, {}
    )
    assert private["billing_type"] == "unknown"
    assert any("not named as this licensed location" in e for e in private["evidence_seen"])
    dept = billing.decide(_site("Spaulding Outpatient Center Wellesley", "65 Walnut St", "02481"),
                          dph, META, {})  # fmt: skip
    assert dept["billing_type"] == "hospital_outpatient"


def test_another_systems_licence_never_decides():
    s = _site("BMC AFFILIATED PHYSICIANS", "736 CAMBRIDGE ST", "02135", system="bmc")
    d = billing.decide(s, _dph(("Hospital Satellite", "9", "DANA-FARBER AT ST ELIZABETH",
                                "736 CAMBRIDGE STREET", "02135")), META, {})  # fmt: skip
    assert d["billing_type"] == "unknown"


def test_rpo_no_for_the_sites_own_location_is_office_and_conflicts_stay_unknown():
    src = "HPC RPO 2024: provider-based status NO (Mass General Imaging Chelsea)"
    s = _site("Mass General Imaging Chelsea", "80 EVERETT AVE", "02150", src=src)
    assert billing.decide(s, {}, META, {})["billing_type"] == "office_visit"
    both = billing.decide(s, _dph(("Hospital Satellite", "1", "MGH IMAGING CHELSEA",
                                   "80 EVERETT AVE", "02150")), META, {})  # fmt: skip
    assert both["billing_type"] == "unknown" and both["reason"].startswith("rules disagree")


def test_hospital_npi_of_own_system():
    n = {"1992737761": {"name": "NEWTON-WELLESLEY HOSPITAL", "taxonomy": "282N00000X",
                        "taxonomy_desc": "General Acute Care Hospital", "street": "", "zip": ""}}  # fmt: skip
    s = _site("Newton-Wellesley Outpatient Surgery Center", "25 Washington St", "02481",
              npis=["1992737761"])  # fmt: skip
    assert billing.decide(s, {}, META, n)["rules"] == ["nppes_hospital_npi"]


def test_committed_registry_applies_the_structure_file():
    doc = billing.load()
    sites = yaml.safe_load((REPO / "data" / "sites" / "sites.yaml").read_text())["sites"]
    todo = yaml.safe_load((REPO / "data" / "sites" / "to_verify.yaml").read_text())
    by = {s.get("census_id"): s for s in sites}
    assert doc["counts"]["unknown_in"] == doc["counts"]["resolved"] + doc["counts"]["to_verify"]
    for cid, r in doc["resolved"].items():
        assert by[cid]["billing_type"] == r["billing_type"]
        assert by[cid]["billing_type_source"].startswith("+".join(r["rules"]))
    unknown = {s["census_id"] for s in sites if s["billing_type"] == "unknown"}
    listed = {b["census_id"] for b in todo["billing_to_verify"]}
    assert unknown == listed == set(doc["to_verify"])
