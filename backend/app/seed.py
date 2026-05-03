"""Auto-seed normalized tables on deploy (idempotent)."""

import logging
from pathlib import Path

from app.db.postgres import get_session_factory
from app.services.csv_import import import_normalized_directory

_log = logging.getLogger(__name__)
SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed" / "etl"


def run_seed() -> None:
    if not SEED_DIR.is_dir():
        _log.warning("Seed dir %s not found, skipping", SEED_DIR)
        return
    db = get_session_factory()()
    try:
        counts = import_normalized_directory(db, SEED_DIR)
        db.commit()
        for k, v in counts.items():
            _log.info("seed %s: %d rows", k, v)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed()
