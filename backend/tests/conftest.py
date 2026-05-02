"""Pytest fixtures: PostgreSQL test database + seeded API client."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.postgres import get_db
from app.db.tables import Base
from app.main import create_app
from app.etl.seed_migration import migrate_wide_to_normalized
from app.services.csv_import import import_az_directory

AZ_DATA = Path(__file__).resolve().parent.parent.parent / "data" / "seed"


def _test_database_url() -> str:
    return os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/carecost_test",
    )


@pytest.fixture(scope="session")
def engine() -> Generator[Engine, None, None]:
    url = _test_database_url()
    os.environ["DATABASE_URL"] = url
    try:
        e = create_engine(url, pool_pre_ping=True, future=True)
        with e.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available ({url}): {exc}")
    Base.metadata.drop_all(e)
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def seeded_db(db_session: Session) -> Session:
    import_az_directory(db_session, AZ_DATA)
    migrate_wide_to_normalized(db_session)
    _seed_dimension_tables(db_session)
    db_session.commit()
    return db_session


def _seed_dimension_tables(db: Session) -> None:
    """Populate hospitals + payers dimension tables from YAML registries."""
    from app.db.tables import Hospital, Payer
    from app.registries import all_hospitals, all_payers

    for hid, h in all_hospitals().items():
        db.merge(Hospital(
            hospital_id=hid, name=h.name, system_name=h.system,
            state="MA", metro_area="boston", neighborhood=h.neighborhood,
            lat=h.lat, lng=h.lng, npi=h.npi or "",
        ))
    for pid, p in all_payers().items():
        db.merge(Payer(
            payer_id=pid, canonical_name=p.label, parent_brand="",
            payer_type="commercial", operating_states=[], tic_portal=p.tic_portal or "",
        ))


@pytest.fixture
def client(seeded_db: Session):
    def _override():
        yield seeded_db

    from app.services.confirmation_llm import FakeLLMClient, get_llm_client

    app = create_app()
    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()
