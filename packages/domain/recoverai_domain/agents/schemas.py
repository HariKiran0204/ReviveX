from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from recoverai_db.enums import RecoveryCaseType
from recoverai_domain.optimizer.config import LEGAL_ACTIONS

AgentSource = Literal["LLM", "DETERMINISTIC_FALLBACK"]
Recoverability = Literal["HIGH", "MEDIUM", "LOW", "UNRECOVERABLE"]
Severity = Literal["LOW", "MEDIUM", "HIGH"]


class StrictAgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TriageResult(StrictAgentModel):
    case_type: RecoveryCaseType
    severity: Severity
    investigation_needed: bool
    relevant_context: list[str] = Field(default_factory=list)
    source: AgentSource
    agent_version: str


class DiagnosisResult(StrictAgentModel):
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    recoverability: Recoverability
    source: AgentSource
    agent_version: str

    @field_validator("root_cause")
    @classmethod
    def root_cause_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("root_cause is required")
        return value.strip()


class StrategyResult(StrictAgentModel):
    candidate_actions: list[str]
    rationale: str
    source: AgentSource
    agent_version: str

    @field_validator("candidate_actions")
    @classmethod
    def closed_enum_only(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("candidate_actions must not be empty")
        unique: list[str] = []
        seen: set[str] = set()
        for raw in value:
            action = str(raw)
            if action not in LEGAL_ACTIONS:
                raise ValueError(f"Illegal recovery action: {action}")
            if action in seen:
                continue
            seen.add(action)
            unique.append(action)
        return unique


class DecisionExplanation(StrictAgentModel):
    observed: str
    candidate_comparison: str
    selected_action: str | None
    policy: str
    reason: str
    source: AgentSource
    agent_version: str


class VerificationExplanation(StrictAgentModel):
    matched: bool
    summary: str
    mismatch_reason: str | None = None
    source: AgentSource
    agent_version: str


class AnalystAnswer(StrictAgentModel):
    question: str
    answer: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    source: AgentSource
    agent_version: str


class OrchestrationResult(StrictAgentModel):
    case_id: str
    merchant_id: str
    case_status: str
    triage: TriageResult
    diagnosis: DiagnosisResult
    strategy: StrategyResult
    selected_action: str | None
    selected_expected_value: str | None
    requires_approval: bool
    explanation: DecisionExplanation
    execution_status: str | None = None
    approval_id: str | None = None
    optimization: dict[str, Any] = Field(default_factory=dict)
    verification_explanation: VerificationExplanation | None = None
    steps_used: int
    tool_calls_used: int
    orchestrator_run_id: str | None = None
    amount_recovered: str
    fallbacks: list[str] = Field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
