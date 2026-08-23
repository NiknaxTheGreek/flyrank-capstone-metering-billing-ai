"""Simulated generation endpoint that records one usage event per request key."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.data.session import get_session
from app.services.metering import (
    MeterUsageCommand,
    SubscriptionNotEligibleError,
    TenantNotFoundError,
    meter_usage,
)
from app.services.checkout_authorization import (
    TenantAuthorizationError,
    TenantAuthorizationNotConfiguredError,
    require_tenant_proof,
)
from app.services.quota import QuotaExceededError

router = APIRouter(prefix="/api")


class GenerateRequest(BaseModel):
    """Validated simulated usage for the dummy generation endpoint."""

    tenant_id: uuid.UUID
    usage_type: Literal["api_call", "ai_token"]
    quantity: Annotated[int, Field(gt=0)]
    token_category: Literal["input", "cached_input", "output", "reasoning"] | None = None

    @model_validator(mode="after")
    def validate_usage_combination(self) -> "GenerateRequest":
        """Reject combinations that cannot be stored or priced safely."""
        if self.usage_type == "ai_token" and self.token_category is None:
            raise ValueError("AI-token usage requires a token_category.")
        if self.usage_type == "api_call" and self.token_category is not None:
            raise ValueError("API-call usage cannot include a token_category.")
        return self


class GenerateResponse(BaseModel):
    """The simulated response and its durable metering result."""

    generated_text: str
    usage_event_id: uuid.UUID
    usage_type: Literal["api_call", "ai_token"]
    quantity: int
    idempotent_replay: bool


@router.post(
    "/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "description": "A retry returned the original metered event."
        }
    },
)
def generate(
    request: GenerateRequest,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            description=(
                "Reuse this key to retry safely; a retry returns the original "
                "usage event with HTTP 200 and idempotent_replay=true."
            ),
        ),
    ],
    session: Annotated[Session, Depends(get_session)],
    tenant_proof: Annotated[
        str | None,
        Header(
            alias="X-Tenant-Proof",
            description=(
                "Endpoint-bound tenant proof issued by the trusted authentication "
                "or gateway layer."
            ),
        ),
    ] = None,
) -> JSONResponse:
    """Simulate generation and record at most one durable usage event per key."""
    try:
        require_tenant_proof(request.tenant_id, tenant_proof, audience="generate")
    except TenantAuthorizationNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "tenant_authorization_not_configured",
                "message": "Tenant request authorization is not configured.",
            },
        ) from error
    except TenantAuthorizationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "tenant_not_authorized",
                "message": "The request is not authorized for the stated tenant.",
            },
        ) from error
    try:
        result = meter_usage(
            session,
            MeterUsageCommand(
                tenant_id=request.tenant_id,
                usage_type=request.usage_type,
                quantity=request.quantity,
                idempotency_key=idempotency_key,
                token_category=request.token_category,
            ),
        )
    except TenantNotFoundError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown tenant.") from error
    except SubscriptionNotEligibleError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "subscription_not_eligible",
                "message": "An active subscription plan is required to record usage.",
            },
        ) from error
    except QuotaExceededError as error:
        session.rollback()
        evaluation = error.evaluation
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "quota_exhausted",
                "message": (
                    f"The {evaluation.usage_type} quota is exhausted for the "
                    "current UTC calendar month."
                ),
                "usage_type": evaluation.usage_type,
                "limit": evaluation.limit,
                "current_usage": evaluation.current_usage,
                "attempted_quantity": evaluation.attempted_quantity,
            },
        ) from error

    response = GenerateResponse(
        generated_text="simulated-generation",
        usage_event_id=result.usage_event.id,
        usage_type=result.usage_event.usage_type,
        quantity=result.usage_event.quantity,
        idempotent_replay=result.idempotent_replay,
    )
    response_status = (
        status.HTTP_200_OK if result.idempotent_replay else status.HTTP_201_CREATED
    )
    return JSONResponse(
        status_code=response_status,
        content=response.model_dump(mode="json"),
    )