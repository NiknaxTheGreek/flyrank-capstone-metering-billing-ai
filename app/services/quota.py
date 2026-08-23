"""Quota evaluation for the current deterministic billing period."""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.data.models import Plan


@dataclass(frozen=True)
class BillingPeriod:
    """A UTC calendar month with an inclusive start and exclusive end."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class QuotaEvaluation:
    """The values used to make one quota decision."""

    usage_type: str
    limit: int
    current_usage: int
    attempted_quantity: int

    @property
    def projected_usage(self) -> int:
        """Return the usage total if this request is accepted."""
        return self.current_usage + self.attempted_quantity


class QuotaExceededError(Exception):
    """Raised when accepting a request would exceed its plan limit."""

    def __init__(self, evaluation: QuotaEvaluation) -> None:
        self.evaluation = evaluation
        super().__init__(
            f"{evaluation.usage_type} quota exceeded: "
            f"{evaluation.projected_usage} would exceed {evaluation.limit}."
        )


def current_utc_billing_period(as_of: datetime | None = None) -> BillingPeriod:
    """Return the UTC calendar month containing ``as_of``."""
    current_time = as_of or datetime.now(UTC)
    if current_time.tzinfo is None:
        raise ValueError("Billing-period timestamps must be timezone-aware.")

    current_time = current_time.astimezone(UTC)
    period_start = datetime(current_time.year, current_time.month, 1, tzinfo=UTC)
    if current_time.month == 12:
        period_end = datetime(current_time.year + 1, 1, 1, tzinfo=UTC)
    else:
        period_end = datetime(current_time.year, current_time.month + 1, 1, tzinfo=UTC)
    return BillingPeriod(start=period_start, end=period_end)


def plan_limit_for_usage_type(plan: Plan, usage_type: str) -> int:
    """Return the configured plan limit for one supported usage dimension."""
    if usage_type == "api_call":
        return plan.included_api_calls
    if usage_type == "ai_token":
        return plan.included_ai_tokens
    raise ValueError(f"Unsupported usage type: {usage_type}")


def enforce_quota(
    *,
    plan: Plan,
    usage_type: str,
    current_usage: int,
    attempted_quantity: int,
) -> QuotaEvaluation:
    """Allow requests through the exact plan limit and reject only excess."""
    evaluation = QuotaEvaluation(
        usage_type=usage_type,
        limit=plan_limit_for_usage_type(plan, usage_type),
        current_usage=current_usage,
        attempted_quantity=attempted_quantity,
    )
    if evaluation.projected_usage > evaluation.limit:
        raise QuotaExceededError(evaluation)
    return evaluation