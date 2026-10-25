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
from app.quote import contracts as q
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


PLACEHOLDERS = {"allow_placeholders": True}

# Sources the fixtures cite that are not in data/etl/sources.yaml + sources.d/ yet. Each one is a
# README-listed placeholder; a new unregistered id fails test_fixture_sources_are_registered.
UNREGISTERED_SOURCES = {
    "bcbs_ma_tic_hmo": "placeholder BCBS TiC group rate (research-v3/pro-fees.md), sha 000...",
    "cms_pfs_rvu26a": "Medicare PFS RVU26A; its format is added with the A3 reader (P3)",
    "afc_watertown_self_pay": "AFC posted page; its format is added with the A3 reader (P3)",
}


def _validate(model: str, body: dict):
    ctx = dict(PLACEHOLDERS)
    if model == "ChatResponse":
        from tests.contracts.chat_ctx import fixture_context

        ctx = fixture_context(body)
    return ROOT_MODELS[model].model_validate(body, context=ctx)


def _validated(name: str):
    model, body = _load(FIX / f"{name}.json")
    return _validate(model, body)


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
    _validate(model, body)


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
    site_ids = {s["id"] for s in json.loads((FIX / "sites.json").read_text())["sites"]}
    for key in ("site_id",):
        for sid in _walk(body, key):
            assert sid in site_ids, f"unknown site {sid} (not in fixtures/sites.json)"


def test_fixture_sources_are_registered():
    from app.etl.config import load_sources

    registered = {s.source_id for s in load_sources().sources}
    used = set()
    for name in ("quote_bcbs_hmo_shoulder", "quote_cash_shoulder", "quote_medicare_shoulder"):
        used |= set(_validated(name).sources)
    assert used - registered == set(UNREGISTERED_SOURCES)


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
                # P11: the line says what its likelihood rests on, derived from the step
                assert ln.tier_basis == q.tier_basis_for_rating(st.appropriateness.rating), (
                    name,
                    ln.line_id,
                )


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
    fresh = [f.freshness for qr in quotes for f in qr.sources.values()]
    # (a) publisher late without (b), (b) we are stale without (a), and current
    assert any(f.late_to_refresh and not f.stale_on_our_side for f in fresh)
    assert any(f.stale_on_our_side and not f.late_to_refresh for f in fresh)
    assert any(not f.late_to_refresh and not f.stale_on_our_side for f in fresh)
    assert any(ln.unit == "per_15_minutes" for ln in lines)
    assert any(ln.list_price is not None for ln in lines)
    assert {ln.tier_basis for ln in lines} >= {"guideline", "plan_rule", "our_judgment"}
    assert any(
        sq.receipt.totals.you_pay.kind == "copay_or_deductible" for qr in quotes for sq in qr.sites
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


def test_hospital_files_use_the_365_day_rule():
    """Austin 2026-10-24: a hospital MRF is late only >365 days after its own last-updated date.
    MGB's 2026-03-27 file is therefore not late on 2026-10-24 (the old 180-day rule said it was)."""
    resp = _validated("quote_bcbs_hmo_shoulder")
    f = resp.sources["brigham_mrf"].freshness
    assert f.source_rule == "hospital_mrf_365_days" and str(f.last_updated) == "2026-03-27"
    assert str(f.expected_by) == "2027-03-27" and not f.late_to_refresh
    assert not f.stale_on_our_side and f.our_rule == "hospital_monthly"


def test_committed_sites_yaml_matches_contract_when_present():
    """Stream A3 writes data/sites/sites.yaml; once it exists it must validate."""
    p = REPO / "data" / "sites" / "sites.yaml"
    if not p.exists():
        pytest.skip("data/sites/sites.yaml not written yet (stream A3)")
    ROOT_MODELS["SitesFile"].model_validate(yaml.safe_load(p.read_text()))


# --------------------------------------------------------------------------- numbers vs the build


def _extract() -> dict[str, dict]:
    import csv

    with (FIX / "rate_row_extract.csv").open() as f:
        return {r["row_ref"]: r for r in csv.DictReader(f)}


def _num(v: str) -> float | None:
    return None if v == "" else float(v)


_BASIS_COLUMN = {"negotiated": "amount", "discounted_cash": "discounted_cash", "gross": "gross"}


def _payer_ok(r: dict, payment) -> bool:
    """Would this row price the person's payment? (the lookup a 'not published' claim denies)"""
    if payment.kind == "cash":
        return r["row_kind"] == "chargemaster"
    if payment.kind == "medicare":
        return r["payer_id"] == "MEDICARE"
    if payment.kind == "masshealth":
        return r["payer_id"] == "MASSHEALTH"
    return (
        r["payer_id"] == payment.payer_id
        and r["line_of_business"] in ("commercial", "unknown")
        and (r["product"] == "" or payment.product in r["product"].split("/"))
    )


def test_fixture_numbers_match_the_build():
    """Theater F4: every hospital-MRF number in a quote fixture is the cited row's number, for
    the line's code and modifier and the payment's payer; every 'not published' / 'percent only'
    claim survives re-running the lookup. Extract: tests/contracts/make_rate_row_extract.py."""
    rows = _extract()
    for name in ("quote_bcbs_hmo_shoulder", "quote_cash_shoulder", "quote_medicare_shoulder"):
        resp = _validated(name)
        for sq in resp.sites:
            for ln in sq.receipt.lines:
                cells = [ln.cell, ln.list_price, *(e.cell for e in ln.elsewhere)]
                moneys = []
                for c in cells:
                    if isinstance(c, etl.Money):
                        moneys.append(c)
                    elif isinstance(c, etl.Conflict):
                        moneys += [c.a, c.b]
                for m in moneys:
                    if m.prov.source_kind != "hospital_mrf":
                        continue
                    r = rows[m.prov.row_ref]
                    where = (name, sq.site.site_id, ln.line_id)
                    assert m.low == m.high == _num(r[_BASIS_COLUMN[m.basis.value]]), where
                    assert r["code"] in ln.codes, where
                    assert r["modifiers"] == (ln.modifier or ""), where
                    assert m.prov.payer_id == (r["payer_id"] or None), where
                    assert m.prov.source_sha256.startswith(m.prov.row_ref.split(":")[1]), where
                c = ln.cell
                if isinstance(
                    c, (etl.NotPublished, etl.PercentOnly)
                ) and c.searched.source_id.endswith("_mrf"):
                    cands = [
                        r
                        for r in rows.values()
                        if r["source_id"] == c.searched.source_id
                        and r["code"] in ln.codes
                        and r["modifiers"] == (ln.modifier or "")
                        and r["excluded"] == "0"
                        and _payer_ok(r, resp.payment)
                    ]
                    col = "discounted_cash" if resp.payment.kind == "cash" else "amount"
                    dollars = [r for r in cands if r[col] != ""]
                    assert not dollars, (
                        name,
                        ln.line_id,
                        "has a dollar row",
                        dollars[0]["row_ref"],
                    )
                    if isinstance(c, etl.PercentOnly):
                        assert any(_num(r["negotiated_pct"]) == c.pct for r in cands), ln.line_id
        for sq in resp.sites:
            for o in sq.other_payers:
                for p in o.points:
                    if p.money.prov.source_kind == "hospital_mrf":
                        r = rows[p.money.prov.row_ref]
                        assert r["code"] == o.code and p.money.low == _num(r["amount"]), o.line_id
