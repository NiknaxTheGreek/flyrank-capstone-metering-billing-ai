# Vercel + Neon migration (prepared, not deployed)

Use Vercel Hobby only for this personal, non-commercial portfolio demo. Keep Stripe in test mode. Stay on Neon Free; do not select paid upgrades. Free tiers have quotas and serverless cold starts; this is not an uptime guarantee.

## Deployment

1. Create/select a Neon Free project and record its project ID. Create a dedicated database for this demo rather than modifying an unrelated project.
2. Store the pooled TLS connection URL in Vercel as DATABASE_URL. The application already normalizes postgresql:// to postgresql+psycopg://. Use the direct TLS URL for Alembic initialization.
3. In a trusted terminal, export the direct DATABASE_URL without printing it, then run:
   uv sync --locked
   uv run alembic upgrade head
   uv run python -m app.data.seed
   uv run python -m app.jobs.monthly_usage_rollup
4. Import this repository's deploy/vercel-neon branch into Vercel. Select FastAPI and repository root. Use Python 3.13 and the existing uv.lock. No Uvicorn start command is needed: Vercel serves app/main.py:app.
5. Set APP_ENV=production, DEMO_MODE=true and a newly generated SESSION_SECRET in Vercel's private environment settings. Set the existing Stripe TEST secret key and price ID if Checkout is required. Never commit credentials.
6. Set STRIPE_SUCCESS_URL and STRIPE_CANCEL_URL to the new deployment's /demo URL, with the Checkout session placeholder on the success URL. Register the new /api/webhooks/stripe endpoint only after confirming its actual route in app/api/webhooks.py; use its own signing secret as STRIPE_WEBHOOK_SECRET.
7. Redeploy after setting environment variables. Allow public reviewer access and Stripe webhook access; deployment protection must not block them.

## Background job

The existing CLI rollup remains outside HTTP and must run separately against the new database:
   uv run python -m app.jobs.monthly_usage_rollup

Do not launch an endless worker from FastAPI startup on Vercel. A scheduled external runner remains to be configured and verified before declaring migration complete. Store its database URL as a private secret. The CLI already has bounded retries and observable failure exit status.

## Acceptance before cutover

- /api/healthz returns 200 (this alone does not prove database access).
- /docs and /demo load; /demo/submission.zip downloads.
- Demo generate and usage work against persistent PostgreSQL.
- Repeating an idempotency key produces one persistent usage event.
- Quota and pricing tests pass with the new database.
- Stripe test Checkout plus a verified webhook upgrades Free to Pro.
- Forged and duplicate webhook probes pass.
- Rollup runs twice without duplicate rows; scheduled execution is verified.
- Recheck after inactivity and record actual startup latency.

Keep Render and the Bosnia recruiter-facing site in place until these checks pass. Inspect the static site's actual API wiring before changing a target; cross-origin access and tenant authentication need verification. No static-site target, Stripe endpoint, production secret, or live database was changed by this preparation.

## References

- https://vercel.com/docs/frameworks/backend/fastapi
- https://vercel.com/docs/functions/runtimes/python
- https://vercel.com/docs/plans/hobby
- https://neon.com/docs/connect/connection-pooling
- https://www.koyeb.com/docs/faqs/pricing

Status: configuration prepared only. No live deployment or acceptance evidence claimed.
