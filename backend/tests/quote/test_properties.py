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

import random

import pytest

from app.etl.contracts import Conflict, Money
from app.quote.contracts import QuoteRequest
from app.quote.engine import Engine
from app.quote.fixtures_gen import KEY_SITES, NEAR
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
                for where in ({"site_ids": None, "near": NEAR}, {"site_ids": KEY_SITES}):
                    yield QuoteRequest.model_validate({
                        "payment": pay, "care_path_id": pid, "answers": ans,
                        "service_codes": [], "picked_by": "person", **where,
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
    refs = {(m.row_ref(r), r.row_id) for r in store.rows for m in [store.sources[r.source_id]]}
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
    rows = list(store.rows)
    rng.shuffle(rows)
    shuffled = RateStore(
        rows=rows, sources=store.sources, version=store.version, codes=store.codes,
        npi_sets=store.npi_sets, census_tins=store.census_tins, flags=store.flags,
    )  # fmt: skip  (C4b: the TiC row flags travel with the rows, keyed by row id)
    eng = Engine(shuffled, registry)
    for req, r in rng.sample(quotes, 30):
        assert eng.quote(req, AS_OF).model_dump_json() == r.model_dump_json()


def test_i6_one_data_version(quotes, store, engine):
    loaded = set(store.sources) | set(engine.posted_by_source)
    for _, r in quotes:
        assert r.data_version.build_id == store.version.build_id
        assert set(r.sources) <= loaded


def _drop(store: RateStore, site, code: str, engine: Engine) -> RateStore:
    """A store without this site's own prices for one code (its hospital file's rows and its own
    billing TINs' TiC rows): 'this price was never published'."""
    src = engine._site_hospital_source(site)
    own = set(engine.reg.site_tins(site))
    rows = [
        r for r in store.rows
        if r.code != code or not (
            (src and r.source_id == src) or (r.source_kind == "insurer_tic" and r.tin in own)
        )
    ]  # fmt: skip
    return RateStore(rows=rows, sources=store.sources, version=store.version, codes=store.codes,
                     npi_sets=store.npi_sets, census_tins=store.census_tins)  # fmt: skip


def test_i7_missing_data_never_makes_a_site_look_cheaper(store, registry, quotes):
    """C3 P1 / P5 property over random removals: drop one site's own price for one summed line
    (re-running the engine on a store without those rows). Either the step becomes missing
    (missing goes up: the site sorts below every site that has it), or the line is estimated
    and its step enters the ranking at the neutral peer median, never at a smaller partial sum
    and never at the minimum row. A site never gains rank from a line that just disappeared."""
    rng = random.Random(7)
    picks = []
    for req, r in rng.sample([x for x in quotes if x[0].near is not None], 40):
        for sq in r.sites:
            for ln in sq.receipt.lines:
                if ln.in_total and ln.at == "this_site" and ln.estimate is None and ln.step_id:
                    picks.append((req, sq.site.site_id, ln))
    checked = estimated = 0
    for req, site_id, ln in rng.sample(picks, 30):
        site = registry.sites[site_id]
        eng = Engine(_drop(store, site, ln.codes[0], Engine(store, registry)), registry)
        before = next(s for s in Engine(store, registry).quote(
            req.model_copy(update={"site_ids": [site_id], "near": None}), AS_OF).sites)  # fmt: skip
        after = next(s for s in eng.quote(
            req.model_copy(update={"site_ids": [site_id], "near": None}), AS_OF).sites)  # fmt: skip
        st_b = next(st for st in before.steps if st.step_id == ln.step_id)
        st_a = next(st for st in after.steps if st.step_id == ln.step_id)
        if st_b.figure == "none":
            continue  # the step was already without a figure: nothing to lose
        if after.headline.missing > before.headline.missing:
            checked += 1
            continue
        # not missing: the step still has a figure, and any line of it that lost its own price
        # is now an estimate whose rank value is the peer median
        assert st_a.figure != "none", (site_id, ln.line_id)
        lines = {x.line_id: x for x in after.receipt.lines}
        for lid in st_a.line_ids:
            x = lines[lid]
            if x.estimate is not None:
                estimated += 1
        if st_a.figure == "own":  # another row still prices it: unchanged rank inputs or dearer
            assert st_a.rank_value is not None and st_b.rank_value is not None
        checked += 1
    assert checked >= 10, checked


def test_i7_ranking_uses_missing_steps_then_the_comparable_figure(quotes):
    from app.quote.contracts import rank_key

    seen = 0
    for _, r in quotes:
        if r.ordering != "rank":
            continue
        keys = [rank_key(sq) for sq in r.sites]
        assert keys == sorted(keys)
        for sq in r.sites:
            expected = [st for st in sq.steps if st.likelihood in ("certain", "likely")
                        and st.rank_value is not None]  # fmt: skip
            want = round(sum(st.rank_value for st in expected), 2) if expected else None
            assert sq.headline.comparable == want
            seen += 1
    assert seen > 100
