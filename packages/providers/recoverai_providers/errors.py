from __future__ import annotations


class ProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderCapabilityError(ProviderError):
    def __init__(self, capability: str, provider: str) -> None:
        super().__init__(
            "PROVIDER_CAPABILITY_UNSUPPORTED",
            f"Provider {provider} does not support {capability}",
        )
        self.capability = capability
        self.provider = provider


class ProviderNotFoundError(ProviderError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__("PROVIDER_RESOURCE_NOT_FOUND", f"{resource} {resource_id} was not found")
