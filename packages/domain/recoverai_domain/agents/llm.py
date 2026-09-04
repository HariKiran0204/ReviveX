from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from recoverai_domain.agents.config import AgentSettings
from recoverai_domain.errors import AgentError


class LlmError(AgentError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, retryable=code in {"LLM_TIMEOUT", "LLM_UNAVAILABLE"})


@dataclass(frozen=True)
class LlmRequest:
    agent_name: str
    system: str
    constraints: str
    output_schema: str
    user: str
    timeout_seconds: float


@dataclass(frozen=True)
class LlmResponse:
    text: str
    latency_ms: int
    provider: str
    raw: dict[str, Any] = field(default_factory=dict)


class LlmClient(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse: ...


class StubLlmClient:
    """Default Phase 8 provider. Always unavailable so deterministic fallback runs."""

    provider_name = "stub"

    def complete(self, request: LlmRequest) -> LlmResponse:
        del request
        raise LlmError("LLM_UNAVAILABLE", "LLM provider is stubbed; using deterministic fallback")


class ScriptedLlmClient:
    """Test double. Maps agent_name to a JSON object, timeout, or invalid text."""

    provider_name = "scripted"

    def __init__(self, scripts: dict[str, Any], *, delay_seconds: float = 0.0) -> None:
        self.scripts = scripts
        self.delay_seconds = delay_seconds
        self.calls: list[LlmRequest] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        started = perf_counter()
        self.calls.append(request)
        if self.delay_seconds > request.timeout_seconds:
            raise LlmError("LLM_TIMEOUT", f"LLM timed out after {request.timeout_seconds}s")
        payload = self.scripts.get(request.agent_name)
        if payload is None:
            raise LlmError("LLM_UNAVAILABLE", f"No script for {request.agent_name}")
        if payload == "timeout":
            raise LlmError("LLM_TIMEOUT", "Scripted LLM timeout")
        if payload == "invalid":
            text = "this is not valid json {"
        elif isinstance(payload, str):
            text = payload
        else:
            text = json.dumps(payload)
        latency = int((perf_counter() - started) * 1000)
        return LlmResponse(text=text, latency_ms=latency, provider=self.provider_name)


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LlmError("INVALID_LLM_OUTPUT", "LLM did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise LlmError("INVALID_LLM_OUTPUT", "LLM JSON must be an object")
    return parsed


def get_llm_client(settings: AgentSettings | None = None) -> LlmClient:
    del settings
    return StubLlmClient()
