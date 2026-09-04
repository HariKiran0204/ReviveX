from __future__ import annotations

import random
import threading
from datetime import UTC, datetime

from recoverai_db.enums import PaymentStatus
from recoverai_providers.base import PaymentProvider
from recoverai_providers.errors import ProviderError, ProviderNotFoundError
from recoverai_providers.models import (
    CreateOrderRequest,
    CreatePaymentLinkRequest,
    CreatePaymentRequest,
    OrderSnapshot,
    PaymentLinkSnapshot,
    PaymentSnapshot,
    ProviderName,
    RefundPaymentRequest,
)
from recoverai_providers.simulator.events import (
    deterministic_order_id,
    deterministic_payment_id,
    deterministic_payment_link_id,
)
from recoverai_providers.simulator.outcomes import roll_attempt_outcome


class LocalSimulationProvider(PaymentProvider):
    """In-memory payment simulator. Not a Razorpay stand-in."""

    name = ProviderName.SIMULATOR

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._lock = threading.RLock()
        self._sequence = 0
        self._orders: dict[str, OrderSnapshot] = {}
        self._payments: dict[str, PaymentSnapshot] = {}
        self._order_payments: dict[str, list[str]] = {}
        self._payment_links: dict[str, PaymentLinkSnapshot] = {}

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _rng(self, *parts: object) -> random.Random:
        material = ":".join(str(part) for part in (self.seed, *parts))
        return random.Random(material)

    def create_order(self, request: CreateOrderRequest) -> OrderSnapshot:
        with self._lock:
            sequence = self._next_sequence()
            provider_order_id = deterministic_order_id(
                self.seed, request.merchant_reference, sequence
            )
            order = OrderSnapshot(
                provider=self.name,
                provider_order_id=provider_order_id,
                merchant_reference=request.merchant_reference,
                amount=request.amount,
                currency=request.currency,
                status=PaymentStatus.CREATED,
                metadata=dict(request.metadata),
            )
            self._orders[provider_order_id] = order
            self._order_payments.setdefault(provider_order_id, [])
            return order

    def create_payment(self, request: CreatePaymentRequest) -> PaymentSnapshot:
        with self._lock:
            sequence = self._next_sequence()
            provider_payment_id = deterministic_payment_id(
                self.seed, request.merchant_reference, sequence
            )
            provider_order_id = request.provider_order_id
            if provider_order_id is None:
                order = self.create_order(
                    CreateOrderRequest(
                        merchant_reference=request.merchant_reference,
                        amount=request.amount,
                        currency=request.currency,
                        customer_reference=request.customer_reference,
                    )
                )
                provider_order_id = order.provider_order_id
            elif provider_order_id not in self._orders:
                self._orders[provider_order_id] = OrderSnapshot(
                    provider=self.name,
                    provider_order_id=provider_order_id,
                    merchant_reference=request.merchant_reference,
                    amount=request.amount,
                    currency=request.currency,
                    status=PaymentStatus.CREATED,
                )

            rng = self._rng(provider_payment_id, request.attempt_number)
            status, failure_reason = roll_attempt_outcome(
                rng,
                failure_reason=request.failure_reason,
                attempt_number=request.attempt_number,
                history=request.customer_history,
                intended_status=request.intended_status,
            )
            snapshot = PaymentSnapshot(
                provider=self.name,
                provider_payment_id=provider_payment_id,
                provider_order_id=provider_order_id,
                merchant_reference=request.merchant_reference,
                amount=request.amount,
                currency=request.currency,
                status=status,
                attempt_number=request.attempt_number,
                failure_reason=failure_reason,
                occurred_at=datetime.now(UTC),
                metadata=dict(request.metadata),
            )
            self._payments[provider_payment_id] = snapshot
            self._order_payments.setdefault(provider_order_id, []).append(provider_payment_id)
            return snapshot

    def fetch_payment(self, provider_payment_id: str) -> PaymentSnapshot:
        with self._lock:
            payment = self._payments.get(provider_payment_id)
            if payment is None:
                raise ProviderNotFoundError("payment", provider_payment_id)
            return payment

    def fetch_order_payments(self, provider_order_id: str) -> list[PaymentSnapshot]:
        with self._lock:
            if (
                provider_order_id not in self._orders
                and provider_order_id not in self._order_payments
            ):
                raise ProviderNotFoundError("order", provider_order_id)
            ids = self._order_payments.get(provider_order_id, [])
            return [
                self._payments[payment_id] for payment_id in ids if payment_id in self._payments
            ]

    def refund_payment(self, request: RefundPaymentRequest) -> PaymentSnapshot:
        with self._lock:
            payment = self._payments.get(request.provider_payment_id)
            if payment is None:
                raise ProviderNotFoundError("payment", request.provider_payment_id)
            if payment.status not in {PaymentStatus.CAPTURED, PaymentStatus.AUTHORIZED}:
                raise ProviderError(
                    "PROVIDER_REFUND_INVALID_STATE",
                    f"Cannot refund payment in status {payment.status}",
                )
            refunded = payment.model_copy(
                update={
                    "status": PaymentStatus.REFUNDED,
                    "occurred_at": datetime.now(UTC),
                    "failure_reason": None,
                }
            )
            self._payments[request.provider_payment_id] = refunded
            return refunded

    def create_payment_link(self, request: CreatePaymentLinkRequest) -> PaymentLinkSnapshot:
        with self._lock:
            sequence = self._next_sequence()
            link_id = deterministic_payment_link_id(self.seed, request.merchant_reference, sequence)
            snapshot = PaymentLinkSnapshot(
                provider=self.name,
                provider_payment_link_id=link_id,
                merchant_reference=request.merchant_reference,
                amount=request.amount,
                currency=request.currency,
                status="CREATED",
                url=f"sim://payment-link/{link_id}",
                simulated=True,
                metadata={
                    **dict(request.metadata),
                    "simulated": True,
                    "description": request.description,
                    "customer_reference": request.customer_reference,
                },
            )
            self._payment_links[link_id] = snapshot
            return snapshot

    def fetch_payment_link(self, provider_payment_link_id: str) -> PaymentLinkSnapshot:
        with self._lock:
            link = self._payment_links.get(provider_payment_link_id)
            if link is None:
                raise ProviderNotFoundError("payment_link", provider_payment_link_id)
            return link

    def cancel_payment_link(self, provider_payment_link_id: str) -> PaymentLinkSnapshot:
        with self._lock:
            link = self._payment_links.get(provider_payment_link_id)
            if link is None:
                raise ProviderNotFoundError("payment_link", provider_payment_link_id)
            cancelled = link.model_copy(update={"status": "CANCELLED"})
            self._payment_links[provider_payment_link_id] = cancelled
            return cancelled
