from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import time
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import webhooks as webhook_api
from app.config import StripeWebhookSettings
from app.data.models import Base, Plan, Subscription, Tenant, UsageEvent
from app.data.seed import DEMO_FREE_SUBSCRIPTION_ID, DEMO_FREE_TENANT_ID, seed_database
from app.data.session import get_session
from app.main import app
from app.services.usage_summary import get_usage_summary

FIXED_NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)
SIGNING_SECRET = "whsec_usage_summary_test_secret"
PRO_PRICE_ID = "price_usage_summary_pro"


@pytest.fixture
def usage_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, object]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(
        webhook_api,
        "get_stripe_webhook_settings",
        lambda: StripeWebhookSettings(
            signing_secret=SIGNING_SECRET,
            pro_price_id=PRO_PRICE_ID,
        ),
    )
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _add_usage(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    usage_type: str,
    quantity: int,
    key: str,
    occurred_at: datetime = FIXED_NOW,
    token_category: str | None = None,
) -> None:
    session.add(
        UsageEvent(
            tenant_id=tenant_id,
            usage_type=usage_type,
            token_category=token_category,
            quantity=quantity,
            idempotency_key=key,
            occurred_at=occurred_at,
        )
    )
    session.commit()


def _set_demo_plan(session: Session, code: str) -> None:
    plan = session.scalar(select(Plan).where(Plan.code == code))
    subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
    assert plan is not None and subscription is not None
    subscription.plan_id = plan.id
    subscription.status = "active"
    session.commit()


def test_free_monthly_summary_retains_categories_and_uses_t10_cost() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        _add_usage(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type="api_call",
            quantity=12,
            key="free-api",
        )
        for category, key in (
            ("input", "free-input"),
            ("cached_input", "free-cached"),
            ("output", "free-output"),
            ("reasoning", "free-reasoning"),
        ):
            _add_usage(
                session,
                tenant_id=DEMO_FREE_TENANT_ID,
                usage_type="ai_token",
                token_category=category,
                quantity=1_000_000,
                key=key,
            )

        summary = get_usage_summary(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            as_of=FIXED_NOW,
        )

    assert summary.plan.code == "free"
    assert summary.plan.included_api_calls == 1_000
    assert summary.plan.included_ai_tokens == 100_000
    assert summary.usage.api_calls == 12
    assert summary.usage.input_tokens == 1_000_000
    assert summary.usage.cached_input_tokens == 1_000_000
    assert summary.usage.output_tokens == 1_000_000
    assert summary.usage.reasoning_tokens == 1_000_000
    assert summary.estimated_ai_cost_cents == 91
    engine.dispose()


def test_pro_summary_uses_pro_limits_and_current_month_only() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        _set_demo_plan(session, "pro")
        _add_usage(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type="api_call",
            quantity=20,
            key="pro-current-api",
        )
        _add_usage(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type="ai_token",
            token_category="output",
            quantity=500,
            key="pro-current-output",
        )
        _add_usage(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type="api_call",
            quantity=999,
            key="pro-prior-api",
            occurred_at=FIXED_NOW - timedelta(days=30),
        )

        summary = get_usage_summary(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            as_of=FIXED_NOW,
        )

    assert summary.plan.code == "pro"
    assert summary.plan.included_api_calls == 10_000
    assert summary.plan.included_ai_tokens == 1_000_000
    assert summary.usage.api_calls == 20
    assert summary.usage.output_tokens == 500
    assert summary.remaining_api_calls == 9_980
    assert summary.remaining_ai_tokens == 999_500
    engine.dispose()


def test_usage_summary_isolated_to_requested_tenant() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    other_tenant_id = uuid.uuid4()
    with Session(engine) as session:
        seed_database(session)
        free_plan = session.scalar(select(Plan).where(Plan.code == "free"))
        assert free_plan is not None
        session.add(Tenant(id=other_tenant_id, name="Other"))
        session.add(
            Subscription(
                tenant_id=other_tenant_id,
                plan_id=free_plan.id,
                status="active",
            )
        )
        session.commit()
        _add_usage(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            usage_type="api_call",
            quantity=7,
            key="first-tenant",
        )
        _add_usage(
            session,
            tenant_id=other_tenant_id,
            usage_type="api_call",
            quantity=700,
            key="second-tenant",
        )

        summary = get_usage_summary(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            as_of=FIXED_NOW,
        )

    assert summary.usage.api_calls == 7
    engine.dispose()


def _signed_post(client: TestClient, event: dict[str, object]) -> object:
    payload = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        SIGNING_SECRET.encode(),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhooks/stripe",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": f"t={timestamp},v1={signature}",
        },
    )


def test_get_usage_reflects_verified_stripe_pro_upgrade(
    usage_client: tuple[TestClient, object],
) -> None:
    client, _engine = usage_client
    tenant_reference = str(DEMO_FREE_TENANT_ID)
    checkout = {
        "id": "evt_usage_checkout",
        "object": "event",
        "created": 1_700_000_000,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_usage",
                "mode": "subscription",
                "customer": "cus_usage",
                "subscription": "sub_usage",
                "client_reference_id": tenant_reference,
                "metadata": {"tenant_id": tenant_reference},
            }
        },
    }
    update = {
        "id": "evt_usage_upgrade",
        "object": "event",
        "created": 1_700_000_010,
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_usage",
                "customer": "cus_usage",
                "status": "active",
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_700_100_000,
                "items": {"data": [{"price": {"id": PRO_PRICE_ID}}]},
            }
        },
    }

    assert _signed_post(client, checkout).status_code == 200
    assert _signed_post(client, update).status_code == 200
    response = client.get(f"/usage?tenant_id={DEMO_FREE_TENANT_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == {
        "code": "pro",
        "status": "active",
        "api_call_limit": 10_000,
        "ai_token_limit": 1_000_000,
    }