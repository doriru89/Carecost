"""contracts/fixtures/*.json: each validates against its contract, points at real registry ids,
and together they cover every tier, every Gap kind, a Money range, a per-NPI breakdown, an
AI-suggested line and a 'late to refresh' source (per line and per site).

Validation goes through the pydantic models the schemas are generated from; the drift test in
test_api_contracts.py keeps model and committed schema identical, so this is schema validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.api_contracts import ROOT_MODELS
from app.care_paths.loader import load_paths
from app.etl import contracts as etl
from app.registries import all_hospitals

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "contracts" / "fixtures"
FILES = sorted(FIX.glob("*.json"))
PATHS = load_paths()
PAYERS = yaml.safe_load((REPO / "data" / "etl" / "payer_aliases.yaml").read_text())
QUESTIONS = {
    q["id"]: q
    for q in yaml.safe_load((REPO / "data" / "questions" / "questions.yaml").read_text())[
        "questions"
    ]
}
CARDS = {
    c["id"]
    for c in yaml.safe_load((REPO / "data" / "questions" / "questions.yaml").read_text())["cards"]
}
REDFLAGS = json.loads((REPO / "data" / "redflags" / "redflags.json").read_text())
GLOSSARY = set(
    yaml.safe_load((REPO / "content" / "glossary" / "glossary.yaml").read_text())["terms"]
)

REQUIRED = {
    "quote_bcbs_hmo_shoulder",
    "quote_cash_shoulder",
    "quote_medicare_shoulder",
    "chat_red_flag",
    "chat_clarify",
    "chat_ai_paused",
    "catalog",
}


def _load(p: Path) -> tuple[str, dict]:
    doc = json.loads(p.read_text())
    assert doc.pop("_fixture") is True, f"{p.name}: every fixture is marked _fixture: true"
    return doc.pop("_schema"), doc


def _validated(name: str):
    model, body = _load(FIX / f"{name}.json")
    return ROOT_MODELS[model].model_validate(body)


def _walk(obj, key):
    """Every value under `key` anywhere in a JSON tree."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)


def test_required_fixtures_exist():
    assert REQUIRED <= {p.stem for p in FILES}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_fixture_validates_against_its_contract(path):
    model, body = _load(path)
    assert model in ROOT_MODELS, f"{path.name}: _schema must name a contract root model"
    ROOT_MODELS[model].model_validate(body)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_fixture_ids_resolve_against_registries(path):
    _, body = _load(path)
    for pid in [*_walk(body, "payer_id")]:
        if pid is not None:
            assert pid in PAYERS["payers"], f"unknown payer_id {pid}"
    for prod in _walk(body, "product"):
        if prod is not None:
            assert prod in PAYERS["products"], f"unknown product {prod}"
    for key in ("care_path_id", "path_id"):
        for pid in _walk(body, key):
            if pid is not None:
                assert pid in PATHS, f"unknown care path {pid}"
    for answers in _walk(body, "answers"):
        if isinstance(answers, dict):
            for qid, vals in answers.items():
                assert set(vals) <= {a["value"] for a in QUESTIONS[qid]["answers"]}
    for ent in _walk(body, "hospital_entity_id"):
        if ent is not None:
            assert ent in all_hospitals()
    for keys in _walk(body, "glossary_keys"):
        assert set(keys) <= GLOSSARY
    for cards in _walk(body, "card_ids"):
        assert set(cards) <= CARDS


def test_quote_lines_match_the_care_path():
    """step ids exist in the path, and the line's likelihood is the step's likelihood_tier."""
    for name in ("quote_bcbs_hmo_shoulder", "quote_cash_shoulder", "quote_medicare_shoulder"):
        resp = _validated(name)
        steps = {s.id: s for s in PATHS[resp.care_path.id].steps}
        assert resp.care_path.review_status == PATHS[resp.care_path.id].review.status
        for sq in resp.sites:
            for ln in sq.receipt.lines:
                st = steps[ln.step_id]
                assert ln.likelihood == st.likelihood_tier, (name, ln.line_id)
                step_codes = st.all_codes()
                assert set(ln.codes) <= step_codes, (name, ln.line_id, ln.codes)
                if ln.ai_suggested:
                    assert set(ln.codes) <= {c.code for a in st.ai_potential for c in a.cpts}


def test_red_flag_copy_is_verbatim_from_redflags_json():
    reply = _validated("chat_red_flag").reply
    disp = {d["id"]: d for d in REDFLAGS["dispositions"]}[reply.disposition]
    assert reply.headline.model_dump() == disp["headline"]
    assert reply.text.model_dump() == disp["text"]
    flags = {f["id"]: f for f in REDFLAGS["flags"]}
    assert all(flags[f]["disposition"] == reply.disposition for f in reply.flag_ids)


def test_clarify_chips_are_verbatim_from_questions_yaml():
    reply = _validated("chat_clarify").reply
    for chip in reply.questions:
        src = QUESTIONS[chip.question_id]
        assert chip.text.model_dump() == src["text"]
        assert [(a.value, a.label.model_dump()) for a in chip.answers] == [
            (a["value"], a["label"]) for a in src["answers"]
        ]


def test_catalog_covers_every_care_path_and_its_primary_codes():
    cat = _validated("catalog")
    assert {p.id for p in cat.care_paths} == set(PATHS)
    listed = {(c.code, pid) for s in cat.services for c in s.codes for pid in s.care_paths}
    for pid, path in PATHS.items():
        for st in path.steps:
            for c in st.cpts:
                if c.role == "primary":
                    assert (c.code, pid) in listed, (pid, st.id, c.code)


def test_fixtures_together_cover_the_whole_contract():
    quotes = [
        _validated(n)
        for n in ("quote_bcbs_hmo_shoulder", "quote_cash_shoulder", "quote_medicare_shoulder")
    ]
    lines = [ln for qr in quotes for sq in qr.sites for ln in sq.receipt.lines]
    assert {ln.tier for ln in lines} == {"certain", "likely", "possible", "not_in_public_data"}
    kinds = {ln.cell.kind for ln in lines if ln.cell is not None}
    kinds |= {e.cell.kind for ln in lines for e in ln.elsewhere}
    assert {k.value for k in etl.GapKind} | {"money"} <= kinds
    assert any(
        ln.cell is not None and ln.cell.kind == "money" and ln.cell.low < ln.cell.high
        for ln in lines
    )
    assert any(ln.doctor_fee and ln.doctor_fee.by_npi for ln in lines)
    assert any(ln.ai_suggested for ln in lines)
    assert any(ln.availability == "not_offered" and ln.elsewhere for ln in lines)
    assert any(c.freshness.late_to_refresh for ln in lines for c in ln.sources), "per data point"
    assert any(not c.freshness.late_to_refresh for ln in lines for c in ln.sources)
    assert any(sq.site.price_freshness.late_to_refresh for qr in quotes for sq in qr.sites), (
        "per site"
    )
    assert any(sq.other_payers for qr in quotes for sq in qr.sites)
    assert {qr.payment.kind for qr in quotes} == {"insurance", "cash", "medicare"}
    assert {sq.site.billing_type for qr in quotes for sq in qr.sites} >= {
        "office_visit",
        "hospital_outpatient",
    }
    rungs = {ln.doctor_fee.rung for ln in lines if ln.doctor_fee}
    assert {2, 5, 7, None} <= rungs
    chats = {
        _validated(n).reply.kind
        for n in ("chat_red_flag", "chat_clarify", "chat_ai_paused", "chat_care_paths")
    }
    assert chats == {"red_flag", "clarify", "ai_paused", "care_paths"}


def test_mgb_late_to_refresh_shows_on_brigham():
    """Austin 2026-10-24: MGB data dated 2026-03-27 is shown, labelled late to refresh."""
    resp = _validated("quote_bcbs_hmo_shoulder")
    bwh = next(sq for sq in resp.sites if sq.site.site_id == "brigham_and_womens_hospital")
    f = bwh.site.price_freshness
    assert f.late_to_refresh and str(f.last_updated) == "2026-03-27" and f.expected_by is not None
    assert any(ln.cell is not None and ln.cell.kind == "money" for ln in bwh.receipt.lines), (
        "data still shown"
    )


def test_committed_sites_yaml_matches_contract_when_present():
    """Stream A3 writes data/sites/sites.yaml; once it exists it must validate."""
    p = REPO / "data" / "sites" / "sites.yaml"
    if not p.exists():
        pytest.skip("data/sites/sites.yaml not written yet (stream A3)")
    ROOT_MODELS["SitesFile"].model_validate(yaml.safe_load(p.read_text()))
