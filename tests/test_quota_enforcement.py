from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.data.models import Base, Plan, Subscription, Tenant, UsageEvent
from app.data.seed import DEMO_FREE_SUBSCRIPTION_ID, DEMO_FREE_TENANT_ID, seed_database
from app.services.metering import MeterUsageCommand, meter_usage
from app.services.quota import QuotaExceededError

FIXED_NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def _seeded_session() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session)
    session.commit()
    return session, engine


def _set_demo_plan(session: Session, plan_code: str) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.code == plan_code))
    assert plan is not None
    subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
    assert subscription is not None
    subscription.plan_id = plan.id
    session.commit()
    return plan


def _record_existing_usage(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    usage_type: str,
    quantity: int,
    key: str,
) -> None:
    session.add(
        UsageEvent(
            tenant_id=tenant_id,
            usage_type=usage_type,
            quantity=quantity,
            idempotency_key=key,
            occurred_at=FIXED_NOW,
        )
    )
    session.commit()


@pytest.mark.parametrize(
    ("plan_code", "usage_type", "limit"),
    [
        ("free", "api_call", 1_000),
        ("free", "ai_token", 100_000),
        ("pro", "api_call", 10_000),
        ("pro", "ai_token", 1_000_000),
    ],
)
@pytest.mark.parametrize(
    ("scenario", "existing_usage", "expected_to_persist"),
    [
        ("just_below", lambda limit: limit - 2, True),
        ("exact_limit", lambda limit: limit - 1, True),
        ("above_limit", lambda limit: limit, False),
    ],
)
def test_quota_boundaries_for_each_plan_and_usage_type(
    plan_code: str,
    usage_type: str,
    limit: int,
    scenario: str,
    existing_usage: object,
    expected_to_persist: bool,
) -> None:
    session, engine = _seeded_session()
    try:
        _set_demo_plan(session, plan_code)
        usage_before_request = existing_usage(limit)
        _record_existing_usage(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type=usage_type,
            quantity=usage_before_request,
            key=f"{plan_code}-{usage_type}-{scenario}-existing",
        )
        command = MeterUsageCommand(
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type=usage_type,
            quantity=1,
            idempotency_key=f"{plan_code}-{usage_type}-{scenario}-request",
        )

        if expected_to_persist:
            result = meter_usage(session, command, now=FIXED_NOW)
            assert result.idempotent_replay is False
        else:
            with pytest.raises(QuotaExceededError) as error:
                meter_usage(session, command, now=FIXED_NOW)
            assert error.value.evaluation.limit == limit
            assert error.value.evaluation.current_usage == limit

        persisted_count = session.scalar(
            select(func.count())
            .select_from(UsageEvent)
            .where(UsageEvent.idempotency_key == command.idempotency_key)
        )
        assert persisted_count == int(expected_to_persist)
    finally:
        session.close()
        engine.dispose()


def test_idempotent_retry_replays_after_the_quota_reaches_its_limit() -> None:
    session, engine = _seeded_session()
    try:
        _record_existing_usage(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type="api_call",
            quantity=999,
            key="idempotent-limit-existing",
        )
        command = MeterUsageCommand(
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type="api_call",
            quantity=1,
            idempotency_key="idempotent-limit-request",
        )

        first = meter_usage(session, command, now=FIXED_NOW)
        replay = meter_usage(session, command, now=FIXED_NOW)

        assert first.idempotent_replay is False
        assert replay.idempotent_replay is True
        assert replay.usage_event.id == first.usage_event.id
        assert (
            session.scalar(
                select(func.count())
                .select_from(UsageEvent)
                .where(UsageEvent.idempotency_key == command.idempotency_key)
            )
            == 1
        )
    finally:
        session.close()
        engine.dispose()


def test_usage_totals_are_isolated_between_tenants() -> None:
    session, engine = _seeded_session()
    try:
        free_plan = session.scalar(select(Plan).where(Plan.code == "free"))
        assert free_plan is not None
        other_tenant = Tenant(id=uuid.uuid4(), name="Other Tenant")
        session.add(other_tenant)
        session.add(
            Subscription(
                tenant_id=other_tenant.id,
                plan_id=free_plan.id,
                status="active",
            )
        )
        session.commit()
        _record_existing_usage(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type="api_call",
            quantity=1_000,
            key="first-tenant-at-limit",
        )

        result = meter_usage(
            session,
            MeterUsageCommand(
                tenant_id=other_tenant.id,
                usage_type="api_call",
                quantity=1,
                idempotency_key="other-tenant-request",
            ),
            now=FIXED_NOW,
        )

        assert result.idempotent_replay is False
    finally:
        session.close()
        engine.dispose()


def test_prior_utc_month_usage_does_not_reduce_current_month_quota() -> None:
    session, engine = _seeded_session()
    try:
        session.add(
            UsageEvent(
                tenant_id=DEMO_FREE_TENANT_ID,
                usage_type="api_call",
                quantity=1_000,
                idempotency_key="prior-month-at-limit",
                occurred_at=datetime(2026, 7, 31, 23, 59, tzinfo=UTC),
            )
        )
        session.commit()

        result = meter_usage(
            session,
            MeterUsageCommand(
                tenant_id=DEMO_FREE_TENANT_ID,
                usage_type="api_call",
                quantity=1,
                idempotency_key="current-month-after-prior-limit",
            ),
            now=FIXED_NOW,
        )

        assert result.idempotent_replay is False
    finally:
        session.close()
        engine.dispose()