"""Stripe's raw-body webhook delivery boundary."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from stripe import SignatureVerificationError, StripeError, Webhook

from app.config import StripeConfigurationError, get_stripe_webhook_settings
from app.data.session import get_session
from app.integrations.stripe.client import get_stripe_test_client
from app.services.webhook_sync import (
    WebhookAuthoritativeStateUnavailable,
    WebhookEventProcessingError,
    process_verified_stripe_event,
)

router = APIRouter()


@router.post("/webhooks/stripe", status_code=status.HTTP_200_OK)
async def receive_stripe_webhook(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, bool]:
    """Verify Stripe's signed raw bytes before beginning any state synchronization."""
    signature = request.headers.get("Stripe-Signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_stripe_signature"},
        )

    try:
        settings = get_stripe_webhook_settings()
    except StripeConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "stripe_webhook_not_configured"},
        ) from error

    raw_body = await request.body()
    try:
        event = Webhook.construct_event(raw_body, signature, settings.signing_secret)
    except (SignatureVerificationError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_stripe_signature"},
        ) from error

    try:
        result = process_verified_stripe_event(
            session,
            event=event.to_dict(),
            pro_price_id=settings.pro_price_id,
            subscription_resolver=_retrieve_authoritative_subscription,
        )
    except WebhookAuthoritativeStateUnavailable as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "stripe_authoritative_state_unavailable"},
        ) from error
    except WebhookEventProcessingError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "stripe_event_not_processable"},
        ) from error

    return {
        "received": True,
        "handled": result.handled,
        "idempotent_replay": result.idempotent_replay,
    }


def _retrieve_authoritative_subscription(subscription_id: str) -> dict[str, object]:
    """Retrieve current Stripe state only when event timestamp ordering is ambiguous."""
    try:
        subscription = get_stripe_test_client().v1.subscriptions.retrieve(
            subscription_id
        )
    except (StripeConfigurationError, StripeError) as error:
        raise WebhookAuthoritativeStateUnavailable(
            "Stripe could not provide authoritative subscription state."
        ) from error
    return subscription.to_dict()