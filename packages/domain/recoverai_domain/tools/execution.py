from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_db.enums import (
    ActorType,
    ApprovalStatus,
    IdempotencyKeyStatus,
    RecoveryActionStatus,
    RecoveryActionType,
    RecoveryCaseStatus,
    ToolCallStatus,
)
from recoverai_db.models import (
    Approval,
    Customer,
    Merchant,
    Payment,
    RecoveryAction,
    RecoveryCase,
    ToolCall,
)
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit
from recoverai_domain.errors import DomainError, IdempotencyConflictError, ToolValidationError
from recoverai_domain.policy_context import build_policy_context
from recoverai_domain.policy_engine import PolicyEngine
from recoverai_domain.policy_types import ProposedAction
from recoverai_domain.recovery_config import RecoverySettings, load_recovery_settings
from recoverai_domain.state_machine import coerce_status, is_terminal
from recoverai_domain.tools.handlers import HANDLERS, HandlerContext, apply_case_outcome
from recoverai_domain.tools.idempotency import (
    begin_idempotent_operation,
    canonical_request_hash,
    complete_idempotent_operation,
    fail_idempotent_operation,
    sanitize_payload,
)
from recoverai_domain.tools.permissions import action_for_tool, parse_action_type, tool_for_action
from recoverai_domain.tools.registry import get_tool_registry
from recoverai_domain.tools.schemas import StrictModel, ToolSpec
from recoverai_domain.transitions import lock_recovery_case, transition_case
from recoverai_providers.base import PaymentProvider
from recoverai_providers.registry import get_payment_provider

SIDE_EFFECT_EXECUTE_STATES = {
    RecoveryCaseStatus.POLICY_CHECK,
    RecoveryCaseStatus.AWAITING_APPROVAL,
    RecoveryCaseStatus.EXECUTING,
    RecoveryCaseStatus.ACTION_COMPLETED,
    RecoveryCaseStatus.RETRY_SCHEDULED,
    RecoveryCaseStatus.NOT_RECOVERED,
    RecoveryCaseStatus.FAILED,
}


@dataclass
class ToolExecutionResult:
    status: str
    tool_name: str
    allowed: bool
    requires_approval: bool
    reason: str
    action_id: UUID | None = None
    approval_id: UUID | None = None
    tool_call_id: UUID | None = None
    provider: str | None = None
    provider_reference: str | None = None
    simulated: bool = True
    policy_version: str | None = None
    idempotency_key: str | None = None
    output: dict[str, Any] | None = None
    risk_level: str | None = None
    replayed: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "tool_name": self.tool_name,
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "action_id": str(self.action_id) if self.action_id else None,
            "approval_id": str(self.approval_id) if self.approval_id else None,
            "tool_call_id": str(self.tool_call_id) if self.tool_call_id else None,
            "provider": self.provider,
            "provider_reference": self.provider_reference,
            "simulated": self.simulated,
            "policy_version": self.policy_version,
            "idempotency_key": self.idempotency_key,
            "output": self.output or {},
            "risk_level": self.risk_level,
            "replayed": self.replayed,
        }


class ToolExecutionService:
    def __init__(
        self,
        session: Session,
        *,
        settings: RecoverySettings | None = None,
        provider: PaymentProvider | None = None,
        queue: Any | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or load_recovery_settings()
        self._provider = provider or get_payment_provider(seed=42)
        self._queue = queue
        self._registry = get_tool_registry()
        self._policy = PolicyEngine(self._settings)

    def evaluate(
        self,
        case_id: UUID,
        action: str,
        *,
        payload: dict[str, Any] | None = None,
        actor_type: str = ActorType.SYSTEM,
        actor_id: str | None = None,
        correlation_id: str | None = None,
        merchant_id: UUID | None = None,
    ) -> dict[str, Any]:
        case = lock_recovery_case(self._session, case_id)
        self._assert_merchant(case, merchant_id)
        try:
            parsed = parse_action_type(action)
        except ValueError as exc:
            raise ToolValidationError(
                "UNKNOWN_ACTION", f"Action {action} is not a valid recovery action"
            ) from exc
        context = build_policy_context(self._session, case, settings=self._settings)
        proposed = _proposed_from_payload(parsed, payload or {})
        result = self._policy.evaluate_and_persist(
            self._session,
            context,
            proposed,
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        return result.to_public_dict()

    def execute(
        self,
        case_id: UUID,
        *,
        tool_name: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str,
        merchant_id: UUID | None = None,
        actor_type: str = ActorType.SYSTEM,
        actor_id: str | None = None,
        correlation_id: str | None = None,
        granted_permissions: frozenset[str] | None = None,
        existing_action_id: UUID | None = None,
        approval_id: UUID | None = None,
        approved_execution: bool = False,
    ) -> ToolExecutionResult:
        started = perf_counter()
        started_at = datetime.now(UTC)
        payload = dict(payload or {})
        spec = self._resolve_tool(tool_name, action)
        validated = self._validate_input(spec, payload)
        case = lock_recovery_case(self._session, case_id)
        self._assert_merchant(case, merchant_id)
        if granted_permissions is not None:
            allowed = {str(item) for item in granted_permissions}
            if str(spec.required_permission) not in allowed:
                raise ToolValidationError(
                    "PERMISSION_DENIED",
                    f"Permission {spec.required_permission} is required for {spec.name}",
                )
        if is_terminal(case.status):
            raise ToolValidationError(
                "CASE_TERMINAL",
                "Tools cannot run on a terminal recovery case and cannot bypass verification",
            )
        customer = self._session.get(Customer, case.customer_id)
        payment = self._session.get(Payment, case.payment_id) if case.payment_id else None

        hash_payload = {
            "tool_name": spec.name,
            "action": str(action_for_tool(spec.name) or action or spec.name),
            "input": validated,
        }
        request_hash = canonical_request_hash(hash_payload)
        idem = begin_idempotent_operation(
            self._session,
            merchant_id=case.merchant_id,
            key=idempotency_key,
            operation=spec.name,
            request_hash=request_hash,
        )
        if idem.replay:
            stored = (idem.record.metadata_json or {}).get("result")
            if idem.record.status == IdempotencyKeyStatus.COMPLETED and isinstance(stored, dict):
                result = _result_from_stored(stored)
                result.replayed = True
                return result
            if (
                idem.record.status == IdempotencyKeyStatus.IN_PROGRESS
                and approved_execution
                and idem.record.request_hash == request_hash
            ):
                pass
            elif idem.record.status == IdempotencyKeyStatus.IN_PROGRESS and isinstance(
                stored, dict
            ):
                result = _result_from_stored(stored)
                result.replayed = True
                return result
            elif idem.record.status == IdempotencyKeyStatus.IN_PROGRESS:
                raise DomainError(
                    "IDEMPOTENCY_IN_PROGRESS",
                    "A matching side-effecting request is already executing",
                    retryable=True,
                )
            elif isinstance(stored, dict):
                result = _result_from_stored(stored)
                result.replayed = True
                return result

        tool_call = ToolCall(
            merchant_id=case.merchant_id,
            recovery_case_id=case.id,
            tool_name=spec.name,
            tool_version=spec.version,
            status=ToolCallStatus.PENDING,
            request_payload=sanitize_payload(
                {
                    **validated,
                    "required_permission": str(spec.required_permission),
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                }
            ),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        self._session.add(tool_call)
        self._session.flush()

        try:
            result = self._run_after_idempotency(
                spec=spec,
                case=case,
                customer=customer,
                payment=payment,
                validated=validated,
                idempotency_key=idempotency_key,
                actor_type=actor_type,
                actor_id=actor_id,
                correlation_id=correlation_id,
                existing_action_id=existing_action_id,
                approval_id=approval_id,
                approved_execution=approved_execution,
                tool_call=tool_call,
            )
        except IdempotencyConflictError:
            raise
        except DomainError as exc:
            fail_idempotent_operation(idem.record, error_code=exc.code)
            self._finish_tool_call(
                tool_call,
                status=ToolCallStatus.FAILED,
                started_at=started_at,
                started=started,
                response={"error": exc.message},
                error_code=exc.code,
                error_message=exc.message,
            )
            raise

        if result.status == "APPROVAL_REQUIRED":
            metadata = dict(idem.record.metadata_json or {})
            metadata["result"] = result.to_public_dict()
            idem.record.metadata_json = metadata
        else:
            complete_idempotent_operation(
                idem.record,
                response=result.to_public_dict(),
                response_reference=str(result.action_id) if result.action_id else str(tool_call.id),
            )
        call_status = _tool_call_status(result.status)
        self._finish_tool_call(
            tool_call,
            status=call_status,
            started_at=started_at,
            started=started,
            response=result.to_public_dict(),
            error_code=None if result.status != "FAILED" else "TOOL_FAILED",
            error_message=result.reason if result.status == "FAILED" else None,
        )
        result.tool_call_id = tool_call.id
        result.idempotency_key = idempotency_key
        return result

    def _run_after_idempotency(
        self,
        *,
        spec: ToolSpec,
        case: RecoveryCase,
        customer: Customer | None,
        payment: Payment | None,
        validated: dict[str, Any],
        idempotency_key: str,
        actor_type: str,
        actor_id: str | None,
        correlation_id: str | None,
        existing_action_id: UUID | None,
        approval_id: UUID | None,
        approved_execution: bool,
        tool_call: ToolCall,
    ) -> ToolExecutionResult:
        action_row: RecoveryAction | None = None
        mapped_action = action_for_tool(spec.name)
        proposed = (
            _proposed_from_payload(mapped_action, validated)
            if mapped_action is not None
            else ProposedAction(action_type="READ_ONLY")
        )
        context = build_policy_context(self._session, case, settings=self._settings)
        if mapped_action is not None:
            evaluation = self._policy.evaluate_and_persist(
                self._session,
                context,
                proposed,
                correlation_id=correlation_id,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        else:
            from recoverai_db.enums import RiskLevel
            from recoverai_domain.policy_types import PolicyEvaluationResult

            evaluation = PolicyEvaluationResult(
                allowed=True,
                requires_approval=False,
                risk_level=RiskLevel.GREEN,
                reason="Read-only tool",
                policy_ids=["read_only"],
                policy_version=context.settings.policy_version,
            )

        if spec.side_effect:
            status = coerce_status(case.status)
            if status not in SIDE_EFFECT_EXECUTE_STATES:
                raise ToolValidationError(
                    "INVALID_CASE_STATE",
                    f"Cannot execute {spec.name} while the case is {case.status}",
                )

        if mapped_action is not None and not evaluation.allowed:
            action_row = self._upsert_action(
                case,
                mapped_action,
                idempotency_key,
                RecoveryActionStatus.BLOCKED,
                evaluation.risk_level,
                existing_action_id,
                error_code="POLICY_DENIED",
                error_message=evaluation.reason,
            )
            record_audit(
                self._session,
                merchant_id=case.merchant_id,
                case_id=case.id,
                event_type=AuditEventType.ACTION_BLOCKED,
                summary=f"Policy blocked {mapped_action}",
                actor_type=actor_type,
                actor_id=actor_id,
                action=str(mapped_action),
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                metadata={
                    "case_id": str(case.id),
                    "merchant_id": str(case.merchant_id),
                    "policy_version": evaluation.policy_version,
                    "action_id": str(action_row.id),
                },
            )
            return ToolExecutionResult(
                status="BLOCKED",
                tool_name=spec.name,
                allowed=False,
                requires_approval=False,
                reason=evaluation.reason,
                action_id=action_row.id,
                policy_version=evaluation.policy_version,
                risk_level=str(evaluation.risk_level),
                output={},
            )

        if mapped_action is not None and evaluation.requires_approval and not approved_execution:
            action_row = self._upsert_action(
                case,
                mapped_action,
                idempotency_key,
                RecoveryActionStatus.APPROVAL_REQUIRED,
                evaluation.risk_level,
                existing_action_id,
                metadata={"payload": validated, "tool_name": spec.name, "executed": False},
            )
            approval = self._create_approval(
                case,
                action_row,
                actor_id=actor_id,
                ttl_minutes=context.settings.approval_ttl_minutes,
                case_version=case.version,
                payload=validated,
                tool_name=spec.name,
                idempotency_key=idempotency_key,
            )
            if coerce_status(case.status) is RecoveryCaseStatus.POLICY_CHECK:
                transition_case(
                    self._session,
                    case,
                    RecoveryCaseStatus.AWAITING_APPROVAL,
                    actor_type=actor_type,
                    correlation_id=correlation_id,
                    summary="Policy requires human approval before tool execution",
                )
            record_audit(
                self._session,
                merchant_id=case.merchant_id,
                case_id=case.id,
                event_type=AuditEventType.APPROVAL_REQUESTED,
                summary=f"Approval requested for {mapped_action}",
                actor_type=actor_type,
                actor_id=actor_id,
                action=str(mapped_action),
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                metadata={
                    "case_id": str(case.id),
                    "merchant_id": str(case.merchant_id),
                    "policy_version": evaluation.policy_version,
                    "approval_id": str(approval.id),
                    "action_id": str(action_row.id),
                },
            )
            return ToolExecutionResult(
                status="APPROVAL_REQUIRED",
                tool_name=spec.name,
                allowed=True,
                requires_approval=True,
                reason=evaluation.reason,
                action_id=action_row.id,
                approval_id=approval.id,
                policy_version=evaluation.policy_version,
                risk_level=str(evaluation.risk_level),
                output={"approval_id": str(approval.id)},
            )

        if approved_execution:
            self._assert_usable_approval(case, approval_id, existing_action_id)

        if spec.side_effect and mapped_action is not None:
            action_row = self._upsert_action(
                case,
                mapped_action,
                idempotency_key,
                RecoveryActionStatus.EXECUTING,
                evaluation.risk_level,
                existing_action_id,
                metadata={"payload": validated, "tool_name": spec.name, "executed": False},
            )
            if spec.name not in {
                "schedule_retry",
                "escalate_to_human",
                "pause_recovery",
            } and coerce_status(case.status) in {
                RecoveryCaseStatus.POLICY_CHECK,
                RecoveryCaseStatus.AWAITING_APPROVAL,
            }:
                transition_case(
                    self._session,
                    case,
                    RecoveryCaseStatus.EXECUTING,
                    actor_type=actor_type,
                    correlation_id=correlation_id,
                    summary="Tool execution started",
                    metadata={"tool_name": spec.name},
                )
            record_audit(
                self._session,
                merchant_id=case.merchant_id,
                case_id=case.id,
                event_type=AuditEventType.ACTION_STARTED,
                summary=f"Started {spec.name}",
                actor_type=actor_type,
                actor_id=actor_id,
                action=str(mapped_action),
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                metadata={
                    "case_id": str(case.id),
                    "merchant_id": str(case.merchant_id),
                    "policy_version": evaluation.policy_version,
                    "action_id": str(action_row.id),
                    "attempt_number": action_row.attempt_number,
                },
            )
        handler = HANDLERS[spec.name]
        handler_ctx = HandlerContext(
            session=self._session,
            case=case,
            merchant_id=case.merchant_id,
            customer=customer,
            payment=payment,
            provider=self._provider,
            payload=validated,
            attempt_number=action_row.attempt_number if action_row is not None else 1,
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            correlation_id=correlation_id,
            queue=self._queue,
        )
        handled = handler(handler_ctx)
        if action_row is not None:
            action_row.provider = handled.provider
            action_row.provider_reference = handled.provider_reference
            if handled.amount is not None:
                action_row.amount = handled.amount
            meta = dict(action_row.metadata_json or {})
            meta.update(handled.metadata)
            executed = bool(meta.get("executed", handled.success))
            meta["executed"] = executed
            if executed:
                action_row.executed_at = datetime.now(UTC)
            action_row.metadata_json = meta
            if handled.success:
                action_row.status = RecoveryActionStatus.SUCCEEDED
                action_row.error_code = None
                action_row.error_message = None
            else:
                action_row.status = RecoveryActionStatus.FAILED
                action_row.error_code = handled.error_code
                action_row.error_message = handled.error_message
            if "scheduled_for" in handled.metadata:
                action_row.scheduled_for = datetime.fromisoformat(handled.metadata["scheduled_for"])

        if handled.success:
            apply_case_outcome(self._session, case, handled, actor_type, correlation_id)
            if spec.side_effect:
                record_audit(
                    self._session,
                    merchant_id=case.merchant_id,
                    case_id=case.id,
                    event_type=AuditEventType.ACTION_SUCCEEDED,
                    summary=f"{spec.name} succeeded",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action=str(mapped_action) if mapped_action else spec.name,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    metadata={
                        "case_id": str(case.id),
                        "merchant_id": str(case.merchant_id),
                        "policy_version": evaluation.policy_version,
                        "provider": handled.provider,
                        "provider_reference": handled.provider_reference,
                    },
                )
            return ToolExecutionResult(
                status="SUCCEEDED",
                tool_name=spec.name,
                allowed=True,
                requires_approval=False,
                reason=evaluation.reason,
                action_id=action_row.id if action_row is not None else None,
                approval_id=approval_id,
                provider=handled.provider,
                provider_reference=handled.provider_reference,
                simulated=handled.simulated,
                policy_version=evaluation.policy_version,
                output=handled.output,
                risk_level=str(evaluation.risk_level),
            )

        if spec.side_effect and coerce_status(case.status) is RecoveryCaseStatus.EXECUTING:
            transition_case(
                self._session,
                case,
                RecoveryCaseStatus.FAILED,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary=handled.error_message or "Tool execution failed",
            )
        record_audit(
            self._session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            event_type=AuditEventType.ACTION_FAILED,
            summary=handled.error_message or f"{spec.name} failed",
            actor_type=actor_type,
            actor_id=actor_id,
            action=str(mapped_action) if mapped_action else spec.name,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            metadata={
                "case_id": str(case.id),
                "merchant_id": str(case.merchant_id),
                "policy_version": evaluation.policy_version,
                "error_code": handled.error_code,
            },
        )
        return ToolExecutionResult(
            status="FAILED",
            tool_name=spec.name,
            allowed=True,
            requires_approval=False,
            reason=handled.error_message or "Tool failed",
            action_id=action_row.id if action_row is not None else None,
            provider=handled.provider,
            policy_version=evaluation.policy_version,
            output=handled.output,
            risk_level=str(evaluation.risk_level),
        )

    def _resolve_tool(self, tool_name: str | None, action: str | None) -> ToolSpec:
        if tool_name:
            return self._registry.require(tool_name)
        if action:
            try:
                parsed = parse_action_type(action)
            except ValueError as exc:
                raise ToolValidationError(
                    "UNKNOWN_ACTION", f"Action {action} is not valid"
                ) from exc
            mapped = tool_for_action(parsed)
            if mapped is None:
                raise ToolValidationError(
                    "UNKNOWN_ACTION", f"Action {action} has no registered tool"
                )
            return self._registry.require(mapped)
        raise ToolValidationError(
            "UNKNOWN_TOOL", "A registered tool or closed action type is required"
        )

    def _validate_input(self, spec: ToolSpec, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            model: StrictModel = spec.input_model.model_validate(payload)
        except ValidationError as exc:
            raise ToolValidationError(
                "INVALID_TOOL_INPUT",
                "Tool input failed schema validation; unsupported fields are rejected",
            ) from exc
        return model.model_dump(mode="json")

    def _assert_merchant(self, case: RecoveryCase, merchant_id: UUID | None) -> None:
        if merchant_id is not None and case.merchant_id != merchant_id:
            raise ToolValidationError(
                "MERCHANT_MISMATCH", "Case does not belong to the given merchant"
            )
        merchant = self._session.get(Merchant, case.merchant_id)
        if merchant is None:
            raise ToolValidationError("MISSING_MERCHANT", "Merchant was not found")

    def _upsert_action(
        self,
        case: RecoveryCase,
        action_type: RecoveryActionType,
        idempotency_key: str,
        status: RecoveryActionStatus,
        risk_level: object,
        existing_action_id: UUID | None,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RecoveryAction:
        existing = None
        if existing_action_id is not None:
            existing = self._session.get(RecoveryAction, existing_action_id)
        if existing is None:
            existing = self._session.scalar(
                select(RecoveryAction).where(
                    RecoveryAction.merchant_id == case.merchant_id,
                    RecoveryAction.idempotency_key == idempotency_key,
                )
            )
        if existing is not None:
            existing.status = str(status)
            existing.error_code = error_code
            existing.error_message = error_message
            if metadata:
                merged = dict(existing.metadata_json or {})
                merged.update(metadata)
                existing.metadata_json = merged
            existing.risk_level = str(risk_level)
            return existing
        attempt = _next_action_attempt(self._session, case.id, action_type)
        row = RecoveryAction(
            merchant_id=case.merchant_id,
            recovery_case_id=case.id,
            action_type=str(action_type),
            status=str(status),
            idempotency_key=idempotency_key,
            attempt_number=attempt,
            risk_level=str(risk_level),
            amount=case.amount_at_risk,
            currency=case.currency,
            error_code=error_code,
            error_message=error_message,
            metadata_json=metadata or {"executed": False},
        )
        self._session.add(row)
        self._session.flush()
        record_audit(
            self._session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            event_type=AuditEventType.ACTION_PLANNED,
            summary=f"Planned {action_type}",
            action=str(action_type),
            idempotency_key=idempotency_key,
            metadata={
                "case_id": str(case.id),
                "merchant_id": str(case.merchant_id),
                "action_id": str(row.id),
            },
        )
        return row

    def _create_approval(
        self,
        case: RecoveryCase,
        action: RecoveryAction,
        *,
        actor_id: str | None,
        ttl_minutes: int,
        case_version: int,
        payload: dict[str, Any],
        tool_name: str,
        idempotency_key: str,
    ) -> Approval:
        from datetime import timedelta

        approval = Approval(
            merchant_id=case.merchant_id,
            recovery_case_id=case.id,
            recovery_action_id=action.id,
            status=ApprovalStatus.PENDING,
            requested_by=actor_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
        )
        self._session.add(approval)
        self._session.flush()
        meta = dict(action.metadata_json or {})
        meta["approval_id"] = str(approval.id)
        meta["case_version"] = case_version
        meta["case_fingerprint"] = _case_fingerprint(case)
        meta["tool_name"] = tool_name
        meta["payload"] = payload
        meta["idempotency_key"] = idempotency_key
        action.metadata_json = meta
        return approval

    def _assert_usable_approval(
        self, case: RecoveryCase, approval_id: UUID | None, action_id: UUID | None
    ) -> None:
        if approval_id is None:
            raise ToolValidationError(
                "APPROVAL_REQUIRED", "Approved execution requires an approval id"
            )
        approval = self._session.get(Approval, approval_id)
        if approval is None or approval.recovery_case_id != case.id:
            raise ToolValidationError("APPROVAL_NOT_FOUND", "Approval was not found for this case")
        if approval.status != ApprovalStatus.APPROVED:
            raise ToolValidationError("APPROVAL_NOT_APPROVED", "Approval is not in APPROVED status")
        if approval.expires_at is not None and approval.expires_at <= datetime.now(UTC):
            approval.status = ApprovalStatus.EXPIRED
            raise ToolValidationError("APPROVAL_EXPIRED", "Approval has expired and cannot execute")
        if action_id is not None:
            action = self._session.get(RecoveryAction, action_id)
            if action is not None:
                fingerprint = (action.metadata_json or {}).get("case_fingerprint")
                if fingerprint and fingerprint != _case_fingerprint(case):
                    raise ToolValidationError(
                        "STALE_APPROVAL",
                        "The recovery case changed materially after approval was requested",
                    )

    def _finish_tool_call(
        self,
        tool_call: ToolCall,
        *,
        status: str,
        started_at: datetime,
        started: float,
        response: dict[str, Any],
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        tool_call.status = status
        tool_call.response_payload = sanitize_payload(response)
        tool_call.latency_ms = int((perf_counter() - started) * 1000)
        tool_call.error_code = error_code
        tool_call.error_message = error_message
        extra = dict(tool_call.request_payload or {})
        extra["started_at"] = started_at.isoformat()
        extra["completed_at"] = datetime.now(UTC).isoformat()
        tool_call.request_payload = extra


def _proposed_from_payload(
    action: RecoveryActionType | str, payload: dict[str, Any]
) -> ProposedAction:
    percent = payload.get("discount_percent")
    return ProposedAction(
        action_type=str(action),
        discount_percent=Decimal(str(percent)) if percent is not None else None,
        channel=payload.get("channel"),
        metadata=payload,
    )


def _next_action_attempt(session: Session, case_id: UUID, action_type: RecoveryActionType) -> int:
    from sqlalchemy import func

    current = session.scalar(
        select(func.max(RecoveryAction.attempt_number)).where(
            RecoveryAction.recovery_case_id == case_id,
            RecoveryAction.action_type == str(action_type),
        )
    )
    return int(current or 0) + 1


def _case_fingerprint(case: RecoveryCase) -> dict[str, Any]:
    return {
        "amount_at_risk": str(case.amount_at_risk),
        "payment_id": str(case.payment_id) if case.payment_id else None,
        "customer_id": str(case.customer_id),
        "last_mismatch_reason": case.last_mismatch_reason,
        "amount_recovered": str(case.amount_recovered),
    }


def _tool_call_status(status: str) -> str:
    mapping = {
        "SUCCEEDED": ToolCallStatus.SUCCESS,
        "FAILED": ToolCallStatus.FAILED,
        "BLOCKED": ToolCallStatus.BLOCKED,
        "APPROVAL_REQUIRED": ToolCallStatus.APPROVAL_REQUIRED,
    }
    return mapping.get(status, ToolCallStatus.SUCCESS)


def _result_from_stored(stored: dict[str, Any]) -> ToolExecutionResult:
    action_id = stored.get("action_id")
    approval_id = stored.get("approval_id")
    tool_call_id = stored.get("tool_call_id")
    return ToolExecutionResult(
        status=str(stored.get("status") or "SUCCEEDED"),
        tool_name=str(stored.get("tool_name") or ""),
        allowed=bool(stored.get("allowed", True)),
        requires_approval=bool(stored.get("requires_approval", False)),
        reason=str(stored.get("reason") or ""),
        action_id=UUID(action_id) if action_id else None,
        approval_id=UUID(approval_id) if approval_id else None,
        tool_call_id=UUID(tool_call_id) if tool_call_id else None,
        provider=stored.get("provider"),
        provider_reference=stored.get("provider_reference"),
        simulated=bool(stored.get("simulated", True)),
        policy_version=stored.get("policy_version"),
        idempotency_key=stored.get("idempotency_key"),
        output=stored.get("output") if isinstance(stored.get("output"), dict) else {},
        risk_level=stored.get("risk_level"),
        replayed=True,
    )
