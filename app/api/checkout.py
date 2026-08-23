"""Thin HTTP API for creating hosted Stripe Checkout Sessions."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import StripeConfigurationError
from app.data.session import get_session
from app.services.checkout import (
    CheckoutNotEligibleError,
    CheckoutTenantNotFoundError,
    StripeCheckoutUnavailableError,
    create_pro_checkout_session,
)
from app.services.checkout_authorization import (
    CheckoutAuthorizationError,
    CheckoutAuthorizationNotConfiguredError,
    require_checkout_tenant_proof,
)

router = APIRouter(prefix="/api")


class CheckoutRequest(BaseModel):
    """The tenant that will be associated with a hosted Checkout Session."""

    tenant_id: uuid.UUID


class CheckoutResponse(BaseModel):
    """Non-sensitive details needed to redirect a tenant to Stripe Checkout."""

    checkout_session_id: str
    checkout_url: str


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_checkout(
    request: CheckoutRequest,
    session: Annotated[Session, Depends(get_session)],
    tenant_proof: Annotated[
        str | None,
        Header(
            alias="X-Checkout-Tenant-Proof",
            description=(
                "Tenant-bound proof issued by the trusted authentication or gateway layer."
            ),
        ),
    ] = None,
) -> CheckoutResponse:
    """Delegate Checkout creation and map service errors to HTTP responses."""
    try:
        require_checkout_tenant_proof(request.tenant_id, tenant_proof)
    except CheckoutAuthorizationNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "checkout_authorization_not_configured",
                "message": "Tenant checkout authorization is not configured.",
            },
        ) from error
    except CheckoutAuthorizationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "checkout_tenant_not_authorized",
                "message": "The request is not authorized for the stated tenant.",
            },
        ) from error

    try:
        result = create_pro_checkout_session(session, tenant_id=request.tenant_id)
    except CheckoutTenantNotFoundError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "tenant_not_found",
                "message": "The requested tenant does not exist.",
            },
        ) from error
    except CheckoutNotEligibleError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "checkout_not_eligible",
                "message": "An active Free subscription is required to start Pro checkout.",
            },
        ) from error
    except StripeConfigurationError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "stripe_not_configured",
                "message": "Stripe test-mode checkout is not configured.",
            },
        ) from error
    except StripeCheckoutUnavailableError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "stripe_checkout_unavailable",
                "message": "Stripe could not create a hosted Checkout Session.",
            },
        ) from error

    return CheckoutResponse(
        checkout_session_id=result.session_id,
        checkout_url=result.url,
    )