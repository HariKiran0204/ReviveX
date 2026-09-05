from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from alembic.config import Config
from sqlalchemy.orm import Session

from alembic import command
from recoverai_db.session import get_engine, normalize_database_url


def _database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="session")
def database_url() -> str:
    raw = _database_url()
    if not raw:
        pytest.skip("DATABASE_URL or TEST_DATABASE_URL is required for database tests")
    url = normalize_database_url(raw)
    try:
        get_engine(url).connect().close()
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    return url


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    return Config("alembic.ini")


@pytest.fixture(scope="session")
def migrated_database(database_url: str, alembic_config: Config) -> str:
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")
    yield database_url


@pytest.fixture
def db_session(migrated_database: str) -> Generator[Session, None, None]:
    engine = get_engine(migrated_database)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
        session.flush()
    finally:
        session.close()
        transaction.rollback()
        connection.close()
