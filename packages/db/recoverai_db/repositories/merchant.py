from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_db.models import Merchant, MerchantMembership, User


class MerchantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_merchant(self, merchant_id: uuid.UUID) -> Merchant | None:
        return self._session.get(Merchant, merchant_id)

    def get_by_slug(self, slug: str) -> Merchant | None:
        return self._session.scalar(select(Merchant).where(Merchant.slug == slug))

    def list_memberships(self, merchant_id: uuid.UUID) -> list[MerchantMembership]:
        stmt = select(MerchantMembership).where(MerchantMembership.merchant_id == merchant_id)
        return list(self._session.scalars(stmt).all())

    def get_membership(
        self, merchant_id: uuid.UUID, user_id: uuid.UUID
    ) -> MerchantMembership | None:
        stmt = select(MerchantMembership).where(
            MerchantMembership.merchant_id == merchant_id,
            MerchantMembership.user_id == user_id,
        )
        return self._session.scalar(stmt)

    def add(self, merchant: Merchant) -> Merchant:
        self._session.add(merchant)
        return merchant

    def add_user(self, user: User) -> User:
        self._session.add(user)
        return user

    def add_membership(self, membership: MerchantMembership) -> MerchantMembership:
        self._session.add(membership)
        return membership
