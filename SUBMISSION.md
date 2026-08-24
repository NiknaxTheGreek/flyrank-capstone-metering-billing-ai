# FlyRank Backend Capstone — Submission

## Project

**Usage Metering & Billing Engine**  
Repository: `NiknaxTheGreek/flyrank-capstone-metering-billing-ai`

## Submission links

- Source repository: `https://github.com/NiknaxTheGreek/flyrank-capstone-metering-billing-ai`
- Current submission archive: `FlyRank_Backend_Capstone_Submission.zip`
- Permanent interactive demo: `https://flyrank-capstone-metering-billing-ai.onrender.com/demo`
- FastAPI API documentation: `https://flyrank-capstone-metering-billing-ai.onrender.com/docs`
- Health check: `https://flyrank-capstone-metering-billing-ai.onrender.com/api/healthz`

## Required submission files

- `README.md`
- `capstone.yaml`
- `EVIDENCE.md`
- `BUILDLOG.md`
- `.env.example`
- `LICENSE`
- source code under `app/`
- Alembic migrations under `alembic/`
- deterministic tests under `tests/`
- Docker/PostgreSQL configuration in `compose.yml`
- dependency files `pyproject.toml` and `uv.lock`
- Render deployment blueprint `render.yaml`

## Core implementation

- Free and Pro plans
- API-call and AI-token usage
- `POST /api/generate`
- `GET /usage`
- PostgreSQL persistence
- SQLAlchemy + Alembic
- database-backed request idempotency
- exact quota boundaries
- integer-cent token pricing
- Stripe test-mode Checkout implementation
- verified and deduplicated Stripe webhooks
- Free-to-Pro / Pro-to-Free subscription synchronization
- tenant isolation
- retry-safe monthly reconciliation background job
- deterministic pytest regression suite
- opt-in reviewer demo page with live usage requests and JSON/CSV report export

## Permanent deployment

The reviewer-facing application is deployed as a free Render Python/FastAPI web service backed by a separate Neon PostgreSQL database.

- Render provides the stable public `onrender.com` hostname.
- Neon provides the persistent PostgreSQL data layer without the 30-day expiry of Render's free Postgres tier.
- The database connection string is stored only as a Render environment variable and is not committed to GitHub.
- Alembic migrations and repeat-safe seed data run before Uvicorn starts.
- `DEMO_MODE=true` exposes only the fixed seeded reviewer tenant through `/demo`; the normal tenant-scoped API remains protected.
- `render.yaml` intentionally marks `DATABASE_URL` as `sync: false` because the external database credential must never be committed.

Permanent demo:

`https://flyrank-capstone-metering-billing-ai.onrender.com/demo`

## Verification status

The committed evidence records the completed deterministic regression suite, acceptance probes, PostgreSQL-backed boundary/idempotency proofs, Stripe signature/deduplication tests, tenant isolation, background-job repeat safety, and two successful deterministic demo rehearsals.

The permanent Render deployment reached `live` state after a deployment-specific connection-driver issue was corrected. The Neon database was then verified to contain the Alembic schema plus the expected seed counts: two plans, one demo tenant, and one subscription. Public-path verification is recorded separately by the permanent deployment verification workflow.

The public reviewer demo is an additional presentation layer and does not replace the protected production-shaped API boundary. Stripe credentials are not configured on the public reviewer deployment, so the public demo is for metering, idempotency, quota, pricing and report behavior; the Stripe flow remains demonstrated by the committed deterministic and test-mode evidence.

## Owner-review item

`T16.5` is complete. On 2026-08-24 the owner personally explained the retained critical billing logic. Three implementation-specific corrections were recorded rather than hidden: quota enforcement uses persisted usage-event totals and `current + attempted <= limit`; pricing combines integer rate numerators and rounds once to cents; and tenant authorization uses endpoint-bound HMAC proofs plus tenant-scoped queries rather than API-key-derived tenant identity.
