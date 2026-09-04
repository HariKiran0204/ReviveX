# ADR-0003: Recovery verification is separate from capture

**Status:** Accepted  
**Date:** 2026-09-03  
**Phase:** 4 — Recovery state machine and verification

## Context

Phase 3 correctly updates a payment to `CAPTURED` when a capture event arrives, and it explicitly does **not** mark the linked recovery case `RECOVERED`. Operators and later metrics must not treat “a capture happened” as “this failed payment was recovered.”

Captures can be for a different order, customer, or merchant; they can be duplicates; they can arrive before the case exists; they can be partial or larger than `amount_at_risk`.

## Decision

### Capture is not recovery

A captured payment is evidence. Recovered revenue is a **verified match** between that evidence and a recovery case. Matching is implemented in `RecoveryVerificationService`, not in webhook HTTP handlers and not in payment-status updates.

### Verification is a separate, idempotent operation

`verify_recovery_case` locks the case, evaluates explicit rules, and then either credits `amount_recovered` or records a mismatch. Re-processing the same capture event or the same counted payment does not increase recovered revenue.

### Recovered money is credited only after matching evidence

`amount_recovered` is a `Decimal` / `NUMERIC` column. It changes only in backend domain logic. Frontend and demo routes must call that logic; they must not set `status = RECOVERED` themselves.

### Payment event ordering cannot be trusted

Webhook `received_at` is not the business time. Capture may be persisted before the recovery case exists. The system keeps the payment row and verifies later, with a configured recovery window plus a short ordering grace.

### Financial state changes are backend-only

No client-supplied recovered amount is accepted. Partial captures credit only the captured amount. Overpayment is capped at `amount_at_risk`. Wrong-order captures fail closed (`ORDER_MISMATCH`) with no credit and no automatic refund in this phase.

## Consequences

- Phase 3 ingestion tests remain valid: processing a capture webhook still does not recover until verification runs
- Metrics in later phases can be derived from persisted `amount_recovered` and `RECOVERED` cases
- A full policy engine, tools, ML, and ERV can replace the Phase 4 placeholder processor without changing these verification invariants

## Alternatives considered

- Setting `RECOVERED` inside capture handling: rejected — conflates provider state with recovery accounting
- Trusting `payment.status == CAPTURED` alone: rejected — insufficient against wrong-source payments
- Crediting the captured amount even when it exceeds `amount_at_risk`: rejected — silent over-count
