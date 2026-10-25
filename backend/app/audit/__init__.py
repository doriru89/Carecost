"""Outlier audit (stream O): peer medians per X2, outliers outside 1/3x-3x, traced to the source.

Read-only over the quote pack, the site registry and the ETL intermediates; it changes no engine or
ETL code. Re-run on a new pack with ``python -m app.audit --pack <pack.sqlite>`` (docs/etl/outlier-audit.md).
"""
