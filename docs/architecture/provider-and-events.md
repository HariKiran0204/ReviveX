# Provider abstraction and event ingestion (Phase 3)

Phase 3 adds a provider-neutral payment adapter, a local simulator (default), asynchronous webhook ingestion, and the first business side effect: a `DETECTED` recovery case when a payment fails.

Razorpay is not implemented. The simulator does not impersonate Razorpay.

## Provider abstraction

Package: `packages/providers/recoverai_providers/`

`PaymentProvider` exposes only operations the application needs:

| Method | Simulator |
| --- | --- |
| `create_order` | In-memory order |
| `create_payment` | Deterministic lifecycle attempt |
| `fetch_payment` | In-memory lookup |
| `fetch_order_payments` | In-memory lookup |
| `refund_payment` | Local status → `REFUNDED` |
| `create_payment_link` / `fetch_payment_link` / `cancel_payment_link` / `fetch_subscription` | `ProviderCapabilityError` |

Request/response objects are Pydantic models (`OrderSnapshot`, `PaymentSnapshot`, `ProviderEvent`). Provider SDKs must not cross this boundary.

`get_payment_provider()` returns `LocalSimulationProvider` for `simulator` / `SIMULATOR`. Other names fail closed with `PROVIDER_NOT_CONFIGURED`.

## Local simulator

`LocalSimulationProvider` is the default for development and tests (`PAYMENT_PROVIDER=simulator`, `SIMULATION_SEED=42`).

Lifecycle statuses: `CREATED`, `AUTHORIZED`, `CAPTURED`, `FAILED`, `REFUNDED`, `CANCELLED`.

Failure reasons: `TEMPORARY_BANK_ERROR`, `INSUFFICIENT_FUNDS`, `EXPIRED_CARD`, `DECLINED`, `NETWORK_TIMEOUT`, `MANDATE_FAILURE`, `CUSTOMER_CANCELLED`, `UNKNOWN`.

Outcomes depend on failure reason, attempt number, optional customer history, and a seeded RNG. Retryable bank/network errors become more likely to capture on later attempts; `CUSTOMER_CANCELLED` and `MANDATE_FAILURE` never capture. The same seed and inputs reproduce the same order/payment ids and statuses.

Provider payment/order ids are strings such as `pay_sim_…` / `order_sim_…`. Internal payment primary keys remain UUIDs (`uuid5` of merchant + provider + provider payment id) and are never equal to the provider id.

## Provider events vs domain events

Inbound `ProviderEvent` fields: `provider`, `event_id`, `event_type`, `occurred_at`, `provider_resource_id`, `merchant_reference`, `payload`, `signature_valid`, `correlation_id`.

Normalization (`recoverai_domain.normalize`) maps simulator types to:

- `PaymentFailedEvent`
- `PaymentCapturedEvent`
- `PaymentRefundedEvent`
- `PaymentCancelledEvent`
- plus created/authorized as generic `DomainPaymentEvent`
- unknown types → `UnknownDomainEvent` (stored, no payment/case side effects)

Domain code reads typed fields, not raw provider JSON.

## Ingestion pipeline

`EventIngestionService`:

1. Validate structure (reject malformed events; do not persist them).
2. Resolve merchant explicitly (`merchant_id` or `merchant_slug`). No global lookup by payment id.
3. Persist `webhook_events` with `provider=SIMULATOR`.
4. Unique `(provider, event_id)`: duplicates return idempotent success, audit `DUPLICATE_EVENT_IGNORED`, and re-enqueue only if the row is still `RECEIVED` or `FAILED`.
5. Enqueue `process_provider_event`. Do not run recovery logic in the HTTP request.
6. Acknowledge `{ accepted, duplicate, queued, event_id, webhook_event_id, status }`.

Endpoints:

- `POST /v1/webhooks/simulator` — development ingest (no Razorpay signature)
- `POST /v1/simulation/events` — generate a deterministic simulator event and ingest it
- `POST /v1/simulation/scenarios` — A / B / C / E
- `GET /v1/events` — recent webhook summaries (no raw secrets)

Known merchant fixture for simulation: deterministic UUID + slug `recoverai-demo`, created on first simulation or unscoped simulator webhook. `seed.py` is not required. Repeated calls do not create duplicate merchants. The previous slug `simulator-dev` is still recognized if already present. An explicit `merchant_id` / unknown slug is not auto-created.

## RQ processing

Job: `recoverai_worker.jobs.process_provider_event`.

Bounded retries (`WORKER_MAX_RETRIES`, default 3, intervals 5s / 15s / 45s, max 10). After RQ will no longer retry, the row is `DEAD_LETTER`. Permanent domain errors (`MISSING_CUSTOMER`, `MISSING_MERCHANT`, …) go to `DEAD_LETTER` immediately and are not retried. There is no infinite retry.

On each run:

1. Lock the webhook row.
2. If `PROCESSED` or `DEAD_LETTER`, return without side effects (`RECEIVED`, `PROCESSING`, and `FAILED` may run).
3. Normalize and apply domain updates (open-case uniqueness still prevents duplicate active cases).
4. Mark `PROCESSED` and audit `PROVIDER_EVENT_PROCESSED`.
5. On retryable failure: roll back the worker transaction (no partial payment/case writes), re-raise for RQ. Status stays `RECEIVED` until success or dead-letter.
6. On permanent failure or exhausted retries: `DEAD_LETTER` in a separate transaction.

## Payment failed → recovery case

For `PaymentFailedEvent`:

- Find or create the merchant-scoped payment (provider ids stored separately).
- If no open case for that payment: create `recovery_cases` with `case_type=FAILED_PAYMENT`, `status=DETECTED`, `amount_at_risk` = unpaid amount, `amount_recovered=0`, `source_event_id` = webhook UUID.
- If an open case already exists: attach and audit `RECOVERY_CASE_ATTACHED` (Phase 2 partial unique index).

The same provider event twice yields one processed webhook and one case. Two different failure events for the same provider payment also yield one open case.

## Payment captured / refunded

Captured: update payment to `CAPTURED`, persist `captured_at`, find matching open cases, enqueue `verify_recovery_case`. HTTP ingest still does not verify inline.

Refunded: update payment to `REFUNDED` and audit. No refund policy.

## Deduplication (summary)

| Situation | Result |
| --- | --- |
| Same `provider` + `event_id` twice | One webhook row; second call is idempotent success |
| Worker runs the same webhook twice | Second run is a no-op (`already_processed`) |
| Two failure events, different ids, same provider payment | One open recovery case |
| Unknown `event_type` | Row stored and marked processed; no payment/case writes |
| Malformed body | HTTP 422; nothing persisted |

## Failure handling

| Condition | Behavior |
| --- | --- |
| Invalid / malformed event | HTTP 422 or `INVALID_PROVIDER_EVENT`; no persist |
| Missing merchant | `MISSING_MERCHANT` (404) |
| Missing customer at process time | `MISSING_CUSTOMER`; webhook `DEAD_LETTER`; no case; not retried |
| Unknown event type | Persist; process with no domain side effects |
| Queue/Redis failure after persist | Logged; `queued=false`; duplicate POST can re-enqueue `RECEIVED`/`PROCESSING`/`FAILED` rows |
| Database operational error in worker | Retryable; worker rolls back; bounded RQ retries then `DEAD_LETTER` |
| Simulation capability not implemented | `ProviderCapabilityError` |

## Observability

Structured logs include `request_id` (middleware), and where relevant `correlation_id`, `merchant_id`, `event_id`. Messages: event received / duplicated / queued / processed / failed, case created.

Audit types: `PROVIDER_EVENT_RECEIVED`, `DUPLICATE_EVENT_IGNORED`, `PAYMENT_UPDATED`, `RECOVERY_CASE_CREATED`, `RECOVERY_CASE_ATTACHED`, `PROVIDER_EVENT_PROCESSED`, `PROVIDER_EVENT_FAILED`, `UNKNOWN_EVENT_IGNORED`.

Secrets (`authorization`, `secret`, `api_key`, …) are stripped from stored payloads.

## Scenarios

| Scenario | How | Expected |
| --- | --- | --- |
| A | `POST /v1/simulation/scenarios` `{"scenario":"A"}` | Failed payment, case `DETECTED` after worker |
| B | scenario `B` | Same event ingested twice → one case |
| C | scenario `C` | Later capture updates payment; case stays `DETECTED` |
| D | malformed `POST /v1/webhooks/simulator` | 422, no corruption |
| E | scenario `E` | Unknown type stored, no case |
| F | run `process_provider_event` twice | Idempotent |

HTTP ingest does not run the worker inline. Process queued jobs with the RQ worker, or in tests call `process_webhook_event`.
