"""Persistence operations for tenant-scoped usage events."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data.models import Tenant, UsageEvent


def get_tenant(session: Session, tenant_id: uuid.UUID) -> Tenant | None:
    """Return a tenant by identifier."""
    return session.get(Tenant, tenant_id)


def get_usage_event_by_idempotency_key(
    session: Session, tenant_id: uuid.UUID, idempotency_key: str
) -> UsageEvent | None:
    """Return the event already recorded for a tenant request key."""
    return session.scalar(
        select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.idempotency_key == idempotency_key,
        )
    )


def create_or_get_usage_event(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    usage_type: str,
    quantity: int,
    idempotency_key: str,
) -> tuple[UsageEvent, bool]:
    """Persist one event or return the existing event for a repeated request."""
    existing_event = get_usage_event_by_idempotency_key(
        session, tenant_id, idempotency_key
    )
    if existing_event is not None:
        return existing_event, True

    usage_event = UsageEvent(
        tenant_id=tenant_id,
        usage_type=usage_type,
        quantity=quantity,
        idempotency_key=idempotency_key,
    )
    session.add(usage_event)

    try:
        session.commit()
    except IntegrityError:
        # Concurrent requests can both miss the initial lookup. The database
        # uniqueness constraint is the final authority in that race.
        session.rollback()
        existing_event = get_usage_event_by_idempotency_key(
            session, tenant_id, idempotency_key
        )
        if existing_event is None:
            raise
        return existing_event, True

    return usage_event, False