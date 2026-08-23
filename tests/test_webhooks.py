from collections.abc import Generator
from datetime import UTC, datetime
import hashlib
import hmac
import json
import time
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import webhooks as webhook_api
from app.config import StripeWebhookSettings
from app.data.models import Base, Plan, ProcessedWebhookEvent, Subscription, Tenant
from app.data.seed import DEMO_FREE_SUBSCRIPTION_ID, DEMO_FREE_TENANT_ID, seed_database
from app.data.session import get_session
from app.main import app

SIGNING_SECRET = "whsec_deterministic_test_secret"
PRO_PRICE_ID = "price_test_pro_monthly"
WEBHOOK_SETTINGS = StripeWebhookSettings(
    signing_secret=SIGNING_SECRET,
    pro_price_id=PRO_PRICE_ID,
)


@pytest.fixture
def webhook_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, object], None, None]:
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
        webhook_api,
        "get_stripe_webhook_settings",
        lambda: WEBHOOK_SETTINGS,
    )
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _signed_headers(
    payload: bytes,
    *,
    signing_secret: str = SIGNING_SECRET,
    timestamp: int | None = None,
) -> dict[str, str]:
    signed_at = int(time.time()) if timestamp is None else timestamp
    signed_payload = f"{signed_at}.".encode() + payload
    signature = hmac.new(
        signing_secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "Stripe-Signature": f"t={signed_at},v1={signature}",
    }


def _post_signed(
    client: TestClient,
    event: dict[str, object],
    *,
    signing_secret: str = SIGNING_SECRET,
    timestamp: int | None = None,
) -> object:
    payload = json.dumps(event, separators=(",", ":")).encode()
    return client.post(
        "/webhooks/stripe",
        content=payload,
        headers=_signed_headers(
            payload,
            signing_secret=signing_secret,
            timestamp=timestamp,
        ),
    )


def _checkout_event(
    event_id: str,
    tenant_id: uuid.UUID = DEMO_FREE_TENANT_ID,
    *,
    created: int = 1_700_000_000,
) -> dict[str, object]:
    tenant_reference = str(tenant_id)
    return {
        "id": event_id,
        "object": "event",
        "created": created,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_completed",
                "customer": "cus_test_webhook",
                "subscription": "sub_test_webhook",
                "client_reference_id": tenant_reference,
                "metadata": {"tenant_id": tenant_reference},
            }
        },
    }


def _subscription_event(
    event_id: str,
    event_type: str,
    *,
    price_id: str = PRO_PRICE_ID,
    status: str = "active",
    created: int = 1_700_000_010,
) -> dict[str, object]:
    return {
        "id": event_id,
        "object": "event",
        "created": created,
        "type": event_type,
        "data": {
            "object": {
                "id": "sub_test_webhook",
                "customer": "cus_test_webhook",
                "status": status,
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_700_100_000,
                "items": {"data": [{"price": {"id": price_id}}]},
            }
        },
    }


def _subscription_state(engine: object, tenant_id: uuid.UUID) -> tuple[str, str, str | None]:
    with Session(engine) as session:  # type: ignore[arg-type]
        subscription = session.scalar(
            select(Subscription).where(Subscription.tenant_id == tenant_id)
        )
        assert subscription is not None
        plan = session.get(Plan, subscription.plan_id)
        assert plan is not None
        return plan.code, subscription.status, subscription.stripe_subscription_id


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        ({}, b'{"id":"evt_missing","type":"checkout.session.completed"}'),
        (
            {"Stripe-Signature": "t=1,v1=forged"},
            b'{"id":"evt_forged","type":"checkout.session.completed"}',
        ),
    ],
)
def test_missing_or_forged_signature_returns_400_without_mutation(
    webhook_client: tuple[TestClient, object],
    headers: dict[str, str],
    body: bytes,
) -> None:
    client, engine = webhook_client

    response = client.post("/webhooks/stripe", content=body, headers=headers)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_stripe_signature"
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == ("free", "active", None)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.scalar(select(func.count()).select_from(ProcessedWebhookEvent)) == 0


def test_wrong_secret_and_stale_signature_return_400_without_mutation(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    event = _checkout_event("evt_rejected")

    wrong_secret = _post_signed(client, event, signing_secret="whsec_wrong_secret")
    stale = _post_signed(client, event, timestamp=int(time.time()) - 301)

    assert wrong_secret.status_code == 400
    assert stale.status_code == 400
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == ("free", "active", None)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.scalar(select(func.count()).select_from(ProcessedWebhookEvent)) == 0


def test_verified_checkout_upgrades_only_referenced_tenant_and_persists_identifiers(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    other_tenant_id = uuid.uuid4()
    with Session(engine) as session:  # type: ignore[arg-type]
        free_plan = session.scalar(select(Plan).where(Plan.code == "free"))
        assert free_plan is not None
        session.add(Tenant(id=other_tenant_id, name="Other tenant"))
        session.add(
            Subscription(
                tenant_id=other_tenant_id,
                plan_id=free_plan.id,
                status="active",
            )
        )
        session.commit()

    response = _post_signed(client, _checkout_event("evt_checkout_upgrade"))

    assert response.status_code == 200
    assert response.json() == {
        "received": True,
        "handled": True,
        "idempotent_replay": False,
    }
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == (
        "pro",
        "active",
        "sub_test_webhook",
    )
    assert _subscription_state(engine, other_tenant_id) == ("free", "active", None)
    with Session(engine) as session:  # type: ignore[arg-type]
        subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
        assert subscription is not None
        assert subscription.stripe_customer_id == "cus_test_webhook"
        assert (
            session.scalar(select(func.count()).select_from(ProcessedWebhookEvent)) == 1
        )


def test_verified_subscription_update_uses_configured_price_for_entitlement(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    assert _post_signed(client, _checkout_event("evt_checkout_for_update")).status_code == 200

    response = _post_signed(
        client,
        _subscription_event("evt_subscription_update", "customer.subscription.updated"),
    )

    assert response.status_code == 200
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == (
        "pro",
        "active",
        "sub_test_webhook",
    )
    with Session(engine) as session:  # type: ignore[arg-type]
        subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
        assert subscription is not None
        # SQLite does not preserve tzinfo for DateTime columns; the service
        # constructs these values in UTC before persistence.
        assert subscription.current_period_start is not None
        assert subscription.current_period_end is not None
        assert subscription.current_period_start.replace(tzinfo=UTC) == datetime.fromtimestamp(
            1_700_000_000, UTC
        )
        assert subscription.current_period_end.replace(tzinfo=UTC) == datetime.fromtimestamp(
            1_700_100_000, UTC
        )


def test_subscription_update_for_other_price_removes_pro_entitlement(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    assert _post_signed(client, _checkout_event("evt_checkout_for_wrong_price")).status_code == 200

    response = _post_signed(
        client,
        _subscription_event(
            "evt_subscription_wrong_price",
            "customer.subscription.updated",
            price_id="price_not_configured",
        ),
    )

    assert response.status_code == 200
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == (
        "free",
        "active",
        "sub_test_webhook",
    )


def test_subscription_deletion_restores_free_access(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    assert _post_signed(client, _checkout_event("evt_checkout_for_delete")).status_code == 200

    response = _post_signed(
        client,
        _subscription_event(
            "evt_subscription_delete",
            "customer.subscription.deleted",
            status="canceled",
        ),
    )

    assert response.status_code == 200
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == (
        "free",
        "canceled",
        "sub_test_webhook",
    )


def test_delayed_update_or_checkout_cannot_restore_access_after_newer_deletion(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    assert (
        _post_signed(
            client,
            _checkout_event("evt_checkout_ordered", created=1_700_000_000),
        ).status_code
        == 200
    )
    assert (
        _post_signed(
            client,
            _subscription_event(
                "evt_delete_newer",
                "customer.subscription.deleted",
                status="canceled",
                created=1_700_000_030,
            ),
        ).status_code
        == 200
    )

    delayed_update = _post_signed(
        client,
        _subscription_event(
            "evt_update_delayed",
            "customer.subscription.updated",
            created=1_700_000_020,
        ),
    )
    delayed_checkout = _post_signed(
        client,
        _checkout_event("evt_checkout_delayed", created=1_700_000_010),
    )

    assert delayed_update.status_code == 200
    assert delayed_checkout.status_code == 200
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == (
        "free",
        "canceled",
        "sub_test_webhook",
    )
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.scalar(select(func.count()).select_from(ProcessedWebhookEvent)) == 4


def test_same_second_updates_reconcile_authoritative_stripe_state(
    webhook_client: tuple[TestClient, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine = webhook_client
    assert (
        _post_signed(
            client,
            _checkout_event("evt_checkout_for_same_second", created=1_700_000_000),
        ).status_code
        == 200
    )
    assert (
        _post_signed(
            client,
            _subscription_event(
                "evt_update_non_pro",
                "customer.subscription.updated",
                price_id="price_not_configured",
                created=1_700_000_020,
            ),
        ).status_code
        == 200
    )
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID)[0] == "free"

    authoritative_event = _subscription_event(
        "evt_authoritative_fixture",
        "customer.subscription.updated",
        price_id=PRO_PRICE_ID,
        created=1_700_000_020,
    )
    authoritative_object = authoritative_event["data"]["object"]  # type: ignore[index]
    assert isinstance(authoritative_object, dict)
    monkeypatch.setattr(
        webhook_api,
        "_retrieve_authoritative_subscription",
        lambda subscription_id: authoritative_object,
    )

    same_second_response = _post_signed(
        client,
        _subscription_event(
            "evt_update_same_second",
            "customer.subscription.updated",
            price_id="price_not_configured",
            created=1_700_000_020,
        ),
    )

    assert same_second_response.status_code == 200
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == (
        "pro",
        "active",
        "sub_test_webhook",
    )

    delayed_intermediate_response = _post_signed(
        client,
        _subscription_event(
            "evt_update_delayed_after_reconciliation",
            "customer.subscription.updated",
            price_id="price_not_configured",
            created=1_700_000_021,
        ),
    )

    assert delayed_intermediate_response.status_code == 200
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == (
        "pro",
        "active",
        "sub_test_webhook",
    )


def test_ambiguous_event_without_authoritative_state_fails_without_mutation(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    assert (
        _post_signed(
            client,
            _checkout_event("evt_checkout_for_authority_failure", created=1_700_000_000),
        ).status_code
        == 200
    )
    assert (
        _post_signed(
            client,
            _subscription_event(
                "evt_update_before_authority_failure",
                "customer.subscription.updated",
                price_id="price_not_configured",
                created=1_700_000_020,
            ),
        ).status_code
        == 200
    )

    response = _post_signed(
        client,
        _subscription_event(
            "evt_ambiguous_authority_failure",
            "customer.subscription.updated",
            created=1_700_000_020,
        ),
    )

    assert response.status_code == 502
    assert (
        response.json()["detail"]["code"] == "stripe_authoritative_state_unavailable"
    )
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == (
        "free",
        "active",
        "sub_test_webhook",
    )
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.scalar(select(func.count()).select_from(ProcessedWebhookEvent)) == 2


def test_duplicate_valid_checkout_has_one_effect_and_successful_idempotent_response(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    event = _checkout_event("evt_checkout_duplicate")

    first = _post_signed(client, event)
    duplicate = _post_signed(client, event)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["idempotent_replay"] is True
    with Session(engine) as session:  # type: ignore[arg-type]
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProcessedWebhookEvent)
                .where(
                    ProcessedWebhookEvent.stripe_event_id == "evt_checkout_duplicate"
                )
            )
            == 1
        )
        subscription = session.get(Subscription, DEMO_FREE_SUBSCRIPTION_ID)
        assert subscription is not None
        assert subscription.stripe_subscription_id == "sub_test_webhook"


def test_mismatched_checkout_references_and_unmapped_subscription_fail_safely(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    mismatched = _checkout_event("evt_mismatched_reference")
    mismatched_object = mismatched["data"]["object"]  # type: ignore[index]
    assert isinstance(mismatched_object, dict)
    mismatched_object["client_reference_id"] = str(uuid.uuid4())

    mismatched_response = _post_signed(client, mismatched)
    unmapped_response = _post_signed(
        client,
        _subscription_event("evt_unmapped_subscription", "customer.subscription.updated"),
    )

    assert mismatched_response.status_code == 422
    assert unmapped_response.status_code == 422
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == ("free", "active", None)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.scalar(select(func.count()).select_from(ProcessedWebhookEvent)) == 0


def test_verified_unsupported_event_is_acknowledged_without_state_change(
    webhook_client: tuple[TestClient, object],
) -> None:
    client, engine = webhook_client
    response = _post_signed(
        client,
        {
            "id": "evt_unsupported",
            "object": "event",
            "type": "invoice.paid",
            "data": {"object": {"id": "in_test"}},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "received": True,
        "handled": False,
        "idempotent_replay": False,
    }
    assert _subscription_state(engine, DEMO_FREE_TENANT_ID) == ("free", "active", None)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.scalar(select(func.count()).select_from(ProcessedWebhookEvent)) == 0