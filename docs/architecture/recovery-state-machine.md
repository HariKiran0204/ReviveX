# Recovery state machine and verification (Phase 4)

Phase 4 adds a persisted, concurrency-safe recovery lifecycle and a verification engine that credits recovered revenue only when a captured payment **matches** the recovery case.

It does not implement ML, ERV, LLM agents, or Razorpay.

Phase 5 connects this machine to the policy engine and `ToolExecutionService`. See [policy-and-tools.md](policy-and-tools.md). Legal transitions now include `POLICY_CHECK → AWAITING_APPROVAL` and `AWAITING_APPROVAL → EXECUTING | STOPPED | ESCALATED | POLICY_CHECK`.

## States

Starting state: `DETECTED`.

Terminal states: `RECOVERED`, `STOPPED`.

Other states, including `NOT_RECOVERED`, `FAILED`, `RETRY_SCHEDULED`, and `ESCALATED`, remain open (`closed_at` is null) so later phases can retry or stop them.

## Legal transitions

```
DETECTED → TRIAGED
TRIAGED → INVESTIGATING | SCORING
INVESTIGATING → DIAGNOSED
DIAGNOSED → SCORING
SCORING → STRATEGY_SELECTED
STRATEGY_SELECTED → POLICY_CHECK
POLICY_CHECK → EXECUTING | STOPPED | ESCALATED
EXECUTING → ACTION_COMPLETED | FAILED
ACTION_COMPLETED → VERIFYING
VERIFYING → RECOVERED | NOT_RECOVERED | RETRY_SCHEDULED
NOT_RECOVERED → RETRY_SCHEDULED | ESCALATED | STOPPED
FAILED → RETRY_SCHEDULED | ESCALATED | STOPPED
RETRY_SCHEDULED → SCORING
ESCALATED → STOPPED
```

Illegal transitions raise `InvalidTransitionError` (`INVALID_STATE_TRANSITION`) and write `STATE_TRANSITION_REJECTED` audit events. The case row is not mutated.

## Concurrency protection

`process_recovery_case` and `verify_recovery_case` load the case with `SELECT FOR UPDATE` inside a database transaction, then:

1. Validate the current status against the legal graph
2. Apply the new status
3. Increment `recovery_cases.version`
4. Write an audit event
5. Commit

Two workers cannot both advance the same case through an illegal or duplicated transition. The second worker waits for the row lock, then either no-ops (idempotent processor) or rejects the transition.

## Phase 4 processor (deterministic placeholder)

`RecoveryCaseProcessor` walks:

`DETECTED → TRIAGED → INVESTIGATING → DIAGNOSED → SCORING → STRATEGY_SELECTED → POLICY_CHECK`

Deterministic action rule (not ML/ERV):

- `RETRY_LATER` when the linked payment `failure_code` is `TEMPORARY_BANK_ERROR`, `NETWORK_TIMEOUT`, or `INSUFFICIENT_FUNDS`
- otherwise `SEND_PAYMENT_LINK`

If policy requires approval, the case goes `POLICY_CHECK → AWAITING_APPROVAL`. High-value cases no longer skip straight to `ESCALATED` without an approval record.

Otherwise it records a `recovery_actions` row with `status=PENDING`, `metadata.executed=false`, then `POLICY_CHECK → EXECUTING → ACTION_COMPLETED`. No provider financial call is made in the processor. Side effects run only through `ToolExecutionService`.

## Verification rules

`RecoveryVerificationService` does **not** treat `payment.status == CAPTURED` as recovery by itself.

A capture matches a case only if all of the following hold:

1. Merchant IDs match
2. Customer IDs match
3. The payment is the case payment, and `provider_order_id` matches when both are present (wrong-order captures fail with `ORDER_MISMATCH`)
4. Currencies match
5. Payment status is `CAPTURED` and `captured_at` is set
6. Capture time is inside the recovery window
7. The payment has not already been counted on this or another case
8. The same webhook event has not already been verified
9. Captured amount is positive `Decimal`

### Accounting

- `amount_recovered` is `NUMERIC` / `Decimal` only
- `0 <= amount_recovered <= amount_at_risk`
- Partial capture (`₹2,000` on a `₹4,000` case): credit `₹2,000`, leave remaining exposure `₹2,000`, status `NOT_RECOVERED`
- Overpayment (`₹5,000` on a `₹4,000` case): credit `₹4,000`, persist the excess as `capped_overpayment` in audit metadata, status `RECOVERED`. Excess is not recovery revenue.
- Duplicate event / already-counted payment: no additional credit

Only this backend service (and the RQ job that calls it) may change `amount_recovered`. Demo HTTP routes call the same functions; they never assign `status = RECOVERED` directly.

Mismatch reasons: `MERCHANT_MISMATCH`, `CUSTOMER_MISMATCH`, `ORDER_MISMATCH`, `PAYMENT_MISMATCH`, `AMOUNT_MISMATCH`, `CURRENCY_MISMATCH`, `OUTSIDE_RECOVERY_WINDOW`, `ALREADY_COUNTED`, `DUPLICATE_EVENT`, `NOT_CAPTURED`, `UNKNOWN`.

The last mismatch is stored on `recovery_cases.last_mismatch_reason`. Successful credit stores `verified_payment_id` and `verified_webhook_event_id`.

Wrong-source example: case for merchant A / customer A / order A / ₹4,000, capture for order B / ₹4,000 → verification fails, case is `NOT_RECOVERED`, no recovered revenue.

## Recovery window

Configuration (not hardcoded in match branches):

| Variable | Default | Meaning |
| --- | --- | --- |
| `RECOVERY_WINDOW_HOURS` | `72` | Capture must be at or before `opened_at + window` |
| `RECOVERY_ORDERING_GRACE_MINUTES` | `60` | Capture may be slightly **before** `opened_at` to absorb webhook reordering |

Valid capture time: `[opened_at - grace, opened_at + window]`.

## Event ordering

Capture and failure events can arrive in any order.

- Payments and webhook rows are always persisted first
- A `CAPTURED` payment is not downgraded to `FAILED` if a late failure event arrives
- If a case is created after a capture, verification can still match that payment
- HTTP webhook handlers only persist + enqueue; verification runs in `verify_recovery_case`

## Workers

- `process_provider_event` — existing ingestion; after commit, enqueues `process_recovery_case` / `verify_recovery_case` follow-ups
- `process_recovery_case` — deterministic lifecycle
- `verify_recovery_case` — lock, verify, persist amount + status + audit

Transient `OperationalError` and `CONCURRENT_CASE_UPDATE` are retryable. Permanent domain errors are not retried endlessly (`WORKER_MAX_RETRIES`, default 3).

## Development endpoints

- `POST /v1/recovery-cases/{id}/process` — runs `RecoveryCaseProcessor`
- `POST /v1/recovery-cases/{id}/verify` — runs `RecoveryVerificationService`

Simulator scenarios: `G` valid recovery, `H` wrong order, `I` wrong customer, `J` wrong merchant, `K` partial, `L` duplicate capture, `M` delayed capture, `N` capture before case, `O` already-counted setup (same as G).
