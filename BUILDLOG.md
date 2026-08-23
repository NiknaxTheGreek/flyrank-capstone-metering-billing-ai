# Build Log

## AI-generated capstone version

This is the dedicated AI-generated implementation workspace for the FlyRank Backend Capstone: Usage Metering & Billing Engine. It is separate from any human-generated version.

## Setup log

- Phase 1 project identity and GitHub repository setup were completed before implementation work began.
- AI assistance established the project identifier, project-control documents, and Git synchronization process.
- Local environment configuration uses placeholders only; real credentials must be supplied through secure environment configuration when later tasks require them.

## Notable setup decisions

- The intended implementation stack is Python, FastAPI, PostgreSQL, Docker, SQLAlchemy, Alembic, pytest, and Stripe test mode.
- The capstone will remain intentionally small: Free and Pro plans, API-call and AI-token metering, and no real AI call.

## T2 initial application setup

- AI assistance configured the Replit-managed project Python environment and locked the minimal initial dependencies: FastAPI, Uvicorn, and pytest.
- A minimal FastAPI application, health endpoint, layered package boundaries, and deterministic pytest check were added and verified.
- Database schema, metering, quotas, Stripe behavior, pricing, usage summaries, migrations, Docker configuration, and background jobs remain unimplemented.

## T3 database foundation

- AI assistance added a local PostgreSQL Compose service with local-only trust authentication, so no database secret is committed.
- SQLAlchemy, Psycopg, and Alembic were added only for environment-driven connectivity and migration configuration.
- The live local PostgreSQL connection, Alembic configuration, and deterministic test suite were verified without creating domain tables or revisions.
- The Replit Docker runtime cannot execute container health-check commands, so verification uses the Compose-published localhost PostgreSQL port rather than the blocked exec-based health status.
- Metering, idempotency, quotas, Stripe behavior, pricing, usage summaries, background jobs, and T4 schema implementation remain unimplemented.

## T4 database schema

- AI assistance added persistence-only models for plans, tenants, subscriptions, usage events, and processed Stripe webhook-event receipts.
- The schema uses tenant foreign keys, tenant-scoped usage idempotency, global Stripe event deduplication, and targeted PostgreSQL indexes without adding service behavior.
- Integer `BIGINT` columns represent cents, usage quantity, and plan limits; no floating-point money representation was introduced.
- The generated Alembic revision was applied and inspected against a dedicated clean PostgreSQL verification database, including direct duplicate-protection checks.
- Metering services, idempotent request handling, quotas, billable API logic, Stripe webhook processing, pricing calculations, usage summaries, and background jobs remain unimplemented.

## T5 seed data

- AI assistance added a repeatable `python -m app.data.seed` command for the Free and Pro plans plus a deterministic demo Free tenant and active Free subscription.
- Free is seeded with 1,000 API calls and 100,000 tokens per month; Pro is seeded with 10,000 API calls and 1,000,000 tokens per month.
- Both plans use the schema-required integer `monthly_price_cents` value of `0` because no approved nonzero plan price exists in the capstone configuration; no pricing behavior was introduced.
- Stable seed UUIDs and converging updates keep repeated runs at exactly two plans, one demo tenant, and one demo subscription.
- Metering services, idempotent request handling, quotas, billable API logic, Stripe webhook processing, pricing calculations, usage summaries, and background jobs remain unimplemented.

## T6 core metering

- AI assistance added a validated dummy `POST /api/generate` endpoint that simulates generation without calling an AI provider.
- The API requires a tenant-scoped request body and `Idempotency-Key` header. A first request returns `201`; a safe retry returns `200`, the original usage event, and `idempotent_replay=true`.
- The service coordinates metering behavior, while the repository owns persistence, transaction handling, and the existing tenant/idempotency database uniqueness constraint as the final duplicate-prevention backstop.
- No quota enforcement, Stripe processing, pricing calculation, usage summary, or background job behavior was added.

## T7 quota enforcement

- AI assistance added tenant-scoped, current-period usage aggregation and active-plan lookup in the data layer.
- The quota service uses an explicit UTC calendar month, inclusive at the month start and exclusive at the next month start, so period evaluation remains deterministic.
- API-call and AI-token quotas are evaluated independently. Requests are accepted when current usage plus attempted quantity is less than or equal to the plan limit, including the exact limit; requests that would exceed it return `429` with `quota_exhausted` details and create no usage event.
- Existing successful idempotency keys are replayed before plan or quota evaluation, preserving exactly-once behavior even when current usage has subsequently reached a limit.
- `402` is reserved for a tenant without an active eligible subscription plan; ordinary quota exhaustion remains `429`.
- No Stripe Checkout or webhook processing, pricing engine, usage-summary route, or background job behavior was added.