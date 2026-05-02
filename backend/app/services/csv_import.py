"""CSV → PostgreSQL idempotent import for demo data."""

from __future__ import annotations

import csv
import hashlib
import logging
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.tables import (
    HospitalBenchmark,
    HospitalPayerRate,
    HospitalProcedure,
    Insurer,
    Price,
    Procedure,
    Provider,
)
from app.registries import bundles_for_specialty, infer_hospital_from_address

BUNDLE_CPT_AZ_MVP: dict[str, str] = {
    bid: b.cpt for bid, b in bundles_for_specialty("Gastroenterology").items()
}

AZ_PROVIDERS_COLUMNS = (
    "npi",
    "first_name",
    "last_name",
    "credential",
    "gender",
    "address",
    "city",
    "state",
    "zip",
    "phone",
)

_AZ_MVP_REF_LAT = 42.3358
_AZ_MVP_REF_LNG = -71.0726

PROVIDERS_COLUMNS = (
    "npi",
    "name",
    "address",
    "city",
    "zip",
    "lat",
    "lng",
    "taxonomy",
    "phone",
    "specialties",
    "source",
    "hospital",
)
PROCEDURES_COLUMNS = ("bundle_id", "label", "cpt_codes", "tags", "source")
PRICES_COLUMNS = (
    "provider_id",
    "bundle_id",
    "min_rate_cents",
    "max_rate_cents",
    "payer",
    "source",
    "confidence",
    "effective_date",
)
INSURERS_COLUMNS = (
    "plan_id",
    "carrier",
    "deductible_cents",
    "oop_max_cents",
    "coinsurance_pct",
    "copay_cents",
    "source",
)

def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _npi_jitter_lat_lng(npi: str) -> tuple[float, float]:
    h = int(hashlib.sha256(npi.encode()).hexdigest()[:12], 16)
    lat_off = ((h % 2000) - 1000) / 80000.0
    lng_off = (((h // 2000) % 2000) - 1000) / 80000.0
    return _AZ_MVP_REF_LAT + lat_off, _AZ_MVP_REF_LNG + lng_off


def _parse_float_cell(raw: str) -> float | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _dollars_to_cents(x: float | None) -> int | None:
    if x is None:
        return None
    return int(round(x * 100))


def _require_columns(row_keys: set[str], required: tuple[str, ...], file_label: str) -> None:
    missing = [c for c in required if c not in row_keys]
    if missing:
        raise ValueError(f"{file_label}: missing columns: {', '.join(missing)}")


def _upsert_by_pk(db: Session, table_cls: type, rows: list[dict]) -> int:  # noqa: ANN401
    if not rows:
        return 0
    table = table_cls.__table__  # type: ignore[attr-defined]
    pk_cols = {c.name for c in table.primary_key.columns}
    update_cols = [c.name for c in table.columns if c.name not in pk_cols]
    stmt = pg_insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=list(pk_cols),
        set_={col: stmt.excluded[col] for col in update_cols},
    )
    db.execute(stmt)
    db.flush()
    return len(rows)


def import_providers_csv(db: Session, path: Path) -> int:
    rows = _read_csv(path)
    if not rows:
        return 0
    _require_columns(set(rows[0].keys()), PROVIDERS_COLUMNS, path.name)
    values = []
    for row in rows:
        specialties = [s.strip() for s in row["specialties"].split(",") if s.strip()]
        values.append(
            {
                "npi": row["npi"].strip(),
                "name": row["name"].strip(),
                "address": row["address"].strip(),
                "city": row["city"].strip(),
                "zip": row["zip"].strip(),
                "lat": float(row["lat"]),
                "lng": float(row["lng"]),
                "taxonomy": row["taxonomy"].strip(),
                "phone": row["phone"].strip(),
                "specialties": specialties,
                "source": row["source"].strip(),
                "hospital": row.get("hospital", "").strip(),
            }
        )
    return _upsert_by_pk(db, Provider, values)


def import_procedures_csv(db: Session, path: Path) -> int:
    rows = _read_csv(path)
    if not rows:
        return 0
    _require_columns(set(rows[0].keys()), PROCEDURES_COLUMNS, path.name)
    values = []
    for row in rows:
        cpt_codes = [c.strip() for c in row["cpt_codes"].split("|") if c.strip()]
        values.append(
            {
                "bundle_id": row["bundle_id"].strip(),
                "label": row["label"].strip(),
                "cpt_codes": cpt_codes,
                "tags": row["tags"].strip(),
                "source": row["source"].strip(),
            }
        )
    return _upsert_by_pk(db, Procedure, values)


def import_prices_csv(db: Session, path: Path) -> int:
    rows = _read_csv(path)
    if not rows:
        return 0
    _require_columns(set(rows[0].keys()), PRICES_COLUMNS, path.name)
    values = []
    for row in rows:
        values.append(
            {
                "provider_id": row["provider_id"].strip(),
                "bundle_id": row["bundle_id"].strip(),
                "min_rate_cents": int(row["min_rate_cents"]),
                "max_rate_cents": int(row["max_rate_cents"]),
                "payer": row["payer"].strip(),
                "source": row["source"].strip(),
                "confidence": float(row["confidence"]),
                "effective_date": row["effective_date"].strip(),
                "mvp_hospital_id": row.get("mvp_hospital_id", "").strip() or None,
            }
        )
    return _upsert_prices(db, values)


def import_insurers_csv(db: Session, path: Path) -> int:
    rows = _read_csv(path)
    if not rows:
        return 0
    _require_columns(set(rows[0].keys()), INSURERS_COLUMNS, path.name)
    values = []
    for row in rows:
        values.append(
            {
                "plan_id": row["plan_id"].strip(),
                "carrier": row["carrier"].strip(),
                "deductible_cents": int(row["deductible_cents"]),
                "oop_max_cents": int(row["oop_max_cents"]),
                "coinsurance_pct": int(row["coinsurance_pct"]),
                "copay_cents": int(row["copay_cents"]),
                "source": row["source"].strip(),
            }
        )
    return _upsert_by_pk(db, Insurer, values)


def import_az_providers_csv(
    db: Session,
    path: Path,
    specialty: str = "Gastroenterology",
    taxonomy: str = "207RG0100X",
) -> int:
    rows = _read_csv(path)
    if not rows:
        return 0
    _require_columns(set(rows[0].keys()), AZ_PROVIDERS_COLUMNS, path.name)
    values = []
    for row in rows:
        npi = row["npi"].strip()
        first = row["first_name"].strip()
        last = row["last_name"].strip()
        cred = row["credential"].strip()
        name_parts = [first, last]
        if cred:
            name_parts.append(cred)
        name = " ".join(name_parts)
        lat, lng = _npi_jitter_lat_lng(npi)
        hospital = row.get("hospital", "").strip() or infer_hospital_from_address(
            row.get("address", ""), row.get("city", "")
        )
        values.append(
            {
                "npi": npi,
                "name": name,
                "address": row["address"].strip(),
                "city": row["city"].strip(),
                "zip": row["zip"].strip(),
                "state": row.get("state", "").strip(),
                "lat": lat,
                "lng": lng,
                "taxonomy": taxonomy,
                "phone": row["phone"].strip(),
                "specialties": [specialty],
                "source": "az_mvp",
                "hospital": hospital,
            }
        )
    return _upsert_by_pk(db, Provider, values)


def _upsert_prices(db: Session, values: list[dict]) -> int:
    if not values:
        return 0
    table = Price.__table__
    stmt = pg_insert(table).values(values)  # type: ignore[arg-type]
    stmt = stmt.on_conflict_do_update(
        constraint="uq_prices_natural_key",
        set_={
            "min_rate_cents": stmt.excluded.min_rate_cents,
            "max_rate_cents": stmt.excluded.max_rate_cents,
            "confidence": stmt.excluded.confidence,
            "mvp_hospital_id": stmt.excluded.mvp_hospital_id,
        },
    )
    db.execute(stmt)
    db.flush()
    return len(values)


_logger = logging.getLogger(__name__)


def _upsert_by_constraint(db: Session, table_cls: type, rows: list[dict], constraint: str) -> int:
    if not rows:
        return 0
    table = table_cls.__table__
    pk_cols = {c.name for c in table.primary_key.columns}
    update_cols = [c.name for c in table.columns if c.name not in pk_cols]
    stmt = pg_insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint=constraint,
        set_={col: stmt.excluded[col] for col in update_cols},
    )
    db.execute(stmt)
    db.flush()
    return len(rows)


_PROCEDURE_FLOAT_COLS = {"gross_charge", "discounted_cash", "de_identified_min", "de_identified_max"}
_PAYER_RATE_FLOAT_COLS = {"negotiated_rate"}
_BENCHMARK_FLOAT_COLS = {"price", "quality_rating"}


def import_hospital_procedures_csv(db: Session, path: Path) -> int:
    from app.etl.csv_builder import PROCEDURE_COLUMNS

    raw_rows = _read_csv(path)
    if not raw_rows:
        return 0
    _require_columns(set(raw_rows[0].keys()), PROCEDURE_COLUMNS, path.name)
    rows = []
    for r in raw_rows:
        row = {c: r.get(c, "") for c in PROCEDURE_COLUMNS}
        row["id"] = f"{row['hospital_id']}:{row['cpt']}"
        for col in _PROCEDURE_FLOAT_COLS:
            row[col] = _parse_float_cell(row[col])
        rows.append(row)
    return _upsert_by_constraint(db, HospitalProcedure, rows, "uq_hospital_procedures_hid_cpt")


def import_hospital_payer_rates_csv(db: Session, path: Path) -> int:
    from app.etl.csv_builder import PAYER_RATE_COLUMNS

    raw_rows = _read_csv(path)
    if not raw_rows:
        return 0
    _require_columns(set(raw_rows[0].keys()), PAYER_RATE_COLUMNS, path.name)
    rows = []
    for r in raw_rows:
        row = {c: r.get(c, "") for c in PAYER_RATE_COLUMNS}
        for col in _PAYER_RATE_FLOAT_COLS:
            row[col] = _parse_float_cell(row[col])
        rows.append(row)
    return _upsert_by_constraint(db, HospitalPayerRate, rows, "uq_hospital_payer_rates_natural_key")


def import_hospital_benchmarks_csv(db: Session, path: Path) -> int:
    from app.etl.csv_builder import BENCHMARK_COLUMNS

    raw_rows = _read_csv(path)
    if not raw_rows:
        return 0
    _require_columns(set(raw_rows[0].keys()), BENCHMARK_COLUMNS, path.name)
    rows = []
    for r in raw_rows:
        row = {c: r.get(c, "") for c in BENCHMARK_COLUMNS}
        for col in _BENCHMARK_FLOAT_COLS:
            row[col] = _parse_float_cell(row[col])
        rows.append(row)
    return _upsert_by_constraint(db, HospitalBenchmark, rows, "uq_hospital_benchmarks_natural_key")


def import_normalized_directory(db: Session, directory: Path) -> dict[str, int]:
    if not directory.is_dir():
        raise FileNotFoundError(f"ETL output directory not found: {directory}")
    counts: dict[str, int] = {}
    for stem, fn in (
        ("hospital_procedures", import_hospital_procedures_csv),
        ("hospital_payer_rates", import_hospital_payer_rates_csv),
        ("hospital_benchmarks", import_hospital_benchmarks_csv),
    ):
        p = directory / f"{stem}.csv"
        if p.exists():
            counts[stem] = fn(db, p)
        else:
            _logger.warning("Skipping %s.csv — file not found in %s", stem, directory)
    return counts


def import_sample_directory(db: Session, directory: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    p = directory / "providers.csv"
    if p.exists():
        counts["providers"] = import_providers_csv(db, p)
    p = directory / "procedures.csv"
    if p.exists():
        counts["procedures"] = import_procedures_csv(db, p)
    p = directory / "prices.csv"
    if p.exists():
        counts["prices"] = import_prices_csv(db, p)
    p = directory / "insurers.csv"
    if p.exists():
        counts["insurers"] = import_insurers_csv(db, p)
    return counts
