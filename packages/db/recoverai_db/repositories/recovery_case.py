from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from recoverai_db.models import RecoveryCase

_CASE_SORTS = {
    "created_at": RecoveryCase.created_at,
    "amount_at_risk": RecoveryCase.amount_at_risk,
    "amount_recovered": RecoveryCase.amount_recovered,
    "status": RecoveryCase.status,
    "case_type": RecoveryCase.case_type,
    "priority": RecoveryCase.priority,
}


class RecoveryCaseRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_case(self, merchant_id: uuid.UUID, case_id: uuid.UUID) -> RecoveryCase | None:
        stmt = select(RecoveryCase).where(
            RecoveryCase.merchant_id == merchant_id,
            RecoveryCase.id == case_id,
        )
        return self._session.scalar(stmt)

    def get_case_unscoped(self, case_id: uuid.UUID) -> RecoveryCase | None:
        return self._session.get(RecoveryCase, case_id)

    def list_cases(
        self,
        merchant_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[RecoveryCase]:
        stmt = select(RecoveryCase).where(RecoveryCase.merchant_id == merchant_id)
        if status is not None:
            stmt = stmt.where(RecoveryCase.status == status)
        stmt = stmt.order_by(RecoveryCase.created_at.desc())
        return list(self._session.scalars(stmt).all())

    def page_cases(
        self,
        merchant_id: uuid.UUID,
        *,
        status: str | None = None,
        case_type: str | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        sort: str = "created_at",
        direction: str = "desc",
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[RecoveryCase], int]:
        filters = RecoveryCase.merchant_id == merchant_id
        stmt: Select[tuple[RecoveryCase]] = select(RecoveryCase).where(filters)
        count_stmt = select(func.count()).select_from(RecoveryCase).where(filters)
        if status is not None:
            stmt = stmt.where(RecoveryCase.status == status)
            count_stmt = count_stmt.where(RecoveryCase.status == status)
        if case_type is not None:
            stmt = stmt.where(RecoveryCase.case_type == case_type)
            count_stmt = count_stmt.where(RecoveryCase.case_type == case_type)
        if min_amount is not None:
            stmt = stmt.where(RecoveryCase.amount_at_risk >= min_amount)
            count_stmt = count_stmt.where(RecoveryCase.amount_at_risk >= min_amount)
        if max_amount is not None:
            stmt = stmt.where(RecoveryCase.amount_at_risk <= max_amount)
            count_stmt = count_stmt.where(RecoveryCase.amount_at_risk <= max_amount)
        column = _CASE_SORTS.get(sort, RecoveryCase.created_at)
        order = column.desc() if direction.lower() != "asc" else column.asc()
        stmt = stmt.order_by(order, RecoveryCase.id.desc()).offset(offset).limit(limit)
        total = int(self._session.scalar(count_stmt) or 0)
        return list(self._session.scalars(stmt).all()), total

    def list_open_for_payment(
        self, merchant_id: uuid.UUID, payment_id: uuid.UUID
    ) -> list[RecoveryCase]:
        stmt = select(RecoveryCase).where(
            RecoveryCase.merchant_id == merchant_id,
            RecoveryCase.payment_id == payment_id,
            RecoveryCase.closed_at.is_(None),
        )
        return list(self._session.scalars(stmt).all())

    def get_case_for_update(self, case_id: uuid.UUID) -> RecoveryCase | None:
        stmt = select(RecoveryCase).where(RecoveryCase.id == case_id).with_for_update()
        return self._session.scalar(stmt)

    def list_open_for_customer(
        self, merchant_id: uuid.UUID, customer_id: uuid.UUID
    ) -> list[RecoveryCase]:
        stmt = select(RecoveryCase).where(
            RecoveryCase.merchant_id == merchant_id,
            RecoveryCase.customer_id == customer_id,
            RecoveryCase.closed_at.is_(None),
        )
        return list(self._session.scalars(stmt).all())

    def list_that_counted_payment(
        self, merchant_id: uuid.UUID, payment_id: uuid.UUID
    ) -> list[RecoveryCase]:
        stmt = select(RecoveryCase).where(
            RecoveryCase.merchant_id == merchant_id,
            RecoveryCase.verified_payment_id == payment_id,
            RecoveryCase.amount_recovered > 0,
        )
        return list(self._session.scalars(stmt).all())

    def add(self, case: RecoveryCase) -> RecoveryCase:
        self._session.add(case)
        return case
