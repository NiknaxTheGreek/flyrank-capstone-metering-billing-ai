# FlyRank Backend Capstone — Submission

## Project

**Usage Metering & Billing Engine**  
Repository: `NiknaxTheGreek/flyrank-capstone-metering-billing-ai`

## Submission links

- Source repository: `https://github.com/NiknaxTheGreek/flyrank-capstone-metering-billing-ai`
- Current submission archive: `FlyRank_Backend_Capstone_Submission.zip`
- Interactive demo route after deployment: `/demo`
- FastAPI API documentation after deployment: `/docs`
- Health check after deployment: `/api/healthz`

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

## Deployment

`render.yaml` defines a self-contained free Render Blueprint with:

- a free Python/FastAPI web service
- a free PostgreSQL 16 database in the same region
- automatic `DATABASE_URL` injection from the Render database
- automatic dependency installation
- Alembic migrations on start
- repeat-safe seed data
- `/api/healthz` health check
- `/demo` enabled in explicit demo mode
- generated runtime `SESSION_SECRET`

One-click Render deployment:

`https://render.com/deploy?repo=https://github.com/NiknaxTheGreek/flyrank-capstone-metering-billing-ai`

Render's free web-service hostname is stable, but its free PostgreSQL database expires after 30 days. For long-lived $0 data beyond the submission/review window, replace `DATABASE_URL` with a free persistent PostgreSQL provider such as Neon; never commit the connection string.

## Verification status

The committed evidence records the completed deterministic regression suite, acceptance probes, PostgreSQL-backed boundary/idempotency proofs, Stripe signature/deduplication tests, tenant isolation, background-job repeat safety, and two successful deterministic demo rehearsals.

The public reviewer demo is an additional presentation layer and does not replace the protected production-shaped API boundary.

## Manual owner-review item

`T16.5` remains a manual owner-verification item until the owner personally demonstrates that they can explain the retained critical billing logic. This is intentionally not fabricated or auto-completed.
