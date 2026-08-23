"""Core metering behavior without quota, pricing, or provider logic."""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.data import usage_repository
from app.data.models import UsageEvent


class TenantNotFoundError(Exception):
    """Raised when a usage request is not scoped to a known tenant."""


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


def meter_usage(session: Session, command: MeterUsageCommand) -> MeterUsageResult:
    """Record one tenant-scoped usage event or return its prior durable record."""
    if usage_repository.get_tenant(session, command.tenant_id) is None:
        raise TenantNotFoundError

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