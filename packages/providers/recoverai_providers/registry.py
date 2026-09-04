from __future__ import annotations

from recoverai_providers.base import PaymentProvider
from recoverai_providers.errors import ProviderError
from recoverai_providers.models import ProviderName
from recoverai_providers.simulator.provider import LocalSimulationProvider


def get_payment_provider(name: str | None = None, *, seed: int = 42) -> PaymentProvider:
    resolved = (name or ProviderName.SIMULATOR).upper()
    if resolved in {ProviderName.SIMULATOR, "SIMULATOR", "LOCAL", "LOCAL_SIMULATION"}:
        return LocalSimulationProvider(seed=seed)
    raise ProviderError(
        "PROVIDER_NOT_CONFIGURED",
        f"Payment provider {resolved} is not available. Razorpay is not implemented in Phase 5.",
    )
