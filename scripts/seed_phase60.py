#!/usr/bin/env python3
"""Seed Phase 60 tables: data_sources + cpt_rvu_components."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

env_path = BACKEND / ".env"
if env_path.is_file():
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except ImportError:
        pass

from app.db.postgres import get_db  # noqa: E402
from app.etl.rvu_parser import parse_rvu_file  # noqa: E402
from app.registries import load_etl_config  # noqa: E402
from app.services.csv_import import import_cpt_rvu_components, seed_data_sources  # noqa: E402

CMS_PFS_PATH = ROOT / "data" / "raw" / "government" / "cms_pfs" / "PPRRVU2026_Jan_nonQPP.csv"


def main() -> int:
    db_url = os.environ.get("DATABASE_URL", "")
    if "railway" in db_url or "render.com" in db_url:
        print("ERROR: refusing to seed against production DB", file=sys.stderr)
        return 1

    session_gen = get_db()
    db = next(session_gen)

    try:
        src_count = seed_data_sources(db)
        print(f"data_sources: {src_count} rows upserted")

        config = load_etl_config()
        target_cpts: set[str] = set()
        for cpts in config.cpt_extraction_sets.values():
            target_cpts.update(cpts)

        if not CMS_PFS_PATH.is_file():
            print(f"WARNING: CMS PFS file not found at {CMS_PFS_PATH}", file=sys.stderr)
            print("Skipping RVU import — seed data_sources only", file=sys.stderr)
            db.commit()
            return 0

        rvu_records = parse_rvu_file(CMS_PFS_PATH, target_cpts)
        rvu_count = import_cpt_rvu_components(db, rvu_records)
        print(f"cpt_rvu_components: {rvu_count} rows upserted ({len(rvu_records)} parsed)")

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
