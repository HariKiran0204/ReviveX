# ADR-0002: Provider and event abstraction

**Status:** Accepted  
**Date:** 2026-09-03  
**Phase:** 3 — Provider abstraction, local simulator, event ingestion

## Context

Phase 2 persisted merchants, payments, webhook rows, and recovery cases but did not ingest events or create cases from the outside world. Phase 3 must run a real loop from a payment event to a `DETECTED` recovery case without coupling the product to Razorpay, and without blocking HTTP on domain work.

Duplicates are normal for webhooks and workers. Side effects must be idempotent.

## Decisions

### Isolated provider adapters

Payment operations go through `PaymentProvider` in `packages/providers`. Domain code consumes snapshots and `ProviderEvent`, never a vendor SDK object. Razorpay can be added later as another adapter behind the same interface.

### Local simulator is the default

Development and tests use `LocalSimulationProvider` with `SIMULATION_SEED`. No Razorpay credentials are required. The simulator models a generic payment lifecycle; it is not a Razorpay sandbox clone.

### Normalized domain events

Ingestion stores the provider envelope on `webhook_events`. The worker normalizes into `PaymentFailedEvent` / `PaymentCapturedEvent` / `PaymentRefundedEvent` / `PaymentCancelledEvent`. Recovery logic branches on those types so provider JSON does not spread through the domain.

### Asynchronous webhook processing

`EventIngestionService` persists and enqueues `process_provider_event` on RQ. HTTP returns an acknowledgement. Expensive matching, payment writes, and case creation happen in the worker with a bounded retry policy.

### Duplicates are expected

`webhook_events` remains unique on `(provider, event_id)`. Duplicate deliveries audit `DUPLICATE_EVENT_IGNORED` and do not create a second case. Open recovery-case uniqueness from Phase 2 remains the guard when two different failure events refer to the same payment. Re-running the worker on a `PROCESSED` row is a no-op.

## Consequences

- Simulator and (later) Razorpay share ingestion, jobs, and case creation.
- Operators can demo failures without a real PSP.
- Captured events in Phase 3 do not credit recovery; verification stays Phase 4+.
- The worker now requires `DATABASE_URL` as well as Redis.

## Alternatives considered

- Processing domain side effects inside the webhook HTTP handler: rejected — timeouts and retries would duplicate work more easily.
- Pretending the simulator is Razorpay: rejected — would bake vendor payload shapes into the core.
- Application-only duplicate checks without the unique constraint: rejected — races would create double cases.
