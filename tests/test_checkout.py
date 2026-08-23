from collections.abc import Generator
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from stripe import StripeError

from app.api import checkout as checkout_api
from app.config import StripeConfigurationError, StripeTestSettings
from app.data.models import Base, Plan, Subscription
from app.data.seed import DEMO_FREE_SUBSCRIPTION_ID, DEMO_FREE_TENANT_ID, seed_database
from app.data.session import get_session
from app.main import app
from app.services.checkout import (
    CheckoutNotEligibleError,
    CheckoutSessionResult,
    CheckoutTenantNotFoundError,
    StripeCheckoutUnavailableError,
    create_pro_checkout_session,
)
from app.services.checkout_authorization import create_checkout_tenant_proof

TEST_SETTINGS = StripeTestSettings(
    secret_key="sk_test_checkout_configuration",
    pro_price_id="price_test_pro_monthly",
    success_url="https://example.test/billing/success?session_id={CHECKOUT_SESSION_ID}",
    cancel_url="https://example.test/billing/cancel",
)


class FakeCheckoutSessions:
    """Record Checkout parameters and return a hosted-session shaped object."""

    def __init__(self) -> None:
        self.params: dict[str, object] | None = None

    def create(self, *, params: dict[str, object]) -> SimpleNamespace:
        self.params = params
        return SimpleNamespace(
            id="cs_test_checkout_session",
            url="https://checkout.stripe.test/c/pay/cs_test_checkout_session",
        )


def _seeded_session() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session)
    session.commit()
    return session, engine


def _fake_client(checkout_sessions: FakeCheckoutSessions) -> SimpleNamespace:
    return SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=checkout_sessions))
    )


def _checkout_headers(tenant_id: uuid.UUID = DEMO_FREE_TENANT_ID) -> dict[str, str]:
    return {
        "X-Checkout-Tenant-Proof": create_checkout_tenant_proof(
            tenant_id,
            "test-session-secret",
        )
    }


def test_free_tenant_checkout_has_expected_stripe_parameters_and_no_local_upgrade() -> None:
    session, engine = _seeded_session()
    try:
        checkout_sessions = FakeCheckoutSessions()
        result = create_pro_checkout_session(
            session,
            tenant_id=DEMO_FREE_TENANT_ID,
            settings=TEST_SETTINGS,
            stripe_client=_fake_client(checkout_sessions),
        )

        assert result == CheckoutSessionResult(
            session_id="cs_test_checkout_session",
            url="https://checkout.stripe.test/c/pay/cs_test_checkout_session",
        )
        assert checkout_sessions.params == {
            "mode": "subscription",
            "line_items": [{"price": "price_test_pro_monthly", "quantity": 1}],
            "success_url": TEST_SETTINGS.success_url,
            "cancel_url": TEST_SETTINGS.cancel_url,
            "client_reference_id": str(DEMO_FREE_TENANT_ID),
            "metadata": {"tenant_id": str(DEMO_FREE_TENANT_ID)},
        }
        subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
        assert subscription is not None
        free_plan = session.get(Plan, subscription.plan_id)
        assert free_plan is not None
        assert free_plan.code == "free"
        assert subscription.status == "active"
        assert subscription.stripe_subscription_id is None
    finally:
        session.close()
        engine.dispose()


def test_checkout_rejects_unknown_and_non_free_tenants() -> None:
    session, engine = _seeded_session()
    try:
        checkout_sessions = FakeCheckoutSessions()
        with pytest.raises(CheckoutTenantNotFoundError):
            create_pro_checkout_session(
                session,
                tenant_id=uuid.uuid4(),
                settings=TEST_SETTINGS,
                stripe_client=_fake_client(checkout_sessions),
            )

        subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
        pro_plan = session.scalar(select(Plan).where(Plan.code == "pro"))
        assert subscription is not None
        assert pro_plan is not None
        subscription.plan_id = pro_plan.id
        session.commit()
        with pytest.raises(CheckoutNotEligibleError):
            create_pro_checkout_session(
                session,
                tenant_id=DEMO_FREE_TENANT_ID,
                settings=TEST_SETTINGS,
                stripe_client=_fake_client(checkout_sessions),
            )

        free_plan = session.scalar(select(Plan).where(Plan.code == "free"))
        assert free_plan is not None
        subscription.plan_id = free_plan.id
        subscription.status = "canceled"
        session.commit()
        with pytest.raises(CheckoutNotEligibleError):
            create_pro_checkout_session(
                session,
                tenant_id=DEMO_FREE_TENANT_ID,
                settings=TEST_SETTINGS,
                stripe_client=_fake_client(checkout_sessions),
            )
    finally:
        session.close()
        engine.dispose()


def test_checkout_wraps_stripe_failures_without_mutating_the_subscription() -> None:
    session, engine = _seeded_session()
    try:
        class FailingCheckoutSessions:
            def create(self, *, params: dict[str, object]) -> SimpleNamespace:
                raise StripeError("Stripe sandbox unavailable")

        with pytest.raises(StripeCheckoutUnavailableError):
            create_pro_checkout_session(
                session,
                tenant_id=DEMO_FREE_TENANT_ID,
                settings=TEST_SETTINGS,
                stripe_client=_fake_client(FailingCheckoutSessions()),
            )

        subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
        assert subscription is not None
        assert session.get(Plan, subscription.plan_id).code == "free"  # type: ignore[union-attr]
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("service_error", "expected_status", "expected_code"),
    [
        (CheckoutTenantNotFoundError(), 404, "tenant_not_found"),
        (CheckoutNotEligibleError(), 409, "checkout_not_eligible"),
        (
            StripeConfigurationError("missing Stripe settings"),
            503,
            "stripe_not_configured",
        ),
        (
            StripeCheckoutUnavailableError(),
            502,
            "stripe_checkout_unavailable",
        ),
    ],
)
def test_checkout_api_maps_service_errors(
    monkeypatch: pytest.MonkeyPatch,
    service_error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        session.commit()

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    def raise_service_error(*args: object, **kwargs: object) -> CheckoutSessionResult:
        raise service_error

    monkeypatch.setattr(
        checkout_api,
        "create_pro_checkout_session",
        raise_service_error,
    )
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/checkout",
                json={"tenant_id": str(DEMO_FREE_TENANT_ID)},
                headers=_checkout_headers(),
            )

        assert response.status_code == expected_status
        assert response.json()["detail"]["code"] == expected_code
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_checkout_api_returns_hosted_session_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        session.commit()

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(
        checkout_api,
        "create_pro_checkout_session",
        lambda *args, **kwargs: CheckoutSessionResult(
            session_id="cs_test_api_session",
            url="https://checkout.stripe.test/c/pay/cs_test_api_session",
        ),
    )
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/checkout",
                json={"tenant_id": str(DEMO_FREE_TENANT_ID)},
                headers=_checkout_headers(),
            )

        assert response.status_code == 201
        assert response.json() == {
            "checkout_session_id": "cs_test_api_session",
            "checkout_url": "https://checkout.stripe.test/c/pay/cs_test_api_session",
        }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_checkout_api_rejects_missing_or_wrong_tenant_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    def service_must_not_run(*args: object, **kwargs: object) -> CheckoutSessionResult:
        raise AssertionError("Unauthorized requests must not reach Checkout creation.")

    monkeypatch.setattr(
        checkout_api,
        "create_pro_checkout_session",
        service_must_not_run,
    )
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            missing_proof = client.post(
                "/api/checkout",
                json={"tenant_id": str(DEMO_FREE_TENANT_ID)},
            )
            wrong_tenant_proof = client.post(
                "/api/checkout",
                json={"tenant_id": str(DEMO_FREE_TENANT_ID)},
                headers=_checkout_headers(uuid.uuid4()),
            )

        assert missing_proof.status_code == 403
        assert missing_proof.json()["detail"]["code"] == "checkout_tenant_not_authorized"
        assert wrong_tenant_proof.status_code == 403
        assert (
            wrong_tenant_proof.json()["detail"]["code"]
            == "checkout_tenant_not_authorized"
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_checkout_api_requires_a_runtime_authorization_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/checkout",
                json={"tenant_id": str(DEMO_FREE_TENANT_ID)},
                headers=_checkout_headers(),
            )

        assert response.status_code == 503
        assert (
            response.json()["detail"]["code"]
            == "checkout_authorization_not_configured"
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()