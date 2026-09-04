# ADR-0004: Deterministic policy and tool execution

**Status:** Accepted  
**Date:** 2026-09-04  
**Phase:** 5 — Policy engine, tool registry, safe side effects, human approval

## Context

Phase 4 can walk a recovery case to a planned action and can verify captured payments. It still has no execution boundary for side effects. Later phases will introduce ML scores, an ERV optimizer, and LLM agents. Those components must be able to **propose** interventions without being able to charge a customer, send money, or mark revenue recovered.

Duplicates, retries, and two workers racing the same case are expected. A second “retry” with the same idempotency key must not create a second provider payment.

## Decisions

### Policy is deterministic and fail-closed

`PolicyEngine.evaluate_action` is ordinary, inspectable Python. The same context and proposed action always yield the same allow / approve / block decision. Unknown actions are denied. Merchant settings and environment variables configure thresholds; tools do not hard-code those rules.

Evaluations are appended to `policy_evaluations` and never overwritten, so a later policy change cannot erase why an action was allowed or blocked.

### AI cannot bypass policy

Agents will call `ToolExecutionService`, not `PaymentProvider`. The service always evaluates policy (and re-evaluates after human approval). Customer-supplied text has no authority. Tool input models reject extra fields so a prompt cannot smuggle `ignore_policy`.

### Tools are the only side-effect boundary

Registered tools are the only code path that may call `PaymentProvider` or write notifications, discounts, and scheduled actions. Read-only tools exist so agents can inspect context without executing. There is no “just this once” provider call from an HTTP handler or an LLM.

### Approval re-enters the same execution path

`approve_action` records the human decision and then calls `ToolExecutionService.execute(..., approved_execution=True)`. It does not invoke the simulator or Razorpay itself. If policy, case fingerprint, or expiry has changed, execution is blocked. That keeps approval from becoming a second, weaker control plane.

### Idempotency is mandatory

Side effects are keyed by `(merchant_id, idempotency_key)` plus a request hash. Replays return the original effective result. A reused key with a different payload is a conflict. Case row locks plus the unique idempotency constraint serialize concurrent workers.

### Verification owns recovered revenue

Successful tools record provider references and action success. They never assign `status = RECOVERED` or increment `amount_recovered`. Phase 4’s `RecoveryVerificationService` remains the only credit path.

## Consequences

- Phase 6+ can add probability models and agents on top of this API without teaching them PSP details.
- The simulator can grow payment-link and retry behavior without pretending to be Razorpay.
- Operators can refuse or expire pending actions without forging recovery metrics.

## Alternatives considered

- Letting the LLM call provider adapters: rejected — prompt injection and unbounded side effects.
- Encoding policy inside each tool: rejected — inconsistent fail-open risk and undebuggable duplicates.
- Treating approval as “run this SQL / provider call now”: rejected — skips revalidation.
- Crediting recovery when `create_payment` returns `CAPTURED`: rejected — ADR-0003.
