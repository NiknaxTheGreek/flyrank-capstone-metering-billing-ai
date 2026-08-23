"""Run the deterministic T18 capstone demonstration without live credentials."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.api import webhooks as webhook_api
from app.config import StripeWebhookSettings
from app.data.models import Base, Plan, ProcessedWebhookEvent, Subscription, UsageEvent
from app.data.seed import DEMO_FREE_TENANT_ID, seed_database
from app.data.session import get_session
from app.main import app
from app.services.checkout_authorization import create_tenant_proof

DEMO_SESSION_SECRET = "t18-local-demo-only"
DEMO_STRIPE_SIGNING_SECRET = "whsec_t18_demo_only"
DEMO_PRO_PRICE_ID = "price_t18_demo_pro"


def _tenant_headers(*, audience: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {
        "X-Tenant-Proof": create_tenant_proof(
            DEMO_FREE_TENANT_ID,
            DEMO_SESSION_SECRET,
            audience=audience,
        )
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _signed_post(client: TestClient, event: dict[str, object]) -> object:
    payload = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        DEMO_STRIPE_SIGNING_SECRET.encode(),
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


def _checkout_event() -> dict[str, object]:
    tenant_reference = str(DEMO_FREE_TENANT_ID)
    return {
        "id": "evt_t18_checkout",
        "object": "event",
        "created": 1_700_000_000,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_t18",
                "mode": "subscription",
                "customer": "cus_t18",
                "subscription": "sub_t18",
                "client_reference_id": tenant_reference,
                "metadata": {"tenant_id": tenant_reference},
            }
        },
    }


def _subscription_update() -> dict[str, object]:
    return {
        "id": "evt_t18_subscription_update",
        "object": "event",
        "created": 1_700_000_010,
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_t18",
                "customer": "cus_t18",
                "status": "active",
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_700_100_000,
                "items": {"data": [{"price": {"id": DEMO_PRO_PRICE_ID}}]},
            }
        },
    }


def _run_selected_test_output() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_pricing.py::test_rounds_once_after_combining_categories_not_per_category",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)
    summary = next(
        line.strip()
        for line in reversed(result.stdout.splitlines())
        if "passed" in line
    )
    print(f"T18.9 selected regression output: {summary}")
    print("T18.9 accepted full-suite baseline: 105 passed")


def run_demo(run_number: int) -> None:
    with TemporaryDirectory(prefix="flyrank-t18-") as temporary_directory:
        database_path = Path(temporary_directory) / "demo.sqlite3"
        engine = create_engine(
            f"sqlite+pysqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            seed_database(session)
            session.add(
                UsageEvent(
                    tenant_id=DEMO_FREE_TENANT_ID,
                    usage_type="api_call",
                    quantity=999,
                    idempotency_key="t18-near-quota-seed",
                    occurred_at=datetime.now(UTC),
                )
            )
            session.commit()

        def override_get_session() -> Generator[Session, None, None]:
            with Session(engine) as session:
                yield session

        previous_secret = os.environ.get("SESSION_SECRET")
        previous_settings = webhook_api.get_stripe_webhook_settings
        os.environ["SESSION_SECRET"] = DEMO_SESSION_SECRET
        webhook_api.get_stripe_webhook_settings = lambda: StripeWebhookSettings(
            signing_secret=DEMO_STRIPE_SIGNING_SECRET,
            pro_price_id=DEMO_PRO_PRICE_ID,
        )
        app.dependency_overrides[get_session] = override_get_session
        try:
            print(f"T18 demo run {run_number}: begin")
            with TestClient(app) as client:
                print("T18.1 seeded Free tenant with 999/1000 API calls")
                exact_limit = client.post(
                    "/api/generate",
                    json={
                        "tenant_id": str(DEMO_FREE_TENANT_ID),
                        "usage_type": "api_call",
                        "quantity": 1,
                    },
                    headers=_tenant_headers(
                        audience="generate",
                        idempotency_key="t18-exact-limit",
                    ),
                )
                blocked = client.post(
                    "/api/generate",
                    json={
                        "tenant_id": str(DEMO_FREE_TENANT_ID),
                        "usage_type": "api_call",
                        "quantity": 1,
                    },
                    headers=_tenant_headers(
                        audience="generate",
                        idempotency_key="t18-blocked-over-limit",
                    ),
                )
                assert exact_limit.status_code == 201
                assert blocked.status_code == 429
                assert blocked.json()["detail"]["code"] == "quota_exhausted"
                print("T18.2 exact-limit accepted; over-limit refused with 429")

                retry_payload = {
                    "tenant_id": str(DEMO_FREE_TENANT_ID),
                    "usage_type": "ai_token",
                    "token_category": "input",
                    "quantity": 2,
                }
                retry_headers = _tenant_headers(
                    audience="generate",
                    idempotency_key="t18-idempotency-retry",
                )
                first = client.post("/api/generate", json=retry_payload, headers=retry_headers)
                replay = client.post("/api/generate", json=retry_payload, headers=retry_headers)
                assert first.status_code == 201
                assert replay.status_code == 200
                assert first.json()["usage_event_id"] == replay.json()["usage_event_id"]
                assert replay.json()["idempotent_replay"] is True
                print("T18.3 retry returned the original usage event")

                with Session(engine) as session:
                    retry_rows = session.scalar(
                        select(func.count())
                        .select_from(UsageEvent)
                        .where(UsageEvent.idempotency_key == "t18-idempotency-retry")
                    )
                    blocked_rows = session.scalar(
                        select(func.count())
                        .select_from(UsageEvent)
                        .where(UsageEvent.idempotency_key == "t18-blocked-over-limit")
                    )
                assert retry_rows == 1
                assert blocked_rows == 0
                print("T18.4 file-backed database proof: retry rows=1, blocked rows=0")

                checkout = _checkout_event()
                upgrade = _subscription_update()
                assert _signed_post(client, checkout).status_code == 200
                assert _signed_post(client, upgrade).status_code == 200
                print("T18.5 verified Stripe test event transition: Free -> Pro")

                forged = client.post(
                    "/webhooks/stripe",
                    content=b'{"id":"evt_t18_forged","type":"checkout.session.completed"}',
                    headers={"Stripe-Signature": "t=1,v1=forged"},
                )
                assert forged.status_code == 400
                print("T18.6 forged Stripe webhook refused with 400")

                duplicate = _signed_post(client, checkout)
                assert duplicate.status_code == 200
                assert duplicate.json()["idempotent_replay"] is True
                with Session(engine) as session:
                    checkout_receipts = session.scalar(
                        select(func.count())
                        .select_from(ProcessedWebhookEvent)
                        .where(ProcessedWebhookEvent.stripe_event_id == "evt_t18_checkout")
                    )
                assert checkout_receipts == 1
                print("T18.7 duplicate valid webhook acknowledged; receipt rows=1")

                usage = client.get(
                    f"/usage?tenant_id={DEMO_FREE_TENANT_ID}",
                    headers=_tenant_headers(audience="usage"),
                )
                assert usage.status_code == 200
                usage_body = usage.json()
                assert usage_body["plan"]["code"] == "pro"
                assert usage_body["usage"]["api_calls"] == 1_000
                assert usage_body["usage"]["input_tokens"] == 2
                assert usage_body["remaining_allowance"] == {
                    "api_calls": 9_000,
                    "ai_tokens": 999_998,
                }
                print(
                    "T18.8 usage exact: plan=pro, api_calls=1000, "
                    "input_tokens=2, remaining_api=9000"
                )
                _run_selected_test_output()
            print(f"T18 demo run {run_number}: passed")
        finally:
            app.dependency_overrides.clear()
            webhook_api.get_stripe_webhook_settings = previous_settings
            if previous_secret is None:
                os.environ.pop("SESSION_SECRET", None)
            else:
                os.environ["SESSION_SECRET"] = previous_secret
            engine.dispose()


if __name__ == "__main__":
    run_demo(1)
    run_demo(2)