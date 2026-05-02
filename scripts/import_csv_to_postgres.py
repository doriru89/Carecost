#!/usr/bin/env python3
"""CLI: import data CSVs into PostgreSQL."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.postgres import get_db, get_engine  # noqa: E402
from app.services.csv_import import (  # noqa: E402
    import_normalized_directory,
    import_sample_directory,
)


def _is_local_hostname(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.lower()
    return host in {"localhost", "127.0.0.1", "::1", "postgres"}


def _looks_like_prod_database_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    db_name = (parsed.path or "").lstrip("/").lower()
    suspicious_host_markers = ("railway", "amazonaws.com", "render.com", "supabase.co")
    if _is_local_hostname(host):
        return False
    if any(marker in host.lower() for marker in suspicious_host_markers):
        return True
    # Conservative fallback: non-local + non-test DB names are treated as protected.
    return bool(host) and not db_name.endswith("_test")


_STAGING_URL_PATTERNS = ("backend-test-", "staging.", "-staging.")


def _enforce_db_safety(*, allow_unsafe: bool) -> None:
    env = os.environ.get("APP_ENV", "").strip().lower()
    db_url = os.environ.get("DATABASE_URL", "").strip()

    if allow_unsafe:
        return

    if env in {"production", "prod"}:
        raise RuntimeError(
            "Refusing to run import with APP_ENV=production/prod. "
            "Use --allow-unsafe-db only when you are absolutely sure."
        )

    if env == "staging":
        parsed = urlparse(db_url)
        host = (parsed.hostname or "").lower()
        if any(p in host for p in _STAGING_URL_PATTERNS):
            return
        raise RuntimeError(
            f"APP_ENV=staging but DATABASE_URL host '{host}' "
            "doesn't match any known staging pattern. "
            "Verify the URL or use --allow-unsafe-db."
        )

    if db_url and _looks_like_prod_database_url(db_url):
        raise RuntimeError(
            "Refusing to run import against a non-local/protected DATABASE_URL. "
            "Use --allow-unsafe-db only for intentional non-production maintenance."
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
        default=os.environ.get("DATA_DIR", str(ROOT / "data" / "seed")),
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Import sample directory (data/seed/) instead of normalized ETL output.",
    )
    parser.add_argument(
        "--etl-output-dir",
        default=str(ROOT / "data" / "intermediate" / "etl_output"),
        help="Directory containing normalized CSV files (default: data/intermediate/etl_output).",
    )
    parser.add_argument(
        "--allow-unsafe-db",
        action="store_true",
        help="Bypass production/non-local DB safety checks (use with care).",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    _enforce_db_safety(allow_unsafe=args.allow_unsafe_db)

    # Initialize engine (creates tables)
    get_engine()

    # Get a session
    session_gen = get_db()
    db = next(session_gen)

    try:
        if args.sample:
            if not data_dir.is_dir():
                print(f"Error: data directory not found: {data_dir}", file=sys.stderr)
                return 1
            counts = import_sample_directory(db, data_dir)
        else:
            etl_dir = Path(args.etl_output_dir)
            counts = import_normalized_directory(db, etl_dir)

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
