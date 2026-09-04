from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_db.models import Customer


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_customer(self, merchant_id: uuid.UUID, customer_id: uuid.UUID) -> Customer | None:
        stmt = select(Customer).where(
            Customer.merchant_id == merchant_id,
            Customer.id == customer_id,
        )
        return self._session.scalar(stmt)

    def get_by_external_id(self, merchant_id: uuid.UUID, external_id: str) -> Customer | None:
        stmt = select(Customer).where(
            Customer.merchant_id == merchant_id,
            Customer.external_id == external_id,
        )
        return self._session.scalar(stmt)

    def list_customers(self, merchant_id: uuid.UUID) -> list[Customer]:
        stmt = select(Customer).where(Customer.merchant_id == merchant_id)
        return list(self._session.scalars(stmt).all())

    def add(self, customer: Customer) -> Customer:
        self._session.add(customer)
        return customer
