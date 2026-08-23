from collections.abc import Generator
from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.data.models import Base, Subscription, UsageEvent
from app.data.seed import DEMO_FREE_TENANT_ID, seed_database
from app.data.session import get_session
from app.main import app


def test_generate_records_one_event_and_replays_duplicate_request() -> None:
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
            headers = {"Idempotency-Key": "generate-api-test-key"}

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


def test_generate_rejects_unsupported_usage_type_without_persisting_an_event() -> None:
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
                headers={"Idempotency-Key": rejected_key},
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
) -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        session.add(
            UsageEvent(
                tenant_id=DEMO_FREE_TENANT_ID,
                usage_type=usage_type,
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
                },
                headers={"Idempotency-Key": f"over-limit-{usage_type}-request"},
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


def test_generate_uses_402_for_subscription_eligibility_not_usage_exhaustion() -> None:
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
                headers={"Idempotency-Key": "inactive-subscription-request"},
            )

        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "subscription_not_eligible"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()