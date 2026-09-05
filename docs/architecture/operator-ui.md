# Operator UI (Phase 9)

The Next.js app is the merchant **view and control surface**. PostgreSQL remains the source of truth. The browser never writes `amount_recovered`, payment status, or verification status.

## Surfaces

| Page | API |
| --- | --- |
| Command Center | `GET /v1/metrics/command-center` |
| Recovery Cases | `GET /v1/recovery-cases` (paginated, filtered, sorted) |
| Case Detail | `GET /v1/recovery-cases/{id}` plus `/decision`, `/timeline`, `/agent-runs`, `/tool-calls` |
| Approvals | `GET /v1/approvals`, `POST /v1/approvals/{id}/approve\|reject\|cancel` |
| Policies | `GET /v1/policy`, `PATCH /v1/policy` |
| Audit | `GET /v1/audit-events` |
| Evaluation | `GET /v1/evaluation/latest` |
| System Health | `GET /v1/system-health` |
| Live demo | `POST /v1/operator/demo` |

Typed access lives in `apps/web/lib/api/`. Components do not call `fetch` directly.

## Real vs expected vs synthetic

- **Actual recovered revenue** is `sum(recovery_cases.amount_recovered)` after `RecoveryVerificationService`.
- **Revenue at risk** is remaining exposure on open cases (`amount_at_risk - amount_recovered`).
- **Expected recovery** is the latest ERV `selected_expected_value`. It is labeled expected, never mixed into recovered revenue.
- **Evaluation Center** metrics are held-out **synthetic/simulation** scores from Phase 6 artifacts. They are not Razorpay production results.

## Live updates

There is no second event bus. Case Detail polls `GET /v1/recovery-cases/{id}/timeline?since=` every 8 seconds against existing `audit_events`. Workflow labels such as `RECOVERY_CASE_CREATED`, `APPROVAL_REQUESTED`, and `RECOVERY_VERIFIED` are those audit types.

## Demo controls

Command Center buttons call `POST /v1/operator/demo` with `kind`:

- `run_demo` — failed payment + case processing
- `failed_payment` — DETECTED case only
- `approval` — high-value retry that requires human approval
- `policy_block` — discount above `max_discount_percent`
- `verification_mismatch` — scenario H (wrong order)

The endpoint uses the existing simulator, ingestion, processor, policy, and tool services.

## Health honesty

`GET /v1/system-health` reports API, database, Redis, RQ workers, payment provider, and LLM. The stub LLM is **unavailable** (deterministic fallback). Razorpay is **unavailable** until Phase 10. Missing workers are **unavailable**, not healthy.

## Financial rule

No operator route updates `amount_recovered`. Approve/reject/cancel go through `ApprovalService` / `ToolExecutionService`. Policy PATCH updates `merchants.settings.policy` only; `PolicyEngine` still evaluates every action.
