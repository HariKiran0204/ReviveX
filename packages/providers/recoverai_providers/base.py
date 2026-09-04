from __future__ import annotations

from abc import ABC, abstractmethod

from recoverai_providers.errors import ProviderCapabilityError
from recoverai_providers.models import (
    CreateOrderRequest,
    CreatePaymentLinkRequest,
    CreatePaymentRequest,
    OrderSnapshot,
    PaymentLinkSnapshot,
    PaymentSnapshot,
    RefundPaymentRequest,
)


class PaymentProvider(ABC):
    """Provider-neutral payment operations. SDKs must not leak through this boundary."""

    name: str

    @abstractmethod
    def create_order(self, request: CreateOrderRequest) -> OrderSnapshot:
        raise NotImplementedError

    @abstractmethod
    def create_payment(self, request: CreatePaymentRequest) -> PaymentSnapshot:
        raise NotImplementedError

    @abstractmethod
    def fetch_payment(self, provider_payment_id: str) -> PaymentSnapshot:
        raise NotImplementedError

    @abstractmethod
    def fetch_order_payments(self, provider_order_id: str) -> list[PaymentSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def refund_payment(self, request: RefundPaymentRequest) -> PaymentSnapshot:
        raise NotImplementedError

    def create_payment_link(self, request: CreatePaymentLinkRequest) -> PaymentLinkSnapshot:
        raise ProviderCapabilityError("create_payment_link", self.name)

    def fetch_payment_link(self, provider_payment_link_id: str) -> PaymentLinkSnapshot:
        raise ProviderCapabilityError("fetch_payment_link", self.name)

    def cancel_payment_link(self, provider_payment_link_id: str) -> PaymentLinkSnapshot:
        raise ProviderCapabilityError("cancel_payment_link", self.name)

    def fetch_subscription(self, *_args: object, **_kwargs: object) -> object:
        raise ProviderCapabilityError("fetch_subscription", self.name)
