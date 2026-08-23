from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.data.models import Base, Plan, Subscription, Tenant
from app.data.seed import (
    DEMO_FREE_SUBSCRIPTION_ID,
    DEMO_FREE_TENANT_ID,
    FREE_PLAN,
    PRO_PLAN,
    seed_database,
)


def test_seed_is_repeatable_and_creates_expected_demo_state() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_database(session)
        session.commit()

        plans = {
            plan.code: plan
            for plan in session.scalars(select(Plan).order_by(Plan.code)).all()
        }
        assert set(plans) == {"free", "pro"}
        assert session.scalar(select(func.count()).select_from(Plan)) == 2
        assert session.scalar(select(func.count()).select_from(Tenant)) == 1
        assert session.scalar(select(func.count()).select_from(Subscription)) == 1

        assert plans["free"].included_api_calls == 1_000
        assert plans["free"].included_ai_tokens == 100_000
        assert plans["pro"].included_api_calls == 10_000
        assert plans["pro"].included_ai_tokens == 1_000_000
        assert plans["free"].monthly_price_cents == 0
        assert plans["pro"].monthly_price_cents == 0

        demo_tenant = session.get(Tenant, DEMO_FREE_TENANT_ID)
        demo_subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
        assert demo_tenant is not None
        assert demo_tenant.name == "Demo Free Tenant"
        assert demo_subscription is not None
        assert demo_subscription.tenant_id == demo_tenant.id
        assert demo_subscription.plan_id == plans["free"].id
        assert demo_subscription.status == "active"

        seed_database(session)
        session.commit()

        assert session.scalar(select(func.count()).select_from(Plan)) == 2
        assert session.scalar(select(func.count()).select_from(Tenant)) == 1
        assert session.scalar(select(func.count()).select_from(Subscription)) == 1

    engine.dispose()