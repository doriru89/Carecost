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
# Stream C: every golden quote is real engine output (python -m app.quote.fixtures_gen). C2: the
# Medicare / MassHealth fee schedules are A3's registered sources (sources.d/government.yaml). A
# clinic's posted self-pay page is a source derived from sites.yaml (posted_<site id>).
UNREGISTERED_SOURCES: dict[str, str] = {}  # C2: every fee schedule is A3's registered source
QUOTES = (
    "quote_bcbs_hmo_shoulder",
    "quote_cash_shoulder",
    "quote_medicare_shoulder",
    "quote_masshealth_manual",
)
REAL_QUOTES = QUOTES  # all four are app.quote.fixtures_gen output
HANDMADE_QUOTES = ("quote_bcbs_hmo_shoulder", "quote_cash_shoulder", "quote_medicare_shoulder")
HANDMADE = Path(__file__).resolve().parent / "handmade"  # the pre-engine hand-made quotes


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
    site_ids = set(SITES) | {s["id"] for s in json.loads((FIX / "sites.json").read_text())["sites"]}
    for key in ("site_id",):
        for sid in _walk(body, key):
            assert sid in site_ids, f"unknown site {sid} (not in data/sites/sites.yaml)"


def test_fixture_sources_are_registered():
    from app.etl.config import load_sources

    registered = {s.source_id for s in load_sources().sources}
    registered |= {f"posted_{sid}" for sid, s in SITES.items() if s.get("cash_prices")}
    used = set()
    for name in QUOTES:
        used |= set(_validated(name).sources)
    assert used - registered == set(UNREGISTERED_SOURCES)


def _modified(path, st, answers):
    """P1 #19: the step after the path's tier modifiers for these answers (tier, rating)."""
    tier, rating = st.likelihood_tier, st.appropriateness.rating
    for m in path.tier_modifiers:
        if m.step == st.id and all(set(v) & set(answers.get(k, [])) for k, v in m.when.items()):
            tier = m.tier
            rating = m.appropriateness.rating if m.appropriateness else rating
    return tier, rating


def test_quote_lines_match_the_care_path():
    """step ids exist in the path, and the line's likelihood is the (modified) step's tier."""
    for name in QUOTES:
        resp = _validated(name)
        if resp.care_path is None:
            continue
        req = json.loads((FIX / f"{name.replace('quote_', 'quote_request_', 1)}.json").read_text())
        path = PATHS[resp.care_path.id]
        steps = {s.id: s for s in path.steps}
        assert resp.care_path.review_status == path.review.status
        for sq in resp.sites:
            for ln in sq.receipt.lines:
                st = steps[ln.step_id]
                tier, rating = _modified(path, st, req["answers"])
                assert ln.likelihood == tier, (name, ln.line_id)
                step_codes = st.all_codes()
                if ln.component == "facility":  # P9 / C2: a clinic visit's facility fee (G0463)
                    step_codes |= set(ENGINE_RULES["hospital_visit_facility_codes"])
                assert set(ln.codes) <= step_codes, (name, ln.line_id, ln.codes)
                if ln.ai_suggested:
                    assert set(ln.codes) <= {c.code for a in st.ai_potential for c in a.cpts}
                # P11: the line says what its likelihood rests on, derived from the step
                assert ln.tier_basis == q.tier_basis_for_rating(rating), (
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
    if any(ln.estimate is not None for ln in lines):
        f.add("estimate")  # C3 P5
    if any(ln.availability == "unknown" for ln in lines):
        f.add("availability_unknown")  # C3 R1
    if any(st.figure == "elsewhere" for qr in quotes for sq in qr.sites for st in sq.steps):
        f.add("step_elsewhere")  # C3 P4
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
    "estimate",
    "availability_unknown",
    "step_elsewhere",
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
    *(f"rung:{r}" for r in (2, 5, 6, 7, None)),
}

# Shapes the real P1 quotes cannot show yet, and why. Only the hand-made quotes in handmade/ show
# them (they stay the mutation base of the negative rule tests). When real data starts showing one,
# test_real_fixtures_cover_what_real_data_can fails: drop it from here.
NOT_IN_REAL_DATA = {
    "cell:percent_only": "no BCBS HMO / cash row of the golden quotes' sites is percent-only for "
    "these codes",
    "not_offered_elsewhere": "Site.offered holds positive evidence only (A3); no evidence is "
    "availability 'unknown', never 'not offered'",
    "late_to_refresh": "no source the fixture quotes use is past its publisher deadline on "
    "2026-10-25 (Fallon's 2026-09-01 TiC file is, but no golden quote reads Fallon)",
    "stale_on_our_side": "every source was fetched within our own schedule",
}


def test_real_fixtures_cover_what_real_data_can():
    """The golden quotes in contracts/fixtures (real BCBS + cash, hand-made Medicare) show every
    contract shape except the listed ones, and the listed ones really are missing."""
    shown = _features([_validated(n) for n in QUOTES])
    assert CONTRACT_FEATURES - shown == set(NOT_IN_REAL_DATA)


def test_fixtures_together_cover_the_whole_contract():
    """With the hand-made quotes, every tier, Gap kind, rung and freshness case is still shown."""
    hand = []
    for n in HANDMADE_QUOTES:
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
    f = resp.sources["mtauburn_mrf"].freshness  # Mount Auburn's file is dated 2026-04-01 too
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
# An independent re-implementation of each lookup over the committed extract (it reads the rule
# files, never the engine), so a number cannot pass because the engine agrees with itself.

ENGINE_RULES = yaml.safe_load((REPO / "data" / "quote" / "engine.yaml").read_text())
NETWORKS = yaml.safe_load((REPO / "data" / "etl" / "tic_networks.yaml").read_text())["networks"]
OFFICE_POS = set(
    yaml.safe_load((REPO / "data" / "etl" / "tic_visit_codes.yaml").read_text())["pos_buckets"][
        "non_facility"
    ]
)
SITES = {
    s["id"]: s
    for s in yaml.safe_load((REPO / "data" / "sites" / "sites.yaml").read_text())["sites"]
}  # C2: the registry the golden quotes use (208 sites)
RADIOLOGY = {
    h: sorted({str(t["tin"]) for g in groups for t in g["tins"]})
    for h, groups in (yaml.safe_load(
        (REPO / "data" / "sites" / "radiology_groups.yaml").read_text())["hospitals"] or {}).items()
}  # fmt: skip
CENSUS_TINS = yaml.safe_load((FIX / "rate_row_extract.sources.yaml").read_text())["census_tins"]


def _extract() -> dict[str, dict]:
    import csv

    # keyed by source + row_id: a row_ref is not unique (one TiC price row serves every provider
    # group listed with it; a hospital line with two target codes gives two rows)
    rows = {}
    for f in ("rate_row_extract.csv",):
        with (FIX / f).open() as fh:
            rows |= {f"{r['source_id']}:{r['row_id']}": r for r in csv.DictReader(fh)}
    return rows


_BASIS_COLUMN = {
    "negotiated": "amount",
    "discounted_cash": "discounted_cash",
    "gross": "gross",
    "fee_schedule": "amount",
    "estimate": "amount",
}


def _num(v: str) -> float | None:
    return None if v == "" else float(v)


def _cited(rows, prov, amount, basis, codes, modifier) -> dict:
    """The row a Provenance cites: row_ref (+ row_id on TiC), one of the line's codes, the
    modifier and the number."""
    col = _BASIS_COLUMN[basis]
    hits = [
        r
        for r in rows.values()
        if r["row_ref"] == prov.row_ref
        and (prov.row_id is None or r["row_id"] == prov.row_id)
        and r["code"] in codes
        and r["modifiers"] in {modifier or "", "TC"}
        and (basis == "estimate" or _num(r[col]) == amount)
    ]
    assert hits, (prov.row_ref, codes, modifier, amount)
    return hits[0]


def _payer_ok(r: dict, payment) -> bool:
    """Would this hospital row price the person's payment? Tall CSV files (Tufts) put the cash
    price on every payer row, so a cash price is any row with a discounted_cash value."""
    if payment.kind == "cash":
        return r["discounted_cash"] != ""
    if payment.kind == "medicare":
        return r["payer_id"] == "MEDICARE" and r["line_of_business"] == "medicare"
    if payment.kind == "masshealth":
        return r["payer_id"] == "MASSHEALTH" and r["line_of_business"] == "medicaid"
    return (
        r["payer_id"] == payment.payer_id
        and r["line_of_business"] in ("commercial", "connector", "unknown")
        and (r["product"] == "" or payment.product in r["product"].split("/"))
    )


def _hospital_candidates(rows, m, ln, payment) -> list[dict]:
    """Re-run the line's lookup on the extract: same file, code, modifier, payer (or cash), bill
    part (a facility line reads facility + unknown rows, a doctor's line professional rows), and
    the same dollar kind (a stated dollar is never ranged with a %-derived one, D20)."""
    cited = _cited(rows, m.prov, m.low, m.basis.value, ln.codes, ln.modifier)
    parts = {"facility", "unknown"} if ln.component in ("facility", "drug") else {"professional"}
    return [
        r
        for r in rows.values()
        if r["source_id"] == m.prov.source_id
        and r["code"] in ln.codes
        and r["modifiers"] == cited["modifiers"]
        and r["component"] in parts
        and (m.basis.value != "negotiated" or _payer_ok(r, payment))
        and (m.basis.value != "negotiated" or r["amount_method"] == cited["amount_method"])
        and r[_BASIS_COLUMN[m.basis.value]] != ""
    ]


def _networks(payment) -> set[str]:
    if payment.kind != "insurance":
        return set()
    from app.etl.config import load_sources

    payer = {s.source_id: s.payer_id for s in load_sources().sources}
    return {
        n["source_id"]
        for n in NETWORKS
        if (n.get("payer_id") or payer.get(n["source_id"])) == payment.payer_id
        and (n.get("product") or payment.product) == payment.product
    }


def _tic_candidates(rows, ln, site_id, payment, billing_class) -> list[dict]:
    """Every TiC row of the site's billing TINs for the code / modifier, in the payment's
    networks; professional rows at the site's place of service (any POS for a modifier-26 reading,
    Austin 2026-10-24), preferring facility-only rows on a hospital line."""
    site = SITES[site_id]
    billing = site["billing_type"]
    if billing == "unknown":  # P9: priced as a hospital clinic (an ASC site as an ASC)
        billing = "asc" if site["site_type"] == "ambulatory_surgery_center" else (
            ENGINE_RULES["unknown_billing_priced_as"])  # fmt: skip
    pos = set(ENGINE_RULES["place_of_service"][billing])
    if billing == "office_visit" and site["site_type"] not in ENGINE_RULES["urgent_care_site_types"]:
        pos = set(ENGINE_RULES["place_of_service"]["office_kind"])  # O F3a
    nets = _networks(payment)
    own = (
        set(site.get("tins", [])) | set(site.get("tin_npis", [])) | set(site.get("type_2_npis", []))
    )
    cid = site.get("census_id") or ""
    linked = set(CENSUS_TINS.get(cid, [])) - own
    rad = set(RADIOLOGY.get(site.get("hospital_entity_id") or "", []))

    def mine(r, tins) -> bool:
        return r["tin"] in tins or (r["tin"] in linked and cid in r["site_ids"].split(";"))

    if billing_class == "professional" and ln.modifier == "26" and rad:
        first = _tic_rows_for(rows, ln, nets, billing_class, lambda r: r["tin"] in rad)
        if first:  # C2: the hospital's radiology group first (radiology_groups.yaml)
            return first
    return _tic_rows_for(rows, ln, nets, billing_class, lambda r: mine(r, own), pos)


def _tic_rows_for(rows, ln, nets, billing_class, keep, pos=None) -> list[dict]:
    cands = [
        r
        for r in rows.values()
        if r["source_id"] in nets
        and keep(r)
        and r["code"] in ln.codes
        and r["modifiers"] == ("" if billing_class == "facility" else (ln.modifier or ""))
        and r["billing_class"] == billing_class
        and r["amount"] != ""
        and r["negotiated_type"] != "percentage"
    ]
    if billing_class == "professional" and ln.modifier != "26" and pos is not None:
        cands = [r for r in cands if set(r["service_codes"].split("|")) & pos]
        if not pos & OFFICE_POS:
            fac = [r for r in cands if not set(r["service_codes"].split("|")) & OFFICE_POS]
            cands = fac or cands
    return cands


def _check_estimate(rows, m, ln, sq, payment, where):
    """C3 P5: an estimate is the PeerRange's p25-p75 (>= min_groups groups); each end is a real
    row's number for the same code, from the payment's own rates, never this site's own TIN."""
    est = ln.estimate
    assert est is not None and est.n_groups >= ENGINE_RULES["peers"]["min_groups"], where
    assert (m.low, m.high) == (est.low, est.high) and est.low <= est.median <= est.high, where
    want = payment.payer_id if payment.kind == "insurance" else None
    assert est.payer_id == want and all(p.payer_id == want for p in m.provs()), where
    if m.prov.source_kind.value == "clinic_posted":
        return
    col = "discounted_cash" if payment.kind == "cash" else "amount"
    site = SITES[sq.site.site_id]
    own = (
        set(site.get("tins", [])) | set(site.get("tin_npis", [])) | set(site.get("type_2_npis", []))
    )
    for p, v in ((m.prov, m.low), (m.prov_high or m.prov, m.high)):
        r = _cited(rows, p, v, "estimate", ln.codes, ln.modifier)
        assert _num(r[col]) == v, (*where, "an estimate end is a real row's number")
        if r["source_kind"] == "insurer_tic":
            assert r["source_id"] in _networks(payment) and r["tin"] not in own, where
        elif payment.kind == "insurance":
            assert _payer_ok(r, payment), where


def _check_money(rows, m, ln, sq, payment, where):
    if m.basis.value == "estimate":
        _check_estimate(rows, m, ln, sq, payment, where)
        return
    kind = m.prov.source_kind.value
    if kind == "clinic_posted":
        page = SITES[ln.chain_price_from or sq.site.site_id]  # R12: the chain's posted page
        posted = [p for p in page["cash_prices"] if set(p.get("codes", [])) & set(ln.codes)]
        assert m.low == m.high == min(p["amount"] for p in posted), where
        return
    per_unit = 1.0
    if m.prov.method.value == "per_unit_x_base_units":  # the cited row is the per-unit rate
        base = yaml.safe_load((REPO / "data" / "quote" / "anesthesia_time.yaml").read_text())
        per_unit = float(base["base_units"][ln.codes[0]])
    lo = _cited(rows, m.prov, round(m.low / per_unit, 2), m.basis.value, ln.codes, ln.modifier)
    if m.prov_high is not None:
        _cited(rows, m.prov_high, round(m.high / per_unit, 2), m.basis.value, ln.codes,
               ln.modifier)
    want_payer = (lo["payer_id"] or None) if m.basis.value == "negotiated" else None
    assert m.prov.payer_id == want_payer, where
    assert m.prov.source_sha256.startswith(m.prov.row_ref.split(":")[1]), where
    col = _BASIS_COLUMN[m.basis.value]
    if kind == "hospital_mrf":
        cands = _hospital_candidates(rows, m, ln, payment)
    elif kind == "insurer_tic":
        bc = "facility" if ln.component == "facility" else "professional"
        cands = _tic_candidates(rows, ln, sq.site.site_id, payment, bc)
    else:  # fee schedule: one row per code / modifier / setting
        assert m.low == m.high == _num(lo["amount"]), where
        return
    un = ln.unusual
    if un is not None and not un.whole_line and m is ln.cell:  # P8: rows set aside per network
        aside = {(p.row_ref, p.row_id) for sa in un.set_aside for p in sa.provs()}
        lo_sa = min(sa.low for sa in un.set_aside)
        hi_sa = max(sa.high for sa in un.set_aside)
        cands = [x for x in cands if (x["row_ref"], x["row_id"] or None) not in aside
                 and not (lo_sa <= _num(x[col]) <= hi_sa and not m.low <= _num(x[col]) <= m.high)]
    assert any(x["row_ref"] == m.prov.row_ref for x in cands), where
    if m.prov.method.value == "per_unit_x_base_units":  # O: a per-unit anesthesia rate
        base = yaml.safe_load((REPO / "data" / "quote" / "anesthesia_time.yaml").read_text())
        units = float(base["base_units"][ln.codes[0]])
        cands = [{**x, col: str(round(_num(x[col]) * units, 2))} for x in cands]
    assert m.low == min(_num(x[col]) for x in cands), where
    assert m.high == max(_num(x[col]) for x in cands), where


def test_fixture_numbers_match_the_build():
    """Theater F4: every number in a quote fixture is the cited row's number for the line's code,
    modifier and the payment's payer; a range's high end is the highest row the same lookup finds
    and is cited too (prov_high); a rung-6 estimate is the cited Medicare row x the multiple; every
    'not published' / 'percent only' claim survives re-running the lookup. Extract:
    python -m app.quote.fixtures_gen."""
    rows = _extract()
    for name in QUOTES:
        resp = _validated(name)
        pay = resp.payment
        for sq in resp.sites:
            for ln in sq.receipt.lines:
                if ln.at != "this_site":
                    continue  # the referral visit is priced at the person's own primary care office
                where = (name, sq.site.site_id, ln.line_id)
                cells = [ln.cell, ln.list_price]
                moneys = []
                for c in cells:
                    if isinstance(c, etl.Money):
                        moneys.append(c)
                    elif isinstance(c, etl.Conflict):
                        moneys += [c.a, c.b]
                for m in moneys:
                    _check_money(rows, m, ln, sq, pay, where)
                c = ln.cell
                if isinstance(
                    c, (etl.NotPublished, etl.PercentOnly)
                ) and c.searched.source_id.endswith("_mrf"):
                    cands = [
                        r
                        for r in rows.values()
                        if r["source_id"] == c.searched.source_id
                        and r["code"] in ln.codes
                        and r["modifiers"] in ("", "TC")
                        and r["component"] in ("facility", "unknown")
                        and _payer_ok(r, pay)
                    ]
                    col = "discounted_cash" if pay.kind == "cash" else "amount"
                    dollars = [r for r in cands if r[col] != ""]
                    assert not dollars, (*where, "has a dollar row", dollars[0]["row_ref"])
                    if isinstance(c, etl.PercentOnly):
                        assert any(_num(r["negotiated_pct"]) == c.pct for r in cands), where
                if (
                    isinstance(c, etl.NotPublished)
                    and c.searched.source_id.startswith("tic_")
                    and ln.component == "professional"
                    and ln.doctor_fee is None
                ):
                    found = _tic_candidates(rows, ln, sq.site.site_id, pay, "professional")
                    assert not found, (*where, "has a TiC row", found[0]["row_ref"])
        for sq in resp.sites:
            for o in sq.other_payers:
                for p in o.points:
                    _cited(rows, p.money.prov, p.money.low, "negotiated", [o.code], "")
                    if p.money.prov_high:
                        _cited(rows, p.money.prov_high, p.money.high, "negotiated", [o.code], "")
