# FlyRank Usage Metering & Billing Engine

Small FastAPI/PostgreSQL capstone for tenant-scoped API and AI-token metering,
Free/Pro quotas, Stripe **test-mode** Checkout and entitlement synchronization,
integer-cent AI cost estimates, and a monthly usage reconciliation job.

## What is included

- Two seeded plans: Free (`1,000` API calls / `100,000` AI tokens per UTC month)
  and Pro (`10,000` / `1,000,000`).
- A simulated generation endpoint; it never calls a real AI provider.
- Tenant-bound HMAC proofs on tenant-scoped public endpoints.
- Tenant + idempotency-key exactly-once usage recording.
- Stripe test-mode hosted Checkout and raw-body signed webhook synchronization.
- Current-month usage summaries and a directly runnable, idempotent rollup job.

## Prerequisites

- Python and `uv`
- Docker Compose with access to `127.0.0.1:5432`
- A Stripe test-mode account only when exercising Checkout/webhooks outside tests

## Local setup

```bash
cp .env.example .env
docker compose -f compose.yml up -d postgres
uv sync --locked
set -a && . ./.env && set +a
uv run alembic upgrade head
uv run python -m app.data.seed
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The Compose database uses local-only trust authentication and publishes only to
`127.0.0.1`. It is a development convenience, not a production configuration.

Run all deterministic tests with:

```bash
uv run --locked pytest -q
```

`alembic upgrade head` is repeatable. The seed command is also repeat-safe and
creates the Free/Pro plans plus the deterministic demo Free tenant.

## Deterministic demo rehearsal

Run the complete local T18 demonstration twice without live Stripe credentials:

```bash
uv run --locked python -m scripts.rehearse_t18_demo
```

The rehearsal uses a temporary file-backed SQLite database and the real HTTP
routes. It visibly exercises near-quota refusal, idempotent retry, durable row
counts, signed Stripe Free-to-Pro synchronization, forged/duplicate webhook
handling, an exact usage summary, and one selected pytest result per run.

## Environment

Copy `.env.example`; it contains placeholders only. Never commit `.env` or put
real values in source, test fixtures intended for publication, `EVIDENCE.md`, or
`BUILDLOG.md`.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL SQLAlchemy URL. |
| `SESSION_SECRET` | Runtime-only secret used by a trusted authentication/gateway layer to issue endpoint-bound tenant proofs. |
| `STRIPE_SECRET_KEY` | Stripe **test-mode** secret key; must begin `sk_test_`. |
| `STRIPE_PRO_PRICE_ID` | Configured recurring Stripe test Price; must begin `price_`. |
| `STRIPE_WEBHOOK_SECRET` | Stripe signing secret; must begin `whsec_`. |
| `STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL` | Absolute credential-free HTTPS Checkout redirects. |

The trusted layer creates a proof as HMAC-SHA256 of
`<audience>:<tenant UUID>` using `SESSION_SECRET`. Audiences are `generate`,
`usage`, and `checkout`; proofs cannot be exchanged between endpoints.

## API contract

All errors use normal HTTP status codes. Domain errors expose a stable
`detail.code`; Pydantic request errors are `422` validation responses.

### `GET /api/healthz`

Returns `200 {"status":"ok"}`.

### `POST /api/generate`

Records one simulated usage event.

- Body: `tenant_id` UUID, `usage_type` (`api_call` or `ai_token`), and positive
  integer `quantity`.
- `ai_token` additionally requires `token_category`: `input`, `cached_input`,
  `output`, or `reasoning`. `api_call` must not include a token category.
- Headers: non-empty `Idempotency-Key` (maximum 255 characters) and
  `X-Tenant-Proof` for audience `generate`.
- First successful request is `201`; a retry of the same tenant/key is `200`
  with `idempotent_replay=true` and the original usage event.
- Invalid bodies return `422` and do not create a usage event. Missing or wrong
  proofs return `403`; absent `SESSION_SECRET` returns `503`; unknown tenants
  return `404`; inactive/ineligible subscriptions return `402`; quota excess
  returns `429` with `quota_exhausted`.

Idempotency is scoped to `(tenant_id, Idempotency-Key)` and backed by a database
uniqueness constraint. Use a new key for every logical request.

### `GET /usage?tenant_id=<uuid>`

Returns the requested tenant's current UTC-month billing period, verified
plan/status and limits, API/token category totals, remaining API/token
allowance, and `estimated_ai_cost_cents`. It requires `X-Tenant-Proof` for
audience `usage`; invalid ownership returns `403`, missing authorization
configuration returns `503`, and an unknown authorized tenant returns `404`.

### `POST /api/checkout`

Creates a Stripe test-mode, subscription-mode hosted Checkout Session for an
active Free tenant. It requires `X-Checkout-Tenant-Proof` for audience
`checkout`. Checkout records no local upgrade: a later verified subscription
webhook is the only entitlement grant path.

Possible errors are `403` invalid proof, `404` missing tenant, `409` ineligible
subscription, `503` missing authorization/Stripe settings, and `502` Stripe
creation failure.

### `POST /webhooks/stripe`

Consumes raw bytes and verifies `Stripe-Signature` before any database work.
Missing, forged, wrong-secret, stale, or malformed signatures return `400`
without a receipt or local state mutation. Supported verified events are:

- `checkout.session.completed`: links a subscription/customer to the verified
  tenant but never grants Pro by itself.
- `customer.subscription.updated`: grants Pro only for an `active` subscription
  containing the configured Pro Price.
- `customer.subscription.deleted`: restores Free access.

Stripe event IDs are globally deduplicated transactionally. A valid duplicate is
acknowledged with `200` and `idempotent_replay=true`. Other valid Stripe event
types are acknowledged with `200`, `handled=false`, and no state mutation.
Mapped events that cannot safely be processed return `422`; an ambiguous event
whose authoritative Stripe state cannot be retrieved returns `502`.

For local Stripe testing, create a recurring test-mode Pro Price, configure the
test variables and webhook signing secret, point Stripe's webhook endpoint at
the running service (or use a secure test forwarder), and complete Checkout
with Stripe test payment details. Never use live keys or production events.

## Quotas and estimates

Billing periods are UTC calendar months: the start is inclusive and the next
month boundary is exclusive. API calls and AI tokens are independent limits.
An exact-limit request is accepted; only `current usage + attempted quantity >
limit` is rejected.

The estimate is Gemini 2.5 Flash-Lite Standard text pricing, calculated with
integers only:

| Category | Cents per 1,000,000 tokens |
| --- | ---: |
| API calls | 0 |
| Input | 10 |
| Cached input | 1 |
| Output | 40 |
| Reasoning | 40 |

All category numerators are combined before one final half-up rounding to whole
cents. `estimated_ai_cost_cents` is an estimate only: it is not an invoice,
charge, tax calculation, or overage bill.

## Monthly reconciliation job

Run:

```bash
set -a && . ./.env && set +a
uv run python -m app.jobs.monthly_usage_rollup
# Optional deterministic period:
uv run python -m app.jobs.monthly_usage_rollup --as-of 2026-08-23T12:00:00+00:00
```

The job derives every tenant/month rollup from the same source-event summary and
pricing logic as `/usage`. A unique tenant + billing-period row makes reruns
idempotent. Transient SQLAlchemy failures retry up to three times; exhausted
retries exit nonzero and log only safe labels, never database exception text.
Scheduling is intentionally external to this capstone.

## Architecture and security boundary

- `app/api`: HTTP parsing, validation, status/error mapping.
- `app/services`: metering, quota, pricing, Checkout authorization, webhook
  synchronization, and usage summaries.
- `app/data`: SQLAlchemy models, repositories, migrations, and seed data.
- `app/integrations/stripe`: Stripe SDK client boundary.
- `app/jobs`: separately runnable reconciliation work.

Tenant proofs are a capstone boundary for a trusted authentication or gateway
layer, not a substitute for production identity/session management. Production
would additionally require real authentication, authorization-derived tenant
identity, secret management, TLS, rate limiting, a secure database deployment,
and monitored job scheduling.

## Deliberate non-goals

No real AI calls, invoices, collections, refunds, taxes, proration, overage
billing, dashboard/UI, production Stripe, background scheduler, microservices,
Kubernetes, or paid infrastructure are included.

## Submission records

- `capstone.yaml`: scope and implementation control record.
- `EVIDENCE.md`: verified command/proof outcomes only.
- `BUILDLOG.md`: implementation decisions, boundaries, and AI-assisted review.
- `.env.example`: safe configuration contract; `.env` remains private.
