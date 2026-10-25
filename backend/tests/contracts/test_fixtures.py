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
# P1: the BCBS and cash quotes are real engine output now, so only the hand-made Medicare quote's
# fee schedule is left.
UNREGISTERED_SOURCES = {
    "cms_pfs_rvu26a": "Medicare PFS RVU26A; its format is added with the A3 reader (P3)",
}
QUOTES = ("quote_bcbs_hmo_shoulder", "quote_cash_shoulder", "quote_medicare_shoulder")
REAL_QUOTES = ("quote_bcbs_hmo_shoulder", "quote_cash_shoulder")  # app.quote.fixtures_gen
HANDMADE = Path(__file__).resolve().parent / "handmade"  # the pre-P1 hand-made BCBS / cash quotes


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
    for name in QUOTES:
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


def _features(quotes) -> set[str]:
    """Contract shapes a set of quote fixtures shows (what the frontend can render from them)."""
    lines = [ln for qr in quotes for sq in qr.sites for ln in sq.receipt.lines]
    f = {f"tier:{ln.tier}" for ln in lines}
    kinds = {ln.cell.kind for ln in lines if ln.cell is not None}
    kinds |= {e.cell.kind for ln in lines for e in ln.elsewhere}
    f |= {f"cell:{k}" for k in kinds}
    if any(isinstance(ln.cell, etl.Money) and ln.cell.low < ln.cell.high for ln in lines):
        f.add("money_range")
    if any(ln.doctor_fee and ln.doctor_fee.by_npi for ln in lines):
        f.add("by_npi")
    if any(ln.ai_suggested for ln in lines):
        f.add("ai_suggested")
    if any(ln.availability == "not_offered" and ln.elsewhere for ln in lines):
        f.add("not_offered_elsewhere")
    fresh = [s.freshness for qr in quotes for s in qr.sources.values()]
    # (a) publisher late without (b), (b) we are stale without (a), and current
    if any(x.late_to_refresh and not x.stale_on_our_side for x in fresh):
        f.add("late_to_refresh")
    if any(x.stale_on_our_side and not x.late_to_refresh for x in fresh):
        f.add("stale_on_our_side")
    if any(not x.late_to_refresh and not x.stale_on_our_side for x in fresh):
        f.add("fresh_source")
    if any(ln.unit == "per_15_minutes" for ln in lines):
        f.add("per_15_minutes")
    if any(ln.list_price is not None for ln in lines):
        f.add("list_price")
    f |= {f"tier_basis:{ln.tier_basis}" for ln in lines}
    f |= {f"you_pay:{sq.receipt.totals.you_pay.kind}" for qr in quotes for sq in qr.sites}
    if any(sq.other_payers for qr in quotes for sq in qr.sites):
        f.add("other_payers")
    f |= {f"payment:{qr.payment.kind}" for qr in quotes}
    f |= {f"billing:{sq.site.billing_type}" for qr in quotes for sq in qr.sites}
    f |= {f"rung:{ln.doctor_fee.rung}" for ln in lines if ln.doctor_fee}
    return f


CONTRACT_FEATURES = {
    *(f"tier:{t}" for t in ("certain", "likely", "possible", "not_in_public_data")),
    *(f"cell:{k.value}" for k in etl.GapKind),
    "cell:money",
    "money_range",
    "by_npi",
    "ai_suggested",
    "not_offered_elsewhere",
    "late_to_refresh",
    "stale_on_our_side",
    "fresh_source",
    "per_15_minutes",
    "list_price",
    *(f"tier_basis:{b}" for b in ("guideline", "plan_rule", "our_judgment")),
    "you_pay:copay_or_deductible",
    "other_payers",
    *(f"payment:{p}" for p in ("insurance", "cash", "medicare")),
    "billing:office_visit",
    "billing:hospital_outpatient",
    *(f"rung:{r}" for r in (2, 5, 7, None)),
}

# Shapes the real P1 quotes cannot show yet, and why. Only the hand-made quotes in handmade/ show
# them (they stay the mutation base of the negative rule tests). When real data starts showing one,
# test_real_fixtures_cover_what_real_data_can fails: drop it from here.
NOT_IN_REAL_DATA = {
    "cell:percent_only": "no BCBS HMO / cash row of the 3 sites is percent-only for these codes",
    "by_npi": "a care-path quote never knows the doctor's NPI (D6 needs a picked doctor)",
    "not_offered_elsewhere": "sites.yaml has no offered-services list yet (A3); absence is "
    "not_published, never 'not offered'",
    "late_to_refresh": "no source of the 3 sites is past its publisher deadline on 2026-10-24",
    "stale_on_our_side": "every source was fetched 2026-10-24",
    "rung:7": "Medicare PFS (the rung-7 reference) is not loaded until A3",
}


def test_real_fixtures_cover_what_real_data_can():
    """The golden quotes in contracts/fixtures (real BCBS + cash, hand-made Medicare) show every
    contract shape except the listed ones, and the listed ones really are missing."""
    shown = _features([_validated(n) for n in QUOTES])
    assert CONTRACT_FEATURES - shown == set(NOT_IN_REAL_DATA)


def test_fixtures_together_cover_the_whole_contract():
    """With the hand-made quotes, every tier, Gap kind, rung and freshness case is still shown."""
    hand = []
    for n in REAL_QUOTES:
        doc = json.loads((HANDMADE / f"{n}.json").read_text())
        hand.append(
            _validate(doc.pop("_schema"), {k: v for k, v in doc.items() if k != "_fixture"})
        )
    quotes = hand + [_validated(n) for n in QUOTES]
    assert CONTRACT_FEATURES <= _features(quotes)
    chats = {
        _validated(n).reply.kind
        for n in (
            "chat_red_flag",
            "chat_clarify",
            "chat_ai_paused",
            "chat_care_paths",
            "chat_text",
            "chat_llm_invalid",
        )
    }
    assert chats == {"red_flag", "clarify", "ai_paused", "care_paths", "text", "llm_invalid"}


def test_real_fixtures_need_no_placeholders():
    """The engine's quotes validate without allow_placeholders: no all-zero sha, no fake NPI."""
    for n in REAL_QUOTES:
        model, body = _load(FIX / f"{n}.json")
        ROOT_MODELS[model].model_validate(body)


def test_hospital_files_use_the_365_day_rule():
    """Austin 2026-10-24: a hospital MRF is late only >365 days after its own last-updated date.
    Tufts' 2026-04-01 file is therefore not late on 2026-10-24 (the old 180-day rule said it was;
    the hand-made fixture checked MGB's 2026-03-27 file, which P1 does not quote)."""
    resp = _validated("quote_bcbs_hmo_shoulder")
    f = resp.sources["tufts_mrf"].freshness
    assert f.source_rule == "hospital_mrf_365_days" and str(f.last_updated) == "2026-04-01"
    assert str(f.expected_by) == "2027-04-01" and not f.late_to_refresh
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

    # keyed by source + row_id: a row_ref is not unique (one TiC price row serves every provider
    # group listed with it; a hospital line with two target codes gives two rows)
    with (FIX / "rate_row_extract.csv").open() as f:
        return {f"{r['source_id']}:{r['row_id']}": r for r in csv.DictReader(f)}


def _cited(rows, m, codes, modifier) -> dict:
    """The row a Money cites: its row_ref, one of the line's codes, its modifier and its number."""
    col = _BASIS_COLUMN[m.basis.value]
    hits = [
        r
        for r in rows.values()
        if r["row_ref"] == m.prov.row_ref
        and r["code"] in codes
        and r["modifiers"] == (modifier or "")
        and _num(r[col]) == m.low
    ]
    assert hits, (m.prov.row_ref, codes, modifier, m.low)
    return hits[0]


def _num(v: str) -> float | None:
    return None if v == "" else float(v)


_BASIS_COLUMN = {"negotiated": "amount", "discounted_cash": "discounted_cash", "gross": "gross"}


def _payer_ok(r: dict, payment) -> bool:
    """Would this row price the person's payment? (the lookup a 'not published' claim denies)
    P1: tall CSV files (Tufts) put the hospital's cash price on every payer row, so a cash price
    is any row with a discounted_cash value, not only a chargemaster row."""
    if payment.kind == "cash":
        return r["discounted_cash"] != ""
    if payment.kind == "medicare":
        return r["payer_id"] == "MEDICARE"
    if payment.kind == "masshealth":
        return r["payer_id"] == "MASSHEALTH"
    return (
        r["payer_id"] == payment.payer_id
        and r["line_of_business"] in ("commercial", "unknown")
        and (r["product"] == "" or payment.product in r["product"].split("/"))
    )


def _hospital_candidates(rows, m, ln, payment) -> list[dict]:
    """Re-run the line's lookup on the extract: same file, code, modifier, payer (or cash), and
    bill part (the engine reads facility + unknown rows together; a doctor's row stays apart)."""
    part = _cited(rows, m, ln.codes, ln.modifier)["component"]
    parts = {"facility", "unknown"} if part in ("facility", "unknown") else {part}
    return [
        r
        for r in rows.values()
        if r["source_id"] == m.prov.source_id
        and r["code"] in ln.codes
        and r["modifiers"] == (ln.modifier or "")
        and r["excluded"] == "0"
        and r["component"] in parts
        and (m.basis.value != "negotiated" or _payer_ok(r, payment))
        and r[_BASIS_COLUMN[m.basis.value]] != ""
    ]


def _tic_candidates(rows, m, ln, site_id) -> list[dict]:
    """A TiC range: every professional row of the site's billing TINs for the code / modifier at
    the site's place of service, in the networks P1 reads for the payment."""
    cfg = yaml.safe_load((REPO / "data" / "quote" / "p1_slice.yaml").read_text())
    site = {s["id"]: s for s in json.loads((FIX / "sites.json").read_text())["sites"]}[site_id]
    nets = {s for srcs in cfg["networks"].values() for s in srcs}
    pos = set(cfg["place_of_service"][site["billing_type"]])
    return [
        r
        for r in rows.values()
        if r["source_id"] in nets
        and r["tin"] in site["tins"]
        and r["code"] in ln.codes
        and r["modifiers"] == (ln.modifier or "")
        and r["billing_class"] == "professional"
        and r["excluded"] == "0"
        and set(r["service_codes"].split("|")) & pos
        and r["amount"] != ""
        and r["negotiated_type"] != "percentage"
    ]


def test_fixture_numbers_match_the_build():
    """Theater F4: every hospital-MRF and TiC number in a quote fixture is the cited row's number,
    for the line's code and modifier and the payment's payer; a range's high end is the highest
    row the same lookup finds; every 'not published' / 'percent only' claim survives re-running
    the lookup. Extract: python -m app.quote.fixtures_gen (P1)."""
    rows = _extract()
    for name in QUOTES:
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
                    if m.prov.source_kind not in ("hospital_mrf", "insurer_tic"):
                        continue
                    r = _cited(rows, m, ln.codes, ln.modifier)
                    where = (name, sq.site.site_id, ln.line_id)
                    want_payer = (r["payer_id"] or None) if m.basis.value == "negotiated" else None
                    assert m.prov.payer_id == want_payer, where
                    assert m.prov.source_sha256.startswith(m.prov.row_ref.split(":")[1]), where
                    if m.prov.source_kind == "hospital_mrf":
                        cands = _hospital_candidates(rows, m, ln, resp.payment)
                    else:
                        cands = _tic_candidates(rows, m, ln, sq.site.site_id)
                    col = _BASIS_COLUMN[m.basis.value]
                    assert any(x["row_ref"] == m.prov.row_ref for x in cands), where
                    assert m.low == min(_num(x[col]) for x in cands), where
                    assert m.high == max(_num(x[col]) for x in cands), where
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
                if isinstance(c, etl.NotPublished) and c.searched.source_id.startswith("tic_"):
                    fake = etl.Money.point(
                        0, basis="negotiated", prov=etl.Provenance(
                            source_id=c.searched.source_id, source_kind="insurer_tic",
                            source_file="x", source_sha256=c.searched.source_sha256,
                            source_date=None, method="stated",
                            row_ref=f"{c.searched.source_id}:{c.searched.source_sha256[:12]}:0",
                        ),
                    )  # fmt: skip
                    found = _tic_candidates(rows, fake, ln, sq.site.site_id)
                    assert not found, (name, ln.line_id, "has a TiC row", found[0]["row_ref"])
        for sq in resp.sites:
            for o in sq.other_payers:
                for p in o.points:
                    if p.money.prov.source_kind == "hospital_mrf":
                        _cited(rows, p.money, [o.code], "")
