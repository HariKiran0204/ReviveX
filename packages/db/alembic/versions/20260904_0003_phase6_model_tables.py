"""Phase 6 model version and prediction tables.

Revision ID: 20260904_0003
Revises: 20260903_0002
Create Date: 2026-09-04
"""

from alembic import op

revision = "20260904_0003"
down_revision = "20260903_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE model_versions (
            version VARCHAR(64) NOT NULL,
            algorithm VARCHAR(64) NOT NULL,
            dataset_version VARCHAR(128) NOT NULL,
            feature_version VARCHAR(64) NOT NULL,
            seed INTEGER NOT NULL,
            trained_at TIMESTAMP WITH TIME ZONE NOT NULL,
            artifact_path TEXT NOT NULL,
            quality_passed BOOLEAN NOT NULL DEFAULT FALSE,
            is_production BOOLEAN NOT NULL DEFAULT FALSE,
            metrics JSONB,
            configuration JSONB,
            notes TEXT,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_model_versions PRIMARY KEY (id),
            CONSTRAINT uq_model_versions_version UNIQUE (version)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_model_versions_production
        ON model_versions (is_production)
        WHERE is_production IS TRUE
        """
    )
    op.execute(
        """
        CREATE TABLE model_predictions (
            recovery_case_id UUID NOT NULL,
            action VARCHAR(64) NOT NULL,
            probability NUMERIC(8, 6) NOT NULL,
            model_version VARCHAR(64) NOT NULL,
            feature_version VARCHAR(64) NOT NULL,
            fingerprint VARCHAR(64) NOT NULL,
            source VARCHAR(32) NOT NULL DEFAULT 'ml',
            diagnostics JSONB,
            id UUID NOT NULL,
            merchant_id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_model_predictions PRIMARY KEY (id),
            CONSTRAINT fk_model_predictions_recovery_case_id_recovery_cases
                FOREIGN KEY (recovery_case_id) REFERENCES recovery_cases (id) ON DELETE CASCADE,
            CONSTRAINT ck_model_predictions_model_predictions_probability_unit_interval
                CHECK (probability >= 0 AND probability <= 1)
        )
        """
    )
    op.execute("CREATE INDEX ix_model_predictions_merchant_id ON model_predictions (merchant_id)")
    op.execute(
        "CREATE INDEX ix_model_predictions_recovery_case_id ON model_predictions (recovery_case_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_model_predictions_fingerprint ON model_predictions (fingerprint)"
    )
    op.execute(
        """
        CREATE INDEX ix_model_predictions_case_action_version
        ON model_predictions (merchant_id, recovery_case_id, action, model_version)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_predictions")
    op.execute("DROP TABLE IF EXISTS model_versions")
