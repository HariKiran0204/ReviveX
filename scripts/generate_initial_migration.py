"""Generate the initial Alembic migration from SQLAlchemy metadata."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable, DropIndex, DropTable

from recoverai_db.base import Base
import recoverai_db.models  # noqa: F401

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages/db/alembic/versions/20260903_0001_phase2_initial_schema.py"
)


def main() -> None:
    dialect = postgresql.dialect()
    upgrade_lines: list[str] = []
    downgrade_lines: list[str] = []

    tables = list(Base.metadata.sorted_tables)
    indexes = [index for table in tables for index in table.indexes]

    for table in tables:
        create_sql = str(CreateTable(table).compile(dialect=dialect)).strip()
        upgrade_lines.append(f'    op.execute("""{create_sql}""")')

    for index in sorted(indexes, key=lambda idx: idx.name or ""):
        create_index_sql = str(CreateIndex(index).compile(dialect=dialect)).strip()
        upgrade_lines.append(f'    op.execute("""{create_index_sql}""")')

    for index in sorted(indexes, key=lambda idx: idx.name or "", reverse=True):
        drop_index_sql = str(DropIndex(index).compile(dialect=dialect)).strip()
        downgrade_lines.append(f'    op.execute("""{drop_index_sql}""")')

    for table in reversed(tables):
        drop_sql = str(DropTable(table).compile(dialect=dialect)).strip()
        downgrade_lines.append(f'    op.execute("""{drop_sql}""")')

    content = f'''"""Phase 2 initial schema

Revision ID: 20260903_0001
Revises:
Create Date: 2026-09-03
"""

from alembic import op

revision = "20260903_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
{chr(10).join(upgrade_lines)}


def downgrade() -> None:
{chr(10).join(downgrade_lines)}
'''
    MIGRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    MIGRATION_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {MIGRATION_PATH}")


if __name__ == "__main__":
    main()
