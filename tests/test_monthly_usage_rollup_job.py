from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.data.models import Base, MonthlyUsageRollup, UsageEvent
from app.data.seed import DEMO_FREE_TENANT_ID, seed_database
from app.jobs.monthly_usage_rollup import (
    MonthlyRollupJobError,
    reconcile_monthly_usage_rollups,
    run_monthly_usage_rollup_job,
)

FIXED_NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def _engine_with_usage() -> object:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        session.add_all(
            [
                UsageEvent(
                    tenant_id=DEMO_FREE_TENANT_ID,
                    usage_type="api_call",
                    quantity=9,
                    idempotency_key="job-api",
                    occurred_at=FIXED_NOW,
                ),
                UsageEvent(
                    tenant_id=DEMO_FREE_TENANT_ID,
                    usage_type="ai_token",
                    token_category="output",
                    quantity=1_000_000,
                    idempotency_key="job-output",
                    occurred_at=FIXED_NOW,
                ),
            ]
        )
        session.commit()
    return engine


def test_monthly_rollup_job_reconciles_and_reuses_one_logical_row() -> None:
    engine = _engine_with_usage()
    try:
        first = run_monthly_usage_rollup_job(
            lambda: Session(engine),  # type: ignore[arg-type]
            as_of=FIXED_NOW,
            sleep=lambda _delay: None,
        )
        with Session(engine) as session:  # type: ignore[arg-type]
            session.add(
                UsageEvent(
                    tenant_id=DEMO_FREE_TENANT_ID,
                    usage_type="api_call",
                    quantity=1,
                    idempotency_key="job-api-later",
                    occurred_at=FIXED_NOW,
                )
            )
            session.commit()
        second = run_monthly_usage_rollup_job(
            lambda: Session(engine),  # type: ignore[arg-type]
            as_of=FIXED_NOW,
            sleep=lambda _delay: None,
        )
        with Session(engine) as session:  # type: ignore[arg-type]
            count = session.scalar(select(func.count()).select_from(MonthlyUsageRollup))
            rollup = session.scalar(select(MonthlyUsageRollup))

        assert first.reconciled_tenants == second.reconciled_tenants == 1
        assert count == 1
        assert rollup is not None
        assert rollup.api_calls == 10
        assert rollup.output_tokens == 1_000_000
        assert rollup.estimated_ai_cost_cents == 40
    finally:
        engine.dispose()  # type: ignore[union-attr]


def test_monthly_rollup_job_retries_a_transient_failure_then_succeeds() -> None:
    engine = _engine_with_usage()
    calls = 0
    delays: list[float] = []

    def flaky_operation(session: Session) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("SELECT 1", {}, RuntimeError("temporary"))
        return reconcile_monthly_usage_rollups(session, as_of=FIXED_NOW)

    try:
        result = run_monthly_usage_rollup_job(
            lambda: Session(engine),  # type: ignore[arg-type]
            max_attempts=3,
            sleep=delays.append,
            reconcile=flaky_operation,
        )
    finally:
        engine.dispose()  # type: ignore[union-attr]

    assert result.attempts == 2
    assert result.reconciled_tenants == 1
    assert delays == [0]


def test_monthly_rollup_job_raises_after_exhausted_retries(caplog: pytest.LogCaptureFixture) -> None:
    engine = _engine_with_usage()

    def always_fails(_session: Session) -> int:
        raise OperationalError("SELECT 1", {}, RuntimeError("temporary"))

    try:
        with pytest.raises(MonthlyRollupJobError):
            run_monthly_usage_rollup_job(
                lambda: Session(engine),  # type: ignore[arg-type]
                max_attempts=2,
                sleep=lambda _delay: None,
                reconcile=always_fails,
            )
    finally:
        engine.dispose()  # type: ignore[union-attr]

    assert "monthly_usage_rollup exhausted_retries attempts=2" in caplog.text