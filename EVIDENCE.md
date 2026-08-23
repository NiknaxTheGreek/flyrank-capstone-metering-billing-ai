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

## Pending evidence

Webhook processing, pricing calculations, usage summaries, background jobs, and later acceptance evidence will be added only after those items exist and their commands have been run successfully.