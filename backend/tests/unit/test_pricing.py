from app.services.pricing import min_max_allowed_for_provider_prices, pick_primary_source


def test_min_max() -> None:
    docs = [
        {"min_rate_cents": 100, "max_rate_cents": 200, "source": "a"},
        {"min_rate_cents": 50, "max_rate_cents": 300, "source": "b"},
    ]
    assert min_max_allowed_for_provider_prices(docs) == (50, 300)


def test_pick_primary_prefers_mrf() -> None:
    docs = [{"source": "turquoise_cache"}, {"source": "mrf_sample"}]
    assert pick_primary_source(docs) == "mrf_sample"
