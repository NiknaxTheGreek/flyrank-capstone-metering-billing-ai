"""Tenant-scoped current-month usage summary endpoint."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.data.session import get_session
from app.services.usage_summary import UsageSummaryNotFoundError, get_usage_summary
from app.services.checkout_authorization import (
    TenantAuthorizationError,
    TenantAuthorizationNotConfiguredError,
    require_tenant_proof,
)

router = APIRouter()


class BillingPeriodResponse(BaseModel):
    start: str
    end: str


class PlanResponse(BaseModel):
    code: str
    status: str
    api_call_limit: int
    ai_token_limit: int


class UsageBreakdownResponse(BaseModel):
    api_calls: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    ai_tokens: int


class RemainingAllowanceResponse(BaseModel):
    api_calls: int
    ai_tokens: int


class UsageResponse(BaseModel):
    tenant_id: uuid.UUID
    billing_period: BillingPeriodResponse
    plan: PlanResponse
    usage: UsageBreakdownResponse
    remaining_allowance: RemainingAllowanceResponse
    estimated_ai_cost_cents: int


@router.get("/usage", response_model=UsageResponse)
def get_usage(
    tenant_id: Annotated[uuid.UUID, Query()],
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
) -> UsageResponse:
    """Return only the requested tenant's current verified monthly summary."""
    try:
        require_tenant_proof(tenant_id, tenant_proof, audience="usage")
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
        summary = get_usage_summary(session, tenant_id=tenant_id)
    except UsageSummaryNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown tenant.") from error
    return UsageResponse(
        tenant_id=summary.tenant_id,
        billing_period=BillingPeriodResponse(
            start=summary.billing_period.start.isoformat(),
            end=summary.billing_period.end.isoformat(),
        ),
        plan=PlanResponse(
            code=summary.plan.code,
            status=summary.subscription.status,
            api_call_limit=summary.plan.included_api_calls,
            ai_token_limit=summary.plan.included_ai_tokens,
        ),
        usage=UsageBreakdownResponse(
            api_calls=summary.usage.api_calls,
            input_tokens=summary.usage.input_tokens,
            cached_input_tokens=summary.usage.cached_input_tokens,
            output_tokens=summary.usage.output_tokens,
            reasoning_tokens=summary.usage.reasoning_tokens,
            ai_tokens=summary.usage.ai_tokens,
        ),
        remaining_allowance=RemainingAllowanceResponse(
            api_calls=summary.remaining_api_calls,
            ai_tokens=summary.remaining_ai_tokens,
        ),
        estimated_ai_cost_cents=summary.estimated_ai_cost_cents,
    )