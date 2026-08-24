from collections.abc import Generator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.data.models import Base, UsageEvent
from app.data.seed import DEMO_FREE_TENANT_ID, seed_database
from app.data.session import get_session
from app.main import app


def _demo_engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        session.commit()
    return engine


def test_demo_is_hidden_when_demo_mode_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    with TestClient(app) as client:
        response = client.get("/demo")
    assert response.status_code == 404


def test_demo_supports_real_request_retry_report_and_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    engine = _demo_engine()

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            page = client.get("/demo")
            assert page.status_code == 200
            assert "Make a real metering request" in page.text

            payload = {
                "usage_type": "api_call",
                "quantity": 1,
                "idempotency_key": "public-demo-retry",
            }
            first = client.post("/demo/api/generate", json=payload)
            retry = client.post("/demo/api/generate", json=payload)
            assert first.status_code == 201
            assert retry.status_code == 200
            assert first.json()["result"]["idempotent_replay"] is False
            assert retry.json()["result"]["idempotent_replay"] is True
            assert retry.json()["result"]["usage_event_id"] == first.json()["result"]["usage_event_id"]

            usage = client.get("/demo/api/usage")
            assert usage.status_code == 200
            assert usage.json()["usage"]["api_calls"] == 1

            csv_report = client.get("/demo/report.csv")
            assert csv_report.status_code == 200
            assert "tenant_id" in csv_report.text
            assert str(DEMO_FREE_TENANT_ID) in csv_report.text

            json_report = client.get("/demo/report.json")
            assert json_report.status_code == 200
            assert json_report.json()["usage"]["api_calls"] == 1

            reset = client.post("/demo/api/reset")
            assert reset.status_code == 200
            assert reset.json()["reset"] is True
            assert reset.json()["usage_summary"]["usage"]["api_calls"] == 0

        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(UsageEvent)
                    .where(UsageEvent.tenant_id == DEMO_FREE_TENANT_ID)
                )
                == 0
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
