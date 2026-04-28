#!/usr/bin/env python3
"""CLI: import data CSVs into PostgreSQL."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.postgres import get_db, get_engine  # noqa: E402
from app.services.csv_import import (  # noqa: E402
    import_az_directory,
    import_insurers_csv,
    import_procedures_csv,
    import_sample_directory,
)


def main() -> int:
    env_path = BACKEND / ".env"
    if env_path.is_file():
        try:
            from dotenv import load_dotenv

            load_dotenv(env_path)
        except ImportError:
            pass

    parser = argparse.ArgumentParser(description="Import CSV fixtures into PostgreSQL")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("DATA_DIR", str(ROOT / "data" / "az-data")),
    )
    parser.add_argument(
        "--az-mvp",
        action="store_true",
        default=True,
        help="Load data/az-data (NPI providers + hospital_rates + per-NPI prices)",
    )
    parser.add_argument("--seed-dir", default=str(ROOT / "data" / "az-data"))
    parser.add_argument("--price-hospital-id", default="bmc")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    # Initialize engine (creates tables)
    get_engine()

    # Get a session
    session_gen = get_db()
    db = next(session_gen)

    try:
        if args.az_mvp:
            seed = Path(args.seed_dir)
            for name, fn in (
                ("procedures", import_procedures_csv),
                ("insurers", import_insurers_csv),
            ):
                p = seed / f"{name}.csv"
                if p.exists():
                    fn(db, p)
            az_dir = Path(os.environ.get("AZ_DATA_DIR", str(ROOT / "data" / "az-data")))
            if not az_dir.is_dir():
                print(f"Error: AZ data directory not found: {az_dir}", file=sys.stderr)
                return 1
            counts = import_az_directory(db, az_dir, price_hospital_id=args.price_hospital_id)
        else:
            if not data_dir.is_dir():
                print(f"Error: data directory not found: {data_dir}", file=sys.stderr)
                return 1
            counts = import_sample_directory(db, data_dir)

        db.commit()
        for k, v in counts.items():
            print(f"{k}: {v} rows upserted")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
