"""Stripe Checkout orchestration without local subscription mutation."""

import uuid
from dataclasses import dataclass

from stripe import StripeClient, StripeError
from sqlalchemy.orm import Session

from app.config import StripeTestSettings, get_stripe_test_settings
from app.data import usage_repository
from app.integrations.stripe.client import get_stripe_test_client


class CheckoutTenantNotFoundError(Exception):
    """Raised when Checkout is requested for an unknown tenant."""


class CheckoutNotEligibleError(Exception):
    """Raised when a tenant is not on an active Free subscription."""


class StripeCheckoutUnavailableError(Exception):
    """Raised when Stripe cannot create the requested hosted Checkout Session."""


@dataclass(frozen=True)
class CheckoutSessionResult:
    """Non-sensitive hosted Checkout details returned to the API layer."""

    session_id: str
    url: str


def create_pro_checkout_session(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    settings: StripeTestSettings | None = None,
    stripe_client: StripeClient | None = None,
) -> CheckoutSessionResult:
    """Create a hosted Pro subscription checkout for an active Free tenant.

    Local subscription changes are intentionally deferred to a later verified
    webhook milestone. This function only reads tenant state and creates the
    remote Checkout Session.
    """
    if usage_repository.get_tenant(session, tenant_id) is None:
        raise CheckoutTenantNotFoundError

    active_plan = usage_repository.get_active_plan_for_tenant(session, tenant_id)
    if active_plan is None or active_plan.code != "free":
        raise CheckoutNotEligibleError

    resolved_settings = settings or get_stripe_test_settings()
    resolved_client = stripe_client or get_stripe_test_client(resolved_settings)
    tenant_reference = str(tenant_id)
    try:
        checkout_session = resolved_client.v1.checkout.sessions.create(
            params={
                "mode": "subscription",
                "line_items": [
                    {
                        "price": resolved_settings.pro_price_id,
                        "quantity": 1,
                    }
                ],
                "success_url": resolved_settings.success_url,
                "cancel_url": resolved_settings.cancel_url,
                "client_reference_id": tenant_reference,
                "metadata": {"tenant_id": tenant_reference},
            }
        )
    except StripeError as error:
        raise StripeCheckoutUnavailableError from error

    if not checkout_session.id or not checkout_session.url:
        raise StripeCheckoutUnavailableError(
            "Stripe returned a Checkout Session without its hosted URL."
        )
    return CheckoutSessionResult(
        session_id=checkout_session.id,
        url=checkout_session.url,
    )