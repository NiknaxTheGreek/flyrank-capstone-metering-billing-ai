"""Tenant-scoped monthly usage summaries shared by the API and rollup job."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.data import usage_repository
from app.data.models import Plan, Subscription
from app.services.pricing import TokenUsage, price_gemini_25_flash_lite_standard
from app.services.quota import BillingPeriod, current_utc_billing_period


class UsageSummaryNotFoundError(Exception):
    """Raised when a requested tenant has no locally verified plan state."""


@dataclass(frozen=True)
class MonthlyUsage:
    """The raw, distinguishable monthly usage values for one tenant."""

    api_calls: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int

    @property
    def ai_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cached_input_tokens
            + self.output_tokens
            + self.reasoning_tokens
        )


@dataclass(frozen=True)
class UsageSummary:
    """A deterministic current-month view of one tenant's verified plan."""

    tenant_id: uuid.UUID
    subscription: Subscription
    plan: Plan
    billing_period: BillingPeriod
    usage: MonthlyUsage
    estimated_ai_cost_cents: int

    @property
    def remaining_api_calls(self) -> int:
        return max(self.plan.included_api_calls - self.usage.api_calls, 0)

    @property
    def remaining_ai_tokens(self) -> int:
        return max(self.plan.included_ai_tokens - self.usage.ai_tokens, 0)


def get_usage_summary(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    as_of: datetime | None = None,
) -> UsageSummary:
    """Build a tenant-isolated current UTC-month summary from source events."""
    if usage_repository.get_tenant(session, tenant_id) is None:
        raise UsageSummaryNotFoundError
    subscription = usage_repository.get_current_subscription_for_tenant(session, tenant_id)
    if subscription is None:
        raise UsageSummaryNotFoundError
    plan = session.get(Plan, subscription.plan_id)
    if plan is None:
        raise UsageSummaryNotFoundError

    billing_period = current_utc_billing_period(as_of)
    breakdown = usage_repository.get_usage_breakdown_for_period(
        session,
        tenant_id=tenant_id,
        period_start=billing_period.start,
        period_end=billing_period.end,
    )
    usage = MonthlyUsage(
        api_calls=breakdown.get(("api_call", None), 0),
        # Legacy AI-token events predate categories and are conservatively
        # retained as input tokens for the fixed T10 calculator.
        input_tokens=breakdown.get(("ai_token", None), 0)
        + breakdown.get(("ai_token", "input"), 0),
        cached_input_tokens=breakdown.get(("ai_token", "cached_input"), 0),
        output_tokens=breakdown.get(("ai_token", "output"), 0),
        reasoning_tokens=breakdown.get(("ai_token", "reasoning"), 0),
    )
    price = price_gemini_25_flash_lite_standard(
        TokenUsage(
            api_calls=usage.api_calls,
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
        )
    )
    return UsageSummary(
        tenant_id=tenant_id,
        subscription=subscription,
        plan=plan,
        billing_period=billing_period,
        usage=usage,
        estimated_ai_cost_cents=price.total_cents,
    )