from __future__ import annotations

from uuid import UUID


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class IngestionError(DomainError):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(code, message, retryable=False)
        self.http_status = http_status


class InvalidTransitionError(DomainError):
    def __init__(
        self,
        from_status: str,
        to_status: str,
        *,
        case_id: UUID | None = None,
    ) -> None:
        super().__init__(
            "INVALID_STATE_TRANSITION",
            f"Cannot transition recovery case from {from_status} to {to_status}",
            retryable=False,
        )
        self.from_status = from_status
        self.to_status = to_status
        self.case_id = case_id


class ConcurrentCaseUpdateError(DomainError):
    def __init__(self, case_id: UUID) -> None:
        super().__init__(
            "CONCURRENT_CASE_UPDATE",
            f"Recovery case {case_id} was updated concurrently",
            retryable=True,
        )
        self.case_id = case_id


class IdempotencyConflictError(DomainError):
    def __init__(self, key: str) -> None:
        super().__init__(
            "IDEMPOTENCY_KEY_CONFLICT",
            f"Idempotency key {key} was reused with a different request payload",
            retryable=False,
        )
        self.key = key


class ToolValidationError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, retryable=False)


class OptimizerError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, retryable=False)


class AgentError(DomainError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(code, message, retryable=retryable)
