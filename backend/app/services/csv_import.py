"""CSV → PostgreSQL idempotent import for demo data."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.tables import HospitalRate, Insurer, Price, Procedure, Provider
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


def _upsert_by_pk(db: Session, table_cls: type, rows: list[dict]) -> int:
    if not rows:
        return 0
    table = table_cls.__table__
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


def import_hospital_rates_csv(db: Session, path: Path) -> int:
    rows = _read_csv(path)
    if not rows:
        return 0
    values = []
    for row in rows:
        hid = row["hospital_id"].strip()
        cpt = str(row["cpt"]).strip()
        values.append(
            {
                "id": f"{hid}:{cpt}",
                "hospital_id": hid,
                "hospital_name": row.get("hospital_name", "").strip(),
                "neighborhood": row.get("neighborhood", "").strip(),
                "system": row.get("system", "").strip(),
                "data_completeness": row.get("data_completeness", "").strip(),
                "cpt": cpt,
                "cpt_desc": row.get("cpt_desc", "").strip(),
                "gross_charge": _parse_float_cell(row.get("gross_charge", "")),
                "discounted_cash": _parse_float_cell(row.get("discounted_cash", "")),
                "de_identified_min": _parse_float_cell(row.get("de_identified_min", "")),
                "de_identified_max": _parse_float_cell(row.get("de_identified_max", "")),
                "bcbs_price": _parse_float_cell(row.get("bcbs_price", "")),
                "bcbs_source": row.get("bcbs_source", "").strip(),
                "bcbs_plan": row.get("bcbs_plan", "").strip(),
                "aetna_price": _parse_float_cell(row.get("aetna_price", "")),
                "aetna_source": row.get("aetna_source", "").strip(),
                "aetna_plan": row.get("aetna_plan", "").strip(),
                "harvard_pilgrim_price": _parse_float_cell(row.get("harvard_pilgrim_price", "")),
                "hp_plan_name": row.get(
                    "hp_plan_name", row.get("harvard_pilgrim_plan", "")
                ).strip(),
                "hp_source": row.get("hp_source", "").strip(),
                "uhc_price": _parse_float_cell(row.get("uhc_price", "")),
                "uhc_source": row.get("uhc_source", row.get("uhc_plan", "")).strip(),
                "bcbs_tic_rate": _parse_float_cell(row.get("bcbs_tic_rate", "")),
                "bcbs_tic_billing_class": row.get("bcbs_tic_billing_class", "").strip(),
                "billing_class": row.get("billing_class", "unknown").strip(),
                "setting": row.get("setting", "").strip(),
                "rate_methodology": row.get("rate_methodology", "").strip(),
                "turquoise_bundled_price": _parse_float_cell(
                    row.get("turquoise_bundled_price", "")
                ),
                "turquoise_quality_rating": _parse_float_cell(
                    row.get("turquoise_quality_rating", "")
                ),
                "masscomparecare_total_paid": _parse_float_cell(
                    row.get("masscomparecare_total_paid", "")
                ),
                "fh_physician_in_network": _parse_float_cell(
                    row.get("fh_physician_in_network", "")
                ),
                "fh_anesthesia_in_network": _parse_float_cell(
                    row.get("fh_anesthesia_in_network", "")
                ),
                "fh_facility_hosp_in_network": _parse_float_cell(
                    row.get("fh_facility_hosp_in_network", "")
                ),
                "fh_pathology_in_network": _parse_float_cell(
                    row.get("fh_pathology_in_network", "")
                ),
                "source": "az_mvp",
            }
        )
    return _upsert_by_pk(db, HospitalRate, values)


_AZ_PAYER_RATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("bcbs_price", "BCBS_MA"),
    ("aetna_price", "AETNA"),
    ("harvard_pilgrim_price", "HARVARD_PILGRIM"),
    ("uhc_price", "UHC"),
)


def _upsert_prices(db: Session, values: list[dict]) -> int:
    if not values:
        return 0
    table = Price.__table__
    stmt = pg_insert(table).values(values)
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


def import_az_mvp_prices(
    db: Session,
    hospital_id: str = "bmc",
    effective_date: str = "2024-01-01",
) -> int:
    npis = [r[0] for r in db.query(Provider.npi).filter(Provider.source == "az_mvp").all()]
    if not npis:
        return 0

    values = []
    for bundle_id, cpt in BUNDLE_CPT_AZ_MVP.items():
        hr = (
            db.query(HospitalRate)
            .filter(
                HospitalRate.hospital_id == hospital_id,
                HospitalRate.cpt == cpt,
            )
            .first()
        )
        if not hr:
            continue

        dmin = hr.de_identified_min
        dmax = hr.de_identified_max
        fallback_min_c = _dollars_to_cents(dmin) if dmin is not None else None
        fallback_max_c = _dollars_to_cents(dmax) if dmax is not None else None
        if fallback_min_c is None and fallback_max_c is None:
            gc = _dollars_to_cents(hr.gross_charge) if hr.gross_charge is not None else None
            fallback_min_c = fallback_max_c = gc or 0
        elif fallback_min_c is None:
            fallback_min_c = fallback_max_c or 0
        elif fallback_max_c is None:
            fallback_max_c = fallback_min_c

        payer_bands: list[tuple[str, int, int]] = []
        for field_name, payer_key in _AZ_PAYER_RATE_FIELDS:
            raw = getattr(hr, field_name, None)
            c = _dollars_to_cents(raw) if raw is not None else None
            if c is None or c <= 0:
                continue
            payer_bands.append((payer_key, c, c))

        if not payer_bands:
            payer_bands.append(
                ("BCBS_MA", int(fallback_min_c), int(fallback_max_c or fallback_min_c))
            )

        for npi in npis:
            for payer_key, min_c, max_c in payer_bands:
                values.append(
                    {
                        "provider_id": npi,
                        "bundle_id": bundle_id,
                        "payer": payer_key,
                        "source": "az_mvp",
                        "effective_date": effective_date,
                        "min_rate_cents": min_c,
                        "max_rate_cents": max_c,
                        "confidence": 0.88,
                        "mvp_hospital_id": hospital_id,
                    }
                )
    return _upsert_prices(db, values)


def import_az_directory(
    db: Session,
    directory: Path,
    *,
    price_hospital_id: str = "bmc",
) -> dict[str, int]:
    counts: dict[str, int] = {}
    p = directory / "providers.csv"
    if p.exists():
        counts["providers_gi"] = import_az_providers_csv(db, p)
    p = directory / "hospital_rates_clean.csv"
    if p.exists():
        counts["hospital_rates_gi"] = import_hospital_rates_csv(db, p)
    if counts.get("providers_gi") and counts.get("hospital_rates_gi"):
        counts["prices_gi"] = import_az_mvp_prices(db, hospital_id=price_hospital_id)
    p = directory / "providers_derm.csv"
    if p.exists():
        counts["providers_derm"] = import_az_providers_csv(
            db,
            p,
            specialty="Dermatology",
            taxonomy="207N00000X",
        )
    p = directory / "hospital_rates_derm.csv"
    if p.exists():
        counts["hospital_rates_derm"] = import_hospital_rates_csv(db, p)
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
