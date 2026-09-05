"""Phase 4 recovery verification columns.

Revision ID: 20260903_0002
Revises: 20260903_0001
Create Date: 2026-09-03
"""

from alembic import op

revision = "20260903_0002"
down_revision = "20260903_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE recovery_cases ADD COLUMN last_mismatch_reason VARCHAR(64)")
    op.execute("ALTER TABLE recovery_cases ADD COLUMN verified_payment_id UUID")
    op.execute("ALTER TABLE recovery_cases ADD COLUMN verified_webhook_event_id UUID")
    op.execute(
        """
        ALTER TABLE recovery_cases
        ADD CONSTRAINT fk_recovery_cases_verified_payment_id
        FOREIGN KEY (verified_payment_id) REFERENCES payments (id) ON DELETE SET NULL
        """
    )
    op.execute(
        "CREATE INDEX ix_recovery_cases_verified_payment_id ON recovery_cases (verified_payment_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_recovery_cases_verified_payment_id")
    op.execute(
        "ALTER TABLE recovery_cases DROP CONSTRAINT IF EXISTS fk_recovery_cases_verified_payment_id"
    )
    op.execute("ALTER TABLE recovery_cases DROP COLUMN IF EXISTS verified_webhook_event_id")
    op.execute("ALTER TABLE recovery_cases DROP COLUMN IF EXISTS verified_payment_id")
    op.execute("ALTER TABLE recovery_cases DROP COLUMN IF EXISTS last_mismatch_reason")
