"""Repeatable seed data for local development and capstone demonstrations."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.data.database import create_database_engine
from app.data.models import Plan, Subscription, Tenant

SEED_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "flyrank-capstone-metering-billing-ai")
FREE_PLAN_ID = uuid.uuid5(SEED_NAMESPACE, "plan/free")
PRO_PLAN_ID = uuid.uuid5(SEED_NAMESPACE, "plan/pro")
DEMO_FREE_TENANT_ID = uuid.uuid5(SEED_NAMESPACE, "tenant/demo-free")
DEMO_FREE_SUBSCRIPTION_ID = uuid.uuid5(SEED_NAMESPACE, "subscription/demo-free")


@dataclass(frozen=True)
class PlanSeed:
    """The authoritative values for a seeded plan."""

    id: uuid.UUID
    code: str
    name: str
    monthly_price_cents: int
    included_api_calls: int
    included_ai_tokens: int


FREE_PLAN = PlanSeed(
    id=FREE_PLAN_ID,
    code="free",
    name="Free",
    monthly_price_cents=0,
    included_api_calls=1_000,
    included_ai_tokens=100_000,
)
PRO_PLAN = PlanSeed(
    id=PRO_PLAN_ID,
    code="pro",
    name="Pro",
    monthly_price_cents=0,
    included_api_calls=10_000,
    included_ai_tokens=1_000_000,
)


def _upsert_plan(session: Session, plan_seed: PlanSeed) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.code == plan_seed.code))
    if plan is None:
        plan = Plan(id=plan_seed.id, code=plan_seed.code, name=plan_seed.name)
        session.add(plan)

    plan.name = plan_seed.name
    plan.monthly_price_cents = plan_seed.monthly_price_cents
    plan.included_api_calls = plan_seed.included_api_calls
    plan.included_ai_tokens = plan_seed.included_ai_tokens
    session.flush()
    return plan


def seed_database(session: Session) -> None:
    """Converge the database on the fixed capstone demo records."""
    free_plan = _upsert_plan(session, FREE_PLAN)
    _upsert_plan(session, PRO_PLAN)

    demo_tenant = session.get(Tenant, DEMO_FREE_TENANT_ID)
    if demo_tenant is None:
        demo_tenant = Tenant(id=DEMO_FREE_TENANT_ID, name="Demo Free Tenant")
        session.add(demo_tenant)
    else:
        demo_tenant.name = "Demo Free Tenant"

    demo_subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
    if demo_subscription is None:
        demo_subscription = Subscription(
            id=DEMO_FREE_SUBSCRIPTION_ID,
            tenant_id=demo_tenant.id,
            plan_id=free_plan.id,
            status="active",
        )
        session.add(demo_subscription)
    else:
        demo_subscription.tenant_id = demo_tenant.id
        demo_subscription.plan_id = free_plan.id
        demo_subscription.status = "active"

    session.flush()


def seed_from_environment(engine: Engine | None = None) -> None:
    """Seed the configured database and commit the converged records."""
    database_engine = engine or create_database_engine()
    try:
        with Session(database_engine) as session:
            seed_database(session)
            session.commit()
    finally:
        if engine is None:
            database_engine.dispose()


def main() -> None:
    """Run the repeatable seed command against ``DATABASE_URL``."""
    seed_from_environment()
    print("seeded plans=free,pro tenant=demo-free subscription=active")


if __name__ == "__main__":
    main()