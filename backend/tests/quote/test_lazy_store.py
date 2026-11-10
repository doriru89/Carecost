"""The lazy, partitioned-by-code RateStore (the server's) answers exactly like the eager one.

Austin 2026-11-09: a Cloud Run cold start spent 41 s turning 1.55 M rows into Python objects. The
server now reads the small tables at startup and each code's rows on its first lookup. These tests
hold it to the eager store on the committed extract: same golden quotes, same order, same counts,
safe when several requests load the same code at once, and loud when something walks every row.
"""

from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.quote.engine import Engine
from app.quote.fixtures_gen import GOLDEN, fixture_text, request
from app.quote.store import load_pack, pack_from_extract
from tests.quote.conftest import AS_OF


@pytest.fixture(scope="module")
def pack_path():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "quote_pack.sqlite"
        pack_from_extract(p)
        yield p


def _engines(pack_path, registry, **kw):
    eager = Engine(load_pack(pack_path, lazy=False, **kw), registry)
    lazy = Engine(load_pack(pack_path, lazy=True, **kw), registry)
    return eager, lazy


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_lazy_store_reproduces_every_golden_quote(pack_path, registry, name):
    eager, lazy = _engines(pack_path, registry)
    a = fixture_text(eager.quote(request(name), AS_OF).model_dump(mode="json"))
    b = fixture_text(lazy.quote(request(name), AS_OF).model_dump(mode="json"))
    assert a == b


def test_lazy_store_with_the_registry_tin_filter_matches_eager(pack_path, registry):
    eager, lazy = _engines(pack_path, registry, tins=registry.tins, census_ids=registry.census_ids)
    for name in sorted(GOLDEN):
        assert (eager.quote(request(name), AS_OF).model_dump_json()
                == lazy.quote(request(name), AS_OF).model_dump_json())  # fmt: skip
    assert lazy.store.counts() == eager.store.counts()
    assert lazy.store.total_rows() == len(eager.store.rows)


def test_lazy_store_loads_nothing_at_startup_and_each_code_once(pack_path, registry):
    store = load_pack(pack_path, lazy=True)
    Engine(store, registry)
    assert store._loaded == set()  # the engine's startup reads no rows
    code = sorted(store.codes)[0]
    store.by_code.get(("any_source", code))
    assert store._loaded == {code}
    before = {k: list(v) for k, v in store._ix["by_code"].items()}
    store.ensure_code(code)  # a second load is a no-op: no duplicate rows
    assert {k: list(v) for k, v in store._ix["by_code"].items()} == before


def test_lazy_tic_items_keep_the_eager_order(pack_path, registry):
    eager = load_pack(pack_path, lazy=False)
    lazy = load_pack(pack_path, lazy=True)
    codes = sorted({k[2] for k, _ in eager.tic.items()})
    assert codes, "the extract has TiC rows"
    assert [k for k, _ in lazy.tic_items(codes)] == [k for k, _ in eager.tic_items(codes)]


def test_concurrent_first_lookups_load_a_code_once(pack_path, registry):
    """FastAPI runs sync routes in a thread pool: many requests may hit a cold code together."""
    eager, _ = _engines(pack_path, registry)
    lazy = Engine(load_pack(pack_path, lazy=True), registry)
    names = sorted(GOLDEN) * 4
    want = {n: eager.quote(request(n), AS_OF).model_dump_json() for n in set(names)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(lambda n: (n, lazy.quote(request(n), AS_OF).model_dump_json()), names))
    assert all(js == want[n] for n, js in got)


def test_walking_every_row_of_a_lazy_store_fails_loudly(pack_path):
    store = load_pack(pack_path, lazy=True)
    with pytest.raises(RuntimeError, match="lazy"):
        list(store.rows)
    with pytest.raises(RuntimeError, match="lazy"):
        store.tic.items()
