"""Core metering behavior without quota, pricing, or provider logic."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.data import usage_repository
from app.data.models import UsageEvent
from app.services.quota import current_utc_billing_period, enforce_quota


class TenantNotFoundError(Exception):
    """Raised when a usage request is not scoped to a known tenant."""


class SubscriptionNotEligibleError(Exception):
    """Raised when a tenant has no active plan that can govern usage."""


@dataclass(frozen=True)
class MeterUsageCommand:
    """Validated values needed to record one simulated usage event."""

    tenant_id: uuid.UUID
    usage_type: str
    quantity: int
    idempotency_key: str


@dataclass(frozen=True)
class MeterUsageResult:
    """The durable event and whether it came from a retry."""

    usage_event: UsageEvent
    idempotent_replay: bool


def meter_usage(
    session: Session,
    command: MeterUsageCommand,
    *,
    now: datetime | None = None,
) -> MeterUsageResult:
    """Record one tenant-scoped usage event or return its prior durable record."""
    if usage_repository.get_tenant(session, command.tenant_id) is None:
        raise TenantNotFoundError

    existing_event = usage_repository.get_usage_event_by_idempotency_key(
        session,
        command.tenant_id,
        command.idempotency_key,
    )
    if existing_event is not None:
        return MeterUsageResult(
            usage_event=existing_event,
            idempotent_replay=True,
        )

    plan = usage_repository.get_active_plan_for_tenant(session, command.tenant_id)
    if plan is None:
        raise SubscriptionNotEligibleError

    billing_period = current_utc_billing_period(now)
    current_usage = usage_repository.get_usage_total_for_period(
        session,
        tenant_id=command.tenant_id,
        usage_type=command.usage_type,
        period_start=billing_period.start,
        period_end=billing_period.end,
    )
    enforce_quota(
        plan=plan,
        usage_type=command.usage_type,
        current_usage=current_usage,
        attempted_quantity=command.quantity,
    )

    usage_event, idempotent_replay = usage_repository.create_or_get_usage_event(
        session,
        tenant_id=command.tenant_id,
        usage_type=command.usage_type,
        quantity=command.quantity,
        idempotency_key=command.idempotency_key,
    )
    return MeterUsageResult(
        usage_event=usage_event,
        idempotent_replay=idempotent_replay,
    )