"""I1-I7 (plan v2 §invariants) as property tests over every care path x payment x answer set,
on the committed extract (real rows). Seeded, so a failure reproduces.

I1 no hidden money: every offered line has a Cell (Money or a typed Gap); missing is never $0.
I2 gap honesty: no negative amount; a conflict shows both numbers and is never summed.
I3 provenance: every amount cites a row that exists in the data the engine loaded.
I4 AI apart: AI-suggested lines are never in a total.
I5 no swapping: under "your insurance" only that payer's negotiated rates; the output does not
   depend on the order rows were loaded in.
I6 one version: one data build per answer; every cited source is a loaded source.
I7 ranking never rewards missing data: dropping a summed price never moves a site up.
"""

from __future__ import annotations

import copy
import random

import pytest

from app.etl.contracts import Conflict, Money
from app.quote.contracts import QuoteRequest
from app.quote.engine import Engine
from app.quote.store import RateStore
from tests.quote.conftest import AS_OF

PAYMENTS = [
    {"kind": "insurance", "payer_id": "BCBS_MA", "product": "HMO", "network": None},
    {"kind": "insurance", "payer_id": "BCBS_MA", "product": "PPO", "network": None},
    {"kind": "insurance", "payer_id": "AETNA", "product": "PPO", "network": None},
    {"kind": "cash"},
    {"kind": "medicare"},
    {"kind": "masshealth"},
]
ANSWERS = [{}, {"Q14": ["hmo_referral_required"]}]


def _all_requests(registry):
    for pid in sorted(registry.paths):
        path = registry.paths[pid]
        answer_sets = [*ANSWERS, *({**m.when} for m in path.tier_modifiers)]
        for pay in PAYMENTS:
            for ans in answer_sets:
                yield QuoteRequest.model_validate({
                    "payment": pay, "care_path_id": pid, "answers": ans, "service_codes": [],
                    "picked_by": "person", "site_ids": None,
                })  # fmt: skip


@pytest.fixture(scope="module")
def quotes(engine, registry):
    return [(req, engine.quote(req, AS_OF)) for req in _all_requests(registry)]


def _moneys(ln):
    for c in [ln.cell, *(e.cell for e in ln.elsewhere)]:
        if isinstance(c, Money):
            yield c
        elif isinstance(c, Conflict):
            yield c.a
            yield c.b


def test_property_run_is_big_enough(quotes):
    lines = sum(len(sq.receipt.lines) for _, r in quotes for sq in r.sites)
    assert len(quotes) >= 100 and lines >= 5000, (len(quotes), lines)


def test_i1_every_offered_line_has_a_cell_and_missing_is_never_zero(quotes):
    for _, r in quotes:
        for sq in r.sites:
            for ln in sq.receipt.lines:
                assert ln.availability == "not_offered" or ln.cell is not None
                for m in _moneys(ln):
                    assert m.low > 0, (sq.site.site_id, ln.line_id)


def test_i2_no_negative_and_conflicts_never_summed(quotes):
    for _, r in quotes:
        for sq in r.sites:
            for ln in sq.receipt.lines:
                for m in _moneys(ln):
                    assert 0 <= m.low <= m.high
                if isinstance(ln.cell, Conflict):
                    assert not ln.in_total


def test_i3_every_amount_cites_a_loaded_row(quotes, store, engine):
    refs = {(m.row_ref(r), r.row_id) for r in store.rows.values() for m in [store.sources[r.source_id]]}
    ref_only = {a for a, _ in refs}
    for _, r in quotes:
        for sq in r.sites:
            for ln in sq.receipt.lines:
                for m in _moneys(ln):
                    for p in m.provs():
                        if p.source_kind.value == "clinic_posted":
                            assert p.source_id in engine.posted_by_source
                        elif p.row_id:
                            assert (p.row_ref, p.row_id) in refs, p.row_ref
                        else:
                            assert p.row_ref in ref_only, p.row_ref


def test_i4_ai_lines_never_in_a_total(quotes):
    seen = 0
    for _, r in quotes:
        for sq in r.sites:
            t = sq.receipt.totals.likely
            for ln in sq.receipt.lines:
                if ln.ai_suggested:
                    seen += 1
                    assert not ln.in_total and (t is None or ln.line_id not in t.line_ids)
    assert seen > 0


def test_i5_only_your_payers_rates(quotes):
    for req, r in quotes:
        pay = req.payment
        if pay.kind != "insurance":
            continue
        for sq in r.sites:
            for ln in sq.receipt.lines:
                for m in _moneys(ln):
                    if m.basis.value == "negotiated":
                        assert {p.payer_id for p in m.provs()} == {pay.payer_id}


def test_i5_row_order_does_not_change_the_answer(store, registry, quotes):
    rng = random.Random(20261024)
    rows = list(store.rows.items())
    rng.shuffle(rows)
    shuffled = RateStore(
        rows=dict(rows), sources=store.sources, version=store.version, codes=store.codes,
        group_npis=store.group_npis,
    )  # fmt: skip
    eng = Engine(shuffled, registry)
    for req, r in rng.sample(quotes, 30):
        assert eng.quote(req, AS_OF).model_dump_json() == r.model_dump_json()


def test_i6_one_data_version(quotes, store, engine):
    loaded = set(store.sources) | set(engine.posted_by_source)
    for _, r in quotes:
        assert r.data_version.build_id == store.version.build_id
        assert set(r.sources) <= loaded


def _position(site_quotes, site_id):
    return [sq["site"]["site_id"] for sq in site_quotes].index(site_id)


def test_i7_dropping_a_price_never_moves_a_site_up(quotes):
    rng = random.Random(7)
    checked = 0
    for _, r in rng.sample(quotes, 60):
        base = r.model_dump(mode="json")["sites"]
        if len(base) < 2:
            continue
        for sq in base:
            for ln in sq["receipt"]["lines"]:
                if not ln["in_total"]:
                    continue
                mutated = copy.deepcopy(base)
                me = next(s for s in mutated if s["site"]["site_id"] == sq["site"]["site_id"])
                line = next(x for x in me["receipt"]["lines"] if x["line_id"] == ln["line_id"])
                line["cell"] = {"kind": "not_loaded", "what": "dropped", "eta": None}
                line["in_total"] = False
                t = me["receipt"]["totals"]
                rest = [x for x in me["receipt"]["lines"] if x["in_total"]]
                t["likely"] = {"low": sum(x["cell"]["low"] for x in rest)} if rest else None
                after = Engine._rank(mutated)
                before = _position(base, sq["site"]["site_id"])
                assert _position(after, sq["site"]["site_id"]) >= before
                checked += 1
    assert checked > 50
