from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from recoverai_db.models import Customer, Merchant
from recoverai_db.repositories import CustomerRepository, MerchantRepository

SEED_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
# Dedicated demo merchant. Created on first simulation call; not a seed.py requirement.
SIMULATOR_MERCHANT_SLUG = "recoverai-demo"
SIMULATOR_CUSTOMER_EXTERNAL_ID = "sim_cust_001"
SIMULATOR_ALT_CUSTOMER_EXTERNAL_ID = "sim_cust_002"
SIMULATOR_ALT_MERCHANT_SLUG = "recoverai-demo-alt"
# Previous Phase 3 slug; still recognized so existing rows are not duplicated.
LEGACY_SIMULATOR_MERCHANT_SLUG = "simulator-dev"


def simulator_merchant_id() -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, "merchant:recoverai-demo")


def simulator_customer_id() -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, "customer:recoverai-demo:1")


def simulator_alt_customer_id() -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, "customer:recoverai-demo:2")


def simulator_alt_merchant_id() -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, "merchant:recoverai-demo-alt")


def _get_demo_merchant(merchants: MerchantRepository) -> Merchant | None:
    merchant = merchants.get_merchant(simulator_merchant_id())
    if merchant is not None:
        return merchant
    merchant = merchants.get_by_slug(SIMULATOR_MERCHANT_SLUG)
    if merchant is not None:
        return merchant
    return merchants.get_by_slug(LEGACY_SIMULATOR_MERCHANT_SLUG)


def ensure_simulator_fixtures(session: Session) -> tuple[Merchant, Customer]:
    """Idempotent demo merchant + customer for clean installs. Safe to call repeatedly."""
    merchants = MerchantRepository(session)
    merchant = _get_demo_merchant(merchants)
    if merchant is None:
        merchant = Merchant(
            id=simulator_merchant_id(),
            name="RecoverAI Demo Merchant",
            slug=SIMULATOR_MERCHANT_SLUG,
            description="Deterministic demo merchant for local payment simulation",
        )
        try:
            with session.begin_nested():
                merchants.add(merchant)
                session.flush()
        except IntegrityError:
            session.expire_all()
            merchant = _get_demo_merchant(merchants)
            if merchant is None:
                raise

    customers = CustomerRepository(session)
    customer = customers.get_customer(merchant.id, simulator_customer_id())
    if customer is None:
        customer = customers.get_by_external_id(merchant.id, SIMULATOR_CUSTOMER_EXTERNAL_ID)
    if customer is None:
        customer = Customer(
            id=simulator_customer_id(),
            merchant_id=merchant.id,
            external_id=SIMULATOR_CUSTOMER_EXTERNAL_ID,
            email="simulator-customer@example.test",
            full_name="Simulator Customer",
            lifetime_value=Decimal("2500.00"),
        )
        try:
            with session.begin_nested():
                customers.add(customer)
                session.flush()
        except IntegrityError:
            session.expire_all()
            customer = customers.get_customer(merchant.id, simulator_customer_id())
            if customer is None:
                customer = customers.get_by_external_id(merchant.id, SIMULATOR_CUSTOMER_EXTERNAL_ID)
            if customer is None:
                raise
    return merchant, customer


def ensure_alt_simulator_customer(session: Session) -> Customer:
    merchant, _primary = ensure_simulator_fixtures(session)
    customers = CustomerRepository(session)
    customer = customers.get_customer(merchant.id, simulator_alt_customer_id())
    if customer is None:
        customer = customers.get_by_external_id(merchant.id, SIMULATOR_ALT_CUSTOMER_EXTERNAL_ID)
    if customer is None:
        customer = Customer(
            id=simulator_alt_customer_id(),
            merchant_id=merchant.id,
            external_id=SIMULATOR_ALT_CUSTOMER_EXTERNAL_ID,
            email="simulator-customer-alt@example.test",
            full_name="Simulator Customer Alt",
            lifetime_value=Decimal("800.00"),
        )
        try:
            with session.begin_nested():
                customers.add(customer)
                session.flush()
        except IntegrityError:
            session.expire_all()
            customer = customers.get_customer(merchant.id, simulator_alt_customer_id())
            if customer is None:
                customer = customers.get_by_external_id(
                    merchant.id, SIMULATOR_ALT_CUSTOMER_EXTERNAL_ID
                )
            if customer is None:
                raise
    return customer


def ensure_alt_simulator_merchant(session: Session) -> tuple[Merchant, Customer]:
    merchants = MerchantRepository(session)
    merchant = merchants.get_merchant(simulator_alt_merchant_id())
    if merchant is None:
        merchant = merchants.get_by_slug(SIMULATOR_ALT_MERCHANT_SLUG)
    if merchant is None:
        merchant = Merchant(
            id=simulator_alt_merchant_id(),
            name="RecoverAI Demo Merchant Alt",
            slug=SIMULATOR_ALT_MERCHANT_SLUG,
            description="Second merchant for mismatch simulation",
        )
        try:
            with session.begin_nested():
                merchants.add(merchant)
                session.flush()
        except IntegrityError:
            session.expire_all()
            merchant = merchants.get_merchant(simulator_alt_merchant_id())
            if merchant is None:
                merchant = merchants.get_by_slug(SIMULATOR_ALT_MERCHANT_SLUG)
            if merchant is None:
                raise
    customers = CustomerRepository(session)
    customer = customers.get_by_external_id(merchant.id, SIMULATOR_ALT_CUSTOMER_EXTERNAL_ID)
    if customer is None:
        customer = Customer(
            merchant_id=merchant.id,
            external_id=SIMULATOR_ALT_CUSTOMER_EXTERNAL_ID,
            email="alt-merchant-customer@example.test",
            full_name="Alt Merchant Customer",
            lifetime_value=Decimal("100.00"),
        )
        try:
            with session.begin_nested():
                customers.add(customer)
                session.flush()
        except IntegrityError:
            session.expire_all()
            customer = customers.get_by_external_id(merchant.id, SIMULATOR_ALT_CUSTOMER_EXTERNAL_ID)
            if customer is None:
                raise
    return merchant, customer
