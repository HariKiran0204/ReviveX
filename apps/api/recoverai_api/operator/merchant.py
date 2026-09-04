from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.models import Merchant
from recoverai_db.repositories import MerchantRepository
from recoverai_domain.errors import DomainError
from recoverai_domain.fixtures import SIMULATOR_MERCHANT_SLUG


class OperatorLookupError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, retryable=False)


def resolve_merchant(
    session: Session,
    *,
    merchant_id: UUID | None = None,
    merchant_slug: str | None = None,
    required: bool = True,
) -> Merchant | None:
    repo = MerchantRepository(session)
    if merchant_id is not None:
        merchant = repo.get_merchant(merchant_id)
        if merchant is None and required:
            raise OperatorLookupError("MERCHANT_NOT_FOUND", "Merchant was not found")
        return merchant
    slug = (merchant_slug or "").strip() or SIMULATOR_MERCHANT_SLUG
    merchant = repo.get_by_slug(slug)
    if merchant is None and slug != SIMULATOR_MERCHANT_SLUG:
        if required:
            raise OperatorLookupError("MERCHANT_NOT_FOUND", "Merchant was not found")
        return None
    if merchant is None:
        merchant = repo.get_by_slug(SIMULATOR_MERCHANT_SLUG)
    if merchant is None and required:
        raise OperatorLookupError(
            "MERCHANT_NOT_FOUND",
            "No merchant is available. Run a simulation or seed data first.",
        )
    return merchant
