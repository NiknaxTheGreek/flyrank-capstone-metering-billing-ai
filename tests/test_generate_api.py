from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.data.models import Base, UsageEvent
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