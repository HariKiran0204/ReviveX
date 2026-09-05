from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from recoverai_db.session import check_database_connection, get_engine


def test_database_connection(database_url: str) -> None:
    assert check_database_connection(database_url) is True


def test_migration_upgrade_and_downgrade(database_url: str, alembic_config: Config) -> None:
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    engine = get_engine(database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "recovery_cases" in tables
    assert "payments" in tables
    assert "audit_events" in tables

    command.downgrade(alembic_config, "base")
    tables_after = set(inspect(engine).get_table_names())
    assert "recovery_cases" not in tables_after

    command.upgrade(alembic_config, "head")
