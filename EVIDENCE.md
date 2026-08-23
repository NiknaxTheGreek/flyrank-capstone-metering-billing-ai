# Evidence Log

This document records only command output and facts that have actually been verified during the AI-generated capstone build. It must never contain fabricated test results, secrets, or claims for work that has not been completed.

## Verified setup facts

- The project is named `flyrank-capstone-metering-billing-ai`.
- The public GitHub repository is connected at `NiknaxTheGreek/flyrank-capstone-metering-billing-ai`.
- At this setup stage, local `main` and remote `origin/main` were verified to reference the same commit.

## T2 verified setup

- `uv sync --locked` completed successfully and reported `Audited 18 packages`.
- The project Python environment was verified at `.pythonlibs` with interpreter prefix `/home/runner/workspace/.pythonlibs`.
- `uv run pytest -q` completed successfully: `1 passed`.
- The managed API service started successfully with Uvicorn listening on `http://0.0.0.0:8080`.
- `curl https://${REPLIT_DEV_DOMAIN}/api/healthz` returned `{"status":"ok"}` with `HTTP 200`.

## T3 verified database foundation

- `docker compose -f compose.yml up -d postgres` started the local PostgreSQL service; `pg_isready -h 127.0.0.1 -p 5432 -U flyrank -d flyrank_metering` reported `accepting connections`.
- The application data-layer connection check completed successfully: `database_connection=ok`.
- `uv run alembic current` loaded the PostgreSQL migration context successfully.
- `uv run alembic check` completed successfully: `No new upgrade operations detected.`
- The T2 and T3 deterministic test suite completed successfully: `4 passed`.
- This Replit Docker runtime blocks exec-based container health checks with `OCI runtime exec ... setns`; the published localhost port, SQLAlchemy connection, and Alembic commands above are the genuine verification path.

## T4 verified database schema

- Alembic generated revision `dd3399d4697c` for the five domain tables: `plans`, `tenants`, `subscriptions`, `usage_events`, and `processed_webhook_events`.
- A dedicated clean PostgreSQL verification database applied the migration successfully: `Running upgrade -> dd3399d4697c, create billing domain schema`.
- Live inspection confirmed the expected tables, named foreign keys, required uniqueness constraints, targeted indexes, and `BIGINT` storage for cents and usage quantity.
- Direct database inserts confirmed duplicate usage-event `(tenant_id, idempotency_key)` values and duplicate Stripe event identifiers are rejected.
- `uv run alembic check` completed successfully: `No new upgrade operations detected.`
- The deterministic test suite completed successfully: `9 passed`.
- `GET /api/healthz` continued to return `{"status":"ok"}` with `HTTP 200`.

## T5 verified seed data

- A dedicated clean PostgreSQL verification database migrated successfully to `dd3399d4697c (head)`.
- The first and second `python -m app.data.seed` runs each completed successfully: `seeded plans=free,pro tenant=demo-free subscription=active`.
- Live PostgreSQL inspection confirmed the approved plan quotas, the demo Free tenant, its active Free subscription, and repeat-safe counts: `plans:2 tenants:1 subscriptions:1`.
- The deterministic test suite completed successfully: `10 passed`.

## T6 verified core metering

- A dedicated clean PostgreSQL verification database migrated, seeded, and served the dummy `/api/generate` route successfully.
- The first request returned `HTTP 201`; a retry with the same tenant and `Idempotency-Key` returned `HTTP 200`, `idempotent_replay=true`, and the same usage-event identifier.
- Direct PostgreSQL inspection confirmed exactly one persistent usage event for the retry key.
- A direct duplicate insert was rejected by the database uniqueness constraint: `database_unique_constraint=duplicate_rejected`.
- The managed API workflow served the same first-request/retry behavior against the documented local Compose database and retained `GET /api/healthz` at `HTTP 200`.
- The deterministic test suite completed successfully: `12 passed`.

## T7 verified quota enforcement

- Quota evaluation uses the deterministic UTC calendar month: the first day at `00:00:00+00:00` is inclusive and the next month boundary is exclusive.
- A dedicated clean PostgreSQL verification database migrated and seeded successfully before exercising `/api/generate`.
- Free API-call usage at `999` accepted one final request with `HTTP 201`, a same-key retry returned `HTTP 200` with the original event, and the next key returned `HTTP 429` with no persistent event.
- Free AI-token usage at `99,999` accepted one final request with `HTTP 201`, and the next key returned `HTTP 429` with no persistent event.
- Direct PostgreSQL totals after the boundary proof were `api_calls:1000 ai_tokens:100000`; rejected-key counts were both zero.
- The deterministic test suite completed successfully: `30 passed`.

## T8.1–T8.3 verified Stripe test-mode foundation

- The official Stripe Python SDK was installed and imported successfully: `stripe_version=15.4.0` and `StripeClient` is available.
- The application accepts Stripe configuration only through runtime environment variables and rejects non-test secret-key prefixes, malformed Pro Price identifiers, missing values, and unsafe redirect URLs.
- The checked-in example configuration contains placeholders only for the Stripe test key, Pro Price ID, success URL, and cancel URL; the local `.env` file remains ignored by Git.
- Deterministic Stripe configuration tests completed successfully: `7 passed`.
- The full deterministic test suite completed successfully: `37 passed`.
- No Stripe API request, Checkout Session, tenant association, subscription mutation, webhook behavior, or live Stripe verification was added in this configuration-only step.

## T8.4–T8.7 Checkout construction

- Deterministic mocked Checkout tests completed successfully: `10 passed`; the full deterministic suite completed successfully: `47 passed`.
- An eligible active Free tenant produces a subscription-mode Checkout request with one configured Pro Price line item, configured success/cancel URLs, and the tenant identifier in both `client_reference_id` and `metadata.tenant_id`.
- The public Checkout route requires a tenant-bound HMAC proof derived from the runtime-only `SESSION_SECRET`; tests confirm a missing or proof-for-another-tenant request is rejected before Checkout creation.
- Tests confirm unknown and non-Free tenants are rejected, Stripe failures map to the Checkout-unavailable path, and creating Checkout leaves the persisted tenant subscription active on Free with no Stripe subscription identifier.
- Live Stripe sandbox acceptance was verified through the connected Stripe sandbox Payment Link workaround. The completed Checkout Session had `livemode=false`, `mode=subscription`, `amount_total=0`, `payment_status=paid`, and `status=complete`; its metadata included the demo tenant ID `1fcf89e3-0f0d-5eff-b8bd-432931feac25`, and Stripe created a real test subscription.
- The verified session line item used the intended FlyRank Capstone Pro test product and configured sandbox Price `price_1U7Y4NKCXHTirgTqAUC7EMvi`: recurring monthly, quantity `1`, `unit_amount=0`, and `livemode=false`.
- This live proof was created through the connected Stripe sandbox Payment Link because its available API surface did not expose Checkout Session creation directly and the Replit runtime did not contain Stripe credentials. The application Checkout implementation itself remains verified by deterministic mocked tests.
- No webhook route, signature verification, event deduplication, subscription synchronization, pricing behavior, usage summary, or background job was added.

## T9 verified Stripe webhook payment synchronization

- The `POST /webhooks/stripe` boundary reads the raw request body and uses Stripe Python SDK `Webhook.construct_event` before calling local synchronization. Missing, forged, wrong-secret, stale, and malformed-signature deliveries return `HTTP 400` with no local mutation.
- Deterministic, correctly HMAC-signed Stripe-compatible event fixtures exercised the real SDK verifier: valid Checkout completion upgrades only the referenced tenant and records Stripe customer/subscription identifiers; mapped subscription updates apply Pro access only for the configured Pro Price; deletion restores the Free plan.
- Subscription synchronization records the latest applied Stripe event creation time and event type under a subscription row lock. Older valid deliveries are acknowledged and receipted but cannot resurrect access after a newer deletion. Because Stripe event timestamps are second-granular, a same-second distinct delivery retrieves the current Stripe subscription before the receipt is claimed, records an authoritative reconciliation watermark, and routes any later potentially subsumed delivery through that same current-state read instead of trusting stale arrival order.
- Valid duplicate deliveries return `HTTP 200` with `idempotent_replay=true`. The existing globally unique processed-event identifier is claimed transactionally before subscription mutation, so only one business effect is durable.
- Valid unsupported event types return `HTTP 200` with `handled=false` and do not create a receipt or alter subscription state. Safely unprocessable but signature-valid mapped events return `HTTP 422` without mutation.
- `uv run --locked pytest -q tests/test_stripe_config.py tests/test_webhooks.py tests/test_pricing.py` completed successfully: `49 passed`.
- An isolated PostgreSQL verification database migrated and seeded successfully. Through the HTTP endpoint, an SDK-verified Checkout completion, its duplicate delivery, a verified deletion, and two older delayed deliveries completed with `receipts=4`, `final_plan=free`, and `final_status=canceled`. `alembic check` reported `No new upgrade operations detected.`
- Stripe CLI was installed without credentials and version-checked as `stripe version 1.27.0`. This environment was not authenticated to Stripe and no Stripe CLI delivery proof was attempted or fabricated.

## T10 verified Gemini 2.5 Flash-Lite Standard pricing engine

- The standalone pricing service is pure and integer-only. API-call variable cost is pinned to `0` cents; the denominator is `1,000,000` tokens; and ordinary input, cached input, output, and reasoning are retained separately.
- The pinned Gemini 2.5 Flash-Lite Standard text rates are input `10`, cached input `1`, output `40`, and reasoning `40` cents per million tokens, as supplied from Google AI pricing and checked on `2026-08-23`.
- All category numerators are combined first; one final non-negative integer half-up rounding to whole cents is applied. No binary floating-point money is used.
- Independent deterministic tests cover each category, zero-cost API calls, mixed totals, exact and below-half-cent boundaries, large values, invalid counts, and immutability.
- The full deterministic suite completed successfully after the final reconciliation change: `89 passed`.

## Pending evidence

Usage summaries, invoicing, charging, taxes, proration, and background jobs remain out of scope and have not been implemented.