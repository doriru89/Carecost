"""CareCost ETL pipeline — extract, normalize, validate, and export hospital pricing data.

All monetary values are USD dollar amounts (float). Conversion to cents
happens downstream in csv_import.py when populating the Price table.
"""

from app.etl.types import EtlResult, RawMrfRecord, RawTicRecord

__all__ = [
    "EtlResult",
    "RawMrfRecord",
    "RawTicRecord",
]
