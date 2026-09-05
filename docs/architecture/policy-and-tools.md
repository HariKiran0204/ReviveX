# Policy engine and tool execution (Phase 5)

Phase 5 adds the **safe execution layer** that later AI agents will call. It does not add ML, ERV, LLM agents, or Razorpay.

## Core principle

```
LLM/agent proposes
→ policy evaluates
→ approval may be required
→ ToolExecutionService executes
→ PaymentProvider performs the side effect
→ provider/domain events record outcome
→ RecoveryVerificationService determines recovery
```

The LLM never mutates payment state, never marks a case recovered, never changes `amount_recovered`, never bypasses policy, and never calls a provider API directly.

Only registered tools may execute side effects. Only `RecoveryVerificationService` may credit recovered revenue.

## Policy flow

`PolicyEngine.evaluate_action(context, proposed_action)` is deterministic and fail-closed.

1. Unknown action types are rejected (`closed_action_enum`) before any tool runs.
2. Merchant `settings.policy` overrides environment defaults.
3. Every evaluation is **inserted** into `policy_evaluations` (append-only).
4. Tools do not embed policy branches; they execute an already-authorized action.

### Risk levels

| Level | Meaning |
| --- | --- |
| GREEN | Low-value automatic action may execute when other rules allow |
| YELLOW | Medium-value or bounded commercial action; approval required when the value threshold says so |
| RED | High-value, blocked, kill-switched, or suspicious. Automatic recovery is prohibited when `allowed` is false |

### Default demo policy

| Rule | Default | Effect |
| --- | --- | --- |
| `max_retry_attempts` | 3 | Block further retries |
| `max_discount_percent` | 10 | Block larger discounts |
| `max_daily_discount_budget` | ₹5,000 | Block when the day’s discounts would exceed the budget |
| `medium_value_approval_threshold` | ₹5,000 | YELLOW + approval |
| `high_value_approval_threshold` | ₹25,000 | RED + approval |
| Communication frequency | 3 / 24h | Block extra notifications |
| Quiet hours | 21:00–08:00 UTC | Block `SEND_REMINDER` |
| Customer opt-out | customer metadata | Block communication actions |
| Blocked action types | merchant list | Block listed `RecoveryActionType` values |
| Automatic recovery kill switch | enabled | Block automatic actions when disabled |
| Suspicious / source mismatch | case `last_mismatch_reason` or customer flags | RED, automatic recovery prohibited |

Low-value temporary payment failure: GREEN, may execute. Kill switch, opt-out, retry cap, discount cap, and source mismatch still fail closed.

## Closed action enum

Valid recovery actions remain:

`RETRY_NOW`, `RETRY_LATER`, `SEND_PAYMENT_LINK`, `SEND_REMINDER`, `OFFER_DISCOUNT`, `ESCALATE`, `DO_NOTHING`

Agents cannot invent actions. Unknown strings are rejected before execution.

## Tool registry

Tools are explicit. Each spec has `name`, `version`, `description`, input schema (`extra=forbid`), output schema, risk level, required permission, timeout, and `side_effect`.

Side-effecting tools (Phase 5 priority):

| Tool | Action | Provider |
| --- | --- | --- |
| `retry_payment` | `RETRY_NOW` | `PaymentProvider.create_payment` — **new** attempt/id |
| `schedule_retry` | `RETRY_LATER` | Local schedule only; not executed now |
| `create_payment_link` | `SEND_PAYMENT_LINK` | Simulator `plink_sim_…` / `sim://` URL |
| `send_notification` | `SEND_REMINDER` | Simulated `notifications` row |
| `offer_discount` | `OFFER_DISCOUNT` | Bounded record; no ERV |
| `escalate_to_human` | `ESCALATE` | Case → `ESCALATED`; no recovery credit |
| `pause_recovery` | `DO_NOTHING` | Case → `STOPPED` |

Read-only tools exist with simple implementations (`get_*`, `check_*`, `calculate_recovery_probability` scores `P(recovery | case, action)` and does not execute an intervention).

Permissions are persisted on tool calls (`VIEW_RECOVERY`, `RETRY_PAYMENT`, `APPROVE_RECOVERY_ACTION`, …). Demo auth does not enforce full RBAC.

## Tool lifecycle and execution

`ToolExecutionService`:

1. Validate registered tool  
2. Validate input schema (unsupported fields rejected)  
3. Lock case, verify merchant  
4. Evaluate policy and persist the evaluation  
5. Enforce approval when required  
6. Enforce idempotency (`merchant_id` + key + request hash)  
7. Call `PaymentProvider` (never the simulator type from domain code)  
8. Record `tool_calls`, `recovery_actions`, audit events  
9. Return a structured result  

Action statuses: `PENDING` / `PLANNED` → `APPROVAL_REQUIRED` → `APPROVED` → `EXECUTING` → `SUCCEEDED` / `FAILED` / `BLOCKED` / `CANCELLED`.

The Phase 4 processor still walks `DETECTED → … → POLICY_CHECK`. GREEN allowed actions are recorded as planned `PENDING` and the case is moved `EXECUTING → ACTION_COMPLETED` **without** a provider call so verification from earlier phases still works. Real side effects happen only through `ToolExecutionService`.

`POLICY_CHECK → AWAITING_APPROVAL` when policy requires a human.

## Approval flow

When `requires_approval` is true the tool does **not** execute.

1. Create `approvals` row with TTL (`APPROVAL_TTL_MINUTES`, default 60)  
2. Mark the action `APPROVAL_REQUIRED`  
3. Audit `APPROVAL_REQUESTED`  
4. Return `APPROVAL_REQUIRED`

`approve_action()` marks the approval `APPROVED` and **re-enters** `ToolExecutionService` with `approved_execution=True`. That path revalidates the case, policy, and idempotency, then executes the tool. Approval never calls the provider itself.

Expired, rejected, or stale approvals (material case fingerprint change: amount, payment, customer, mismatch, recovered amount) cannot execute.

`reject_action()` / operator cancel marks the action `CANCELLED` and escalates the case. It cannot bypass verification or credit recovery.

## Idempotency

`idempotency_keys` is unique on `(merchant_id, key)`.

- Same key + same request hash → replay the stored result; no second provider call  
- Same key + different hash → `IDEMPOTENCY_KEY_CONFLICT`  
- Concurrent workers lock the case row and the idempotency row  

Approval-required attempts keep the key `IN_PROGRESS` until the approved execution completes or the request is rejected.

## Provider separation

Domain tools call `PaymentProvider`. The local simulator implements `create_payment_link` honestly (`provider=SIMULATOR`, `simulated=true`). Razorpay remains unimplemented.

`retry_payment` does **not** retry the original failed provider payment id. It creates a new simulated payment. The original row stays historical.

Provider exceptions become structured tool failures. A function returning without raising is not enough: handlers inspect snapshots. Tools never set `amount_recovered`.

## Security

Customer notes and other natural-language fields are untrusted. They are not parsed into commands. Tool schemas reject unknown fields (`extra=forbid`). Secrets, API keys, and card data are stripped before persistence. Tool payloads store summaries, not chain-of-thought.

## Failure handling

| Condition | Result |
| --- | --- |
| Unknown tool / action | Rejected, no side effect |
| Policy deny | Action `BLOCKED`, audit `ACTION_BLOCKED` |
| Approval required | No provider call |
| Provider error | Action `FAILED`, case `FAILED` if it had entered `EXECUTING` |
| Terminal case | Tools refused |
| Idempotency conflict | HTTP 409 / domain error |

## Development endpoints

These call domain services; they do not assign statuses in the router.

- `POST /v1/recovery-cases/{id}/actions/evaluate`  
- `POST /v1/recovery-cases/{id}/actions/execute`  
- `POST /v1/recovery-cases/{id}/actions/{action_id}/execute`  
- `POST /v1/recovery-cases/{id}/actions/{action_id}/approve`  
- `POST /v1/recovery-cases/{id}/actions/{action_id}/reject`  
