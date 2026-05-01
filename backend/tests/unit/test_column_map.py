"""SSOT coverage: column_map keys must match registry payers."""

from app.etl.column_map import PAYER_RATE_MAP
from app.registries import all_payers


def test_payer_rate_map_covers_all_registry_payers():
    registry_ids = set(all_payers().keys())
    map_ids = set(PAYER_RATE_MAP.keys())
    assert map_ids == registry_ids, f"Drift: registry={registry_ids - map_ids}, map={map_ids - registry_ids}"
