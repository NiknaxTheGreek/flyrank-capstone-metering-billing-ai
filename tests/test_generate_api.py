from collections.abc import Generator
from datetime import UTC, datetime
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.data.models import Base, Plan, Subscription, Tenant, UsageEvent
from app.data.seed import DEMO_FREE_TENANT_ID, seed_database
from app.data.session import get_session
from app.main import app
from app.services.checkout_authorization import create_tenant_proof

TEST_SESSION_SECRET = "test-generate-tenant-proof-secret"


def _generate_headers(
    idempotency_key: str,
    tenant_id=DEMO_FREE_TENANT_ID,
) -> dict[str, str]:
    return {
        "Idempotency-Key": idempotency_key,
        "X-Tenant-Proof": create_tenant_proof(
            tenant_id,
            TEST_SESSION_SECRET,
            audience="generate",
        ),
    }


def test_generate_records_one_event_and_replays_duplicate_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
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

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            request_payload = {
                "tenant_id": str(DEMO_FREE_TENANT_ID),
                "usage_type": "api_call",
                "quantity": 1,
            }
            headers = _generate_headers("generate-api-test-key")

            first_response = client.post(
                "/api/generate",
                json=request_payload,
                headers=headers,
            )
            assert first_response.status_code == 201
            assert first_response.json()["idempotent_replay"] is False

            duplicate_response = client.post(
                "/api/generate",
                json=request_payload,
                headers=headers,
            )
            assert duplicate_response.status_code == 200
            assert duplicate_response.json()["idempotent_replay"] is True
            assert duplicate_response.json()["usage_event_id"] == first_response.json()[
                "usage_event_id"
            ]

        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(UsageEvent)
                    .where(
                        UsageEvent.tenant_id == DEMO_FREE_TENANT_ID,
                        UsageEvent.idempotency_key == "generate-api-test-key",
                    )
                )
                == 1
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_generate_rejects_unsupported_usage_type_without_persisting_an_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
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

    rejected_key = "unsupported-usage-type-request"
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/generate",
                json={
                    "tenant_id": str(DEMO_FREE_TENANT_ID),
                    "usage_type": "unsupported_type",
                    "quantity": 1,
                },
                headers=_generate_headers(rejected_key),
            )

        assert response.status_code == 422
        assert any(
            error["loc"] == ["body", "usage_type"]
            and error["type"] == "literal_error"
            for error in response.json()["detail"]
        )
        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(UsageEvent)
                    .where(UsageEvent.idempotency_key == rejected_key)
                )
                == 0
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.parametrize(
    ("usage_type", "limit"),
    [
        ("api_call", 1_000),
        ("ai_token", 100_000),
    ],
)
def test_generate_returns_429_without_persisting_an_over_limit_request(
    usage_type: str,
    limit: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        token_category = "input" if usage_type == "ai_token" else None
        session.add(
            UsageEvent(
                tenant_id=DEMO_FREE_TENANT_ID,
                usage_type=usage_type,
                token_category=token_category,
                quantity=limit,
                idempotency_key=f"{usage_type}-limit-already-reached",
                occurred_at=datetime.now(UTC),
            )
        )
        session.commit()

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/generate",
                json={
                    "tenant_id": str(DEMO_FREE_TENANT_ID),
                    "usage_type": usage_type,
                    "quantity": 1,
                    **(
                        {"token_category": "input"}
                        if usage_type == "ai_token"
                        else {}
                    ),
                },
                headers=_generate_headers(f"over-limit-{usage_type}-request"),
            )

        assert response.status_code == 429
        assert response.json()["detail"]["code"] == "quota_exhausted"
        assert "quota is exhausted" in response.json()["detail"]["message"]
        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(UsageEvent)
                    .where(
                        UsageEvent.idempotency_key
                        == f"over-limit-{usage_type}-request"
                    )
                )
                == 0
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_generate_uses_402_for_subscription_eligibility_not_usage_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        subscription = session.scalar(
            select(Subscription).where(Subscription.tenant_id == DEMO_FREE_TENANT_ID)
        )
        assert subscription is not None
        subscription.status = "inactive"
        session.commit()

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/generate",
                json={
                    "tenant_id": str(DEMO_FREE_TENANT_ID),
                    "usage_type": "api_call",
                    "quantity": 1,
                },
                headers=_generate_headers("inactive-subscription-request"),
            )

        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "subscription_not_eligible"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.parametrize(
    "payload",
    [
        {"usage_type": "ai_token", "quantity": 1},
        {"usage_type": "api_call", "quantity": 1, "token_category": "input"},
        {"usage_type": "api_call", "quantity": 0},
    ],
)
def test_generate_rejects_invalid_combinations_and_boundaries_without_persisting(
    payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
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

    rejected_key = f"invalid-request-{payload['usage_type']}-{payload['quantity']}"
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/generate",
                json={"tenant_id": str(DEMO_FREE_TENANT_ID), **payload},
                headers=_generate_headers(rejected_key),
            )

        assert response.status_code == 422
        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(UsageEvent)
                    .where(UsageEvent.idempotency_key == rejected_key)
                )
                == 0
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_generate_rejects_another_tenants_proof_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    other_tenant_id = uuid.uuid4()
    with Session(engine) as session:
        seed_database(session)
        free_plan = session.scalar(select(Plan).where(Plan.code == "free"))
        assert free_plan is not None
        session.add(Tenant(id=other_tenant_id, name="Other tenant"))
        session.flush()
        session.add(
            Subscription(
                tenant_id=other_tenant_id,
                plan_id=free_plan.id,
                status="active",
            )
        )
        session.commit()

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    rejected_key = "cross-tenant-generate"
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/generate",
                json={
                    "tenant_id": str(other_tenant_id),
                    "usage_type": "api_call",
                    "quantity": 1,
                },
                headers=_generate_headers(rejected_key),
            )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "tenant_not_authorized"
        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(UsageEvent)
                    .where(UsageEvent.idempotency_key == rejected_key)
                )
                == 0
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()