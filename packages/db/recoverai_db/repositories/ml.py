from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from recoverai_db.models import ModelPrediction, ModelVersion
from recoverai_db.types import JsonDict


class ModelVersionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_version(self, version: str) -> ModelVersion | None:
        stmt = select(ModelVersion).where(ModelVersion.version == version)
        return self._session.scalar(stmt)

    def get_production(self) -> ModelVersion | None:
        stmt = select(ModelVersion).where(ModelVersion.is_production.is_(True))
        return self._session.scalar(stmt)

    def get_latest(self) -> ModelVersion | None:
        stmt = select(ModelVersion).order_by(ModelVersion.trained_at.desc()).limit(1)
        return self._session.scalar(stmt)

    def add(self, row: ModelVersion) -> ModelVersion:
        self._session.add(row)
        return row

    def clear_production(self) -> None:
        self._session.execute(update(ModelVersion).values(is_production=False))


class ModelPredictionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_fingerprint(self, fingerprint: str) -> ModelPrediction | None:
        stmt = select(ModelPrediction).where(ModelPrediction.fingerprint == fingerprint)
        return self._session.scalar(stmt)

    def list_for_case(self, recovery_case_id: uuid.UUID) -> list[ModelPrediction]:
        stmt = (
            select(ModelPrediction)
            .where(ModelPrediction.recovery_case_id == recovery_case_id)
            .order_by(ModelPrediction.updated_at.desc(), ModelPrediction.created_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def get_latest_for_action(
        self, *, recovery_case_id: uuid.UUID, action: str
    ) -> ModelPrediction | None:
        stmt = (
            select(ModelPrediction)
            .where(
                ModelPrediction.recovery_case_id == recovery_case_id,
                ModelPrediction.action == action,
            )
            .order_by(ModelPrediction.updated_at.desc(), ModelPrediction.created_at.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def upsert(
        self,
        *,
        merchant_id: uuid.UUID,
        recovery_case_id: uuid.UUID,
        action: str,
        probability: Decimal,
        model_version: str,
        feature_version: str,
        fingerprint: str,
        source: str,
        diagnostics: JsonDict | None,
    ) -> ModelPrediction:
        existing = self.get_by_fingerprint(fingerprint)
        now = datetime.now(UTC)
        if existing is not None:
            existing.probability = probability
            existing.source = source
            existing.diagnostics = diagnostics
            existing.updated_at = now
            return existing
        row = ModelPrediction(
            merchant_id=merchant_id,
            recovery_case_id=recovery_case_id,
            action=action,
            probability=probability,
            model_version=model_version,
            feature_version=feature_version,
            fingerprint=fingerprint,
            source=source,
            diagnostics=diagnostics,
        )
        self._session.add(row)
        return row
