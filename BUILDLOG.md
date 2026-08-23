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

## T8.1–T8.3 Stripe test-mode configuration

- AI assistance added Stripe Python SDK `15.4.0` and a lazy `StripeClient` construction boundary. It reads only validated runtime settings and does not issue Stripe API requests in this milestone.
- Stripe configuration requires a test-mode secret-key prefix, a Pro Price identifier beginning with `price_`, and absolute HTTPS success and cancel URLs without embedded user credentials. A Price identifier alone cannot distinguish test and live mode, so the test-mode secret key is the mode boundary.
- The example environment contract now contains only safe placeholders for `STRIPE_SECRET_KEY`, `STRIPE_PRO_PRICE_ID`, `STRIPE_SUCCESS_URL`, and `STRIPE_CANCEL_URL`; no real credential or sandbox Price ID is committed.
- Deterministic configuration tests verify valid environment loading, safe SDK client construction, and rejection of missing, live-key, malformed-price, and unsafe-URL values.
- No Checkout endpoint or service, Stripe API call, tenant association, subscription change, webhook handling, pricing, usage summary, or background job behavior was added.

## T8.4–T8.7 Stripe Checkout construction

- AI assistance added a service-layer Checkout flow for active Free tenants and a thin `POST /api/checkout` route. The service uses the validated environment-derived Pro Price and redirect URLs to build a Stripe subscription-mode hosted Checkout Session.
- The Checkout request carries the tenant UUID in both `client_reference_id` and `metadata.tenant_id`. Checkout creation only reads local tenant/subscription state; it intentionally does not mutate the local plan, status, customer reference, or subscription reference.
- The API maps unknown tenants to `404`, ineligible subscriptions to `409`, missing Stripe configuration to `503`, and Stripe session failures to `502`. Stripe business decisions remain outside the route.
- The public route also requires `X-Checkout-Tenant-Proof`, an HMAC proof bound to the request tenant UUID and verified with the existing runtime-only `SESSION_SECRET`. This prevents callers from substituting a different tenant identifier; a trusted authentication or gateway layer can issue the proof without exposing the secret.
- Mocked tests verify the exact Checkout request shape, tenant association, eligibility behavior, Stripe failure handling, API error mapping, and no immediate Free-to-Pro upgrade.
- Live sandbox acceptance was completed through the connected Stripe sandbox Payment Link workaround. The resulting Checkout Session was verified as `livemode=false`, `mode=subscription`, `amount_total=0`, `payment_status=paid`, and `status=complete`, with the demo tenant UUID in metadata and a real Stripe test subscription created.
- The completed session used the intended FlyRank Capstone Pro test product with configured sandbox Price `price_1U7Y4NKCXHTirgTqAUC7EMvi`, a monthly recurring interval, quantity `1`, `unit_amount=0`, and `livemode=false`.
- The workaround was necessary because the connected Stripe API surface did not expose Checkout Session creation directly and this Replit runtime does not contain Stripe credentials. The application implementation is still evidenced independently through deterministic mocked Checkout tests; no runtime behavior was changed. Webhooks, signature verification, event processing, subscription synchronization, pricing, usage summaries, and background jobs remain out of scope.

## T9 Stripe webhook payment-state synchronization

- AI assistance added a thin raw-body Stripe webhook route that verifies `Stripe-Signature` using the official Stripe Python SDK before any persistence work begins. The webhook signing secret is runtime-only, structurally validated as a `whsec_` value, and represented only by a safe placeholder in the example environment file.
- Verified subscription-mode Checkout completion resolves tenant identity exclusively from Stripe Checkout metadata/client-reference information and records Stripe customer/subscription identifiers. It deliberately leaves the local Free entitlement unchanged: only a later verified subscription update with `active` status and the configured Pro Price can grant Pro access.
- Verified subscription updates find the prior local Stripe-subscription mapping and grant Pro access only when the remote status is `active` and its items contain the configured Pro Price. A price mismatch or non-active status removes Pro entitlement rather than guessing. Verified subscription deletion restores the Free plan while retaining the audited Stripe link and remote status.
- Supported-event processing claims the existing globally unique Stripe event receipt before mutation. A database uniqueness collision becomes a successful idempotent response, preserving one durable business effect. Unsupported verified event types are safely acknowledged without a state change.
- Subscriptions persist the latest applied Stripe event creation time/type and an authoritative-reconciliation watermark through follow-on Alembic migrations. Handlers lock the mapped subscription row and do not apply an older event. Because Stripe event creation time has second-level granularity, any distinct same-second event retrieves the current Stripe subscription before receipt persistence and records the observation time; later deliveries that could be subsumed by that observation are reconciled again instead of trusting their stale payload. If Stripe cannot provide that current state, the delivery fails safely with no receipt or entitlement mutation.
- A verified Checkout that links a tenant to a different Stripe subscription resets only the previous subscription's ordering state while preserving Free access. This lets a delayed Checkout map the new subscription even after an event for the prior subscription, so the new subscription's later verified active configured-price update can grant Pro.
- Stripe CLI `1.27.0` was installed and version-checked without credentials. No CLI login or event delivery was attempted because this workspace has no Stripe runtime credentials; no delivery evidence is claimed.
- The implementation adds no usage summary, invoice, charge collection, tax, proration, or background-job behavior.

## T10 Gemini 2.5 Flash-Lite Standard pricing

- AI assistance added a side-effect-free token pricing module that uses integer cents and validates every API-call/token count as a non-negative, non-boolean integer.
- API-call variable cost is pinned to `0` cents. Gemini 2.5 Flash-Lite Standard text rates are pinned as follows: input `10`, cached input `1`, output `40`, and reasoning `40` cents per 1,000,000 tokens. The source is Google AI pricing as supplied and checked on `2026-08-23`.
- The calculator combines category numerators first and applies exactly one final half-up rounding to whole cents. It does not use binary floating-point money and is deliberately not integrated with a usage-summary endpoint.
- Deterministic tests cover the independent cost categories, final-rounding boundaries, large exact integers, invalid values, webhook delivery paths, PostgreSQL-backed synchronization, and full regression behavior.

## T11 monthly usage summary

- AI assistance added a tenant-scoped `GET /usage` route backed by one shared source-event summary service using the existing UTC calendar billing period.
- The response exposes the locally verified plan/status, Free or Pro limits, current API/token usage with distinct token categories, remaining allowance, and the existing T10 integer-cent estimate. No pricing constants or rounding behavior were duplicated.
- Legacy uncategorized AI-token events remain represented as input tokens; new generation requests can retain input, cached-input, output, or reasoning categories.
- The summary derives its plan from persisted Stripe-synchronized subscription state, so a verified Pro update changes displayed limits without changing historical usage.

## T12 monthly usage reconciliation job

- AI assistance added a directly runnable `python -m app.jobs.monthly_usage_rollup` job outside FastAPI request handling.
- The job reuses the same summary/pricing functions as `GET /usage`, retries transient database failures with a small bounded budget, logs only safe failure labels, and raises a nonzero CLI exit after exhausted retries.
- A monthly rollup table with a tenant-plus-UTC-month uniqueness constraint allows repeated execution to reconcile one row rather than create duplicates.
- The final deterministic regression-suite rerun against the corrected committed T11/T12 milestone completed successfully: `99 passed`.

## T13.1 invalid usage type

- The existing FastAPI/Pydantic literal validation for the real generation endpoint already allows only `api_call` and `ai_token`, so no production behavior was changed.
- A focused API regression now proves an unsupported type receives a validation error before metering and produces no usage event for its idempotency key.

## Phase 4 hardening and reproducibility

- AI assistance reused the existing runtime-only HMAC proof mechanism for `generate` and `usage`, with endpoint-specific proof audiences. This closes caller-supplied tenant UUID access without introducing an authentication system or changing Checkout proof compatibility.
- Request-level validation now rejects storage-invalid usage combinations before services or database writes. Focused API coverage verifies invalid type/category/boundary inputs have zero durable events and cross-tenant generate/usage attempts return `403`; the focused run completed successfully: `14 passed`.
- Existing webhook code was left intact because its signature-first rejection, valid unsupported-event acknowledgement, duplicate receipt, and Free-to-Pro safeguards already had deterministic coverage. The single final regression run completed successfully: `105 passed`.
- The stale initial README, generic migration note, incomplete environment contract, and Phase 1 control-file status were corrected with a reproducibility runbook covering setup, migrations, seed data, endpoints, error semantics, quotas, pricing, Stripe test flow, usage, rollups, security boundary, architecture, and non-goals.

## T15 evidence review

- Existing verified PostgreSQL and deterministic evidence was mapped to idempotency, quota boundaries, pricing, forged/duplicate webhooks, Free-to-Pro entitlement, tenant isolation, and rollup reconciliation. No expensive proof was rerun when its prior evidence remained applicable.
- A tracked source/documentation scan for common live credential prefixes completed with `live_credential_scan=clear`. Published configuration remains placeholder-only.

## T16 AI-assisted review

- **Major decisions:** retain usage events as the source of truth; use UTC calendar months; keep pricing integer-only with one final rounding; keep Checkout separate from entitlement; use endpoint-bound tenant proofs rather than a new auth subsystem.
- **AI mistakes corrected:** the original README and migration note still described an unimplemented workspace, and the control file still reported Phase 1 despite implemented billing behavior. They were updated to match the verified capstone.
- **Nicholas's corrections:** Nicholas required the missing C5 labels not be invented, demanded a low-credit focused-then-one-full-suite verification strategy, and required no claim of personal understanding without his demonstration.
- **Important learning:** tenant scoping in repositories is not sufficient when a public API accepts a tenant UUID; ownership must be checked at the request boundary before any metering or disclosure.
- **T16.5 status: incomplete.** Nicholas has not personally demonstrated that he can explain the retained critical code, so no such claim is made.