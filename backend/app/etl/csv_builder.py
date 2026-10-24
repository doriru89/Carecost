"""Column layout of the legacy seed CSVs (data/seed/etl/*.csv) read by services/csv_import.py.

The old ETL that wrote these files (pipeline.py and friends) was deleted in favour of
``python -m app.etl`` (see app/etl/cli.py). These constants stay only because the FastAPI
seed path still imports the committed snapshot; a later phase replaces both.
"""

from __future__ import annotations

PROCEDURE_COLUMNS = (
    "hospital_id",
    "cpt",
    "cpt_desc",
    "gross_charge",
    "discounted_cash",
    "de_identified_min",
    "de_identified_max",
    "billing_class",
    "setting",
    "rate_methodology",
    "data_completeness",
    "compliance_score",
    "price_granularity",
    "null_reason",
    "source_type",
    "rate_quality",
)

PAYER_RATE_COLUMNS = (
    "hospital_id",
    "cpt",
    "payer_id",
    "negotiated_rate",
    "plan_name",
    "source",
    "source_origin",
    "billing_class",
    "price_source",
    "setting",
    "source_file",
    "rate_methodology",
    "plan_type",
    "payer_raw",
)

BENCHMARK_COLUMNS = (
    "hospital_id",
    "cpt",
    "benchmark_source",
    "component",
    "price",
    "quality_rating",
)
