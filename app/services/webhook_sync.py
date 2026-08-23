"""Transactional synchronization of signature-verified Stripe event payloads."""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data.models import Plan, ProcessedWebhookEvent, Subscription, Tenant

SUPPORTED_STRIPE_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)


class WebhookEventProcessingError(ValueError):
    """Raised when a verified event cannot be safely applied locally."""


class WebhookAuthoritativeStateUnavailable(WebhookEventProcessingError):
    """Raised when an ambiguous event cannot be reconciled with Stripe."""


@dataclass(frozen=True)
class WebhookProcessResult:
    """The durable outcome of one verified Stripe event delivery."""

    handled: bool
    idempotent_replay: bool


@dataclass(frozen=True)
class _PreparedEvent:
    """A fully resolved state operation that has not mutated the database yet."""

    tenant_id: uuid.UUID
    subscription: Subscription
    apply: Callable[[], None]
    replaces_stripe_subscription_link: bool = False


def process_verified_stripe_event(
    session: Session,
    *,
    event: Mapping[str, Any],
    pro_price_id: str,
    subscription_resolver: Callable[[str], Mapping[str, Any]] | None = None,
) -> WebhookProcessResult:
    """Atomically claim and apply one already signature-verified Stripe event.

    A duplicate is successful by design: the database's globally unique Stripe
    event identifier is the final authority that prevents a second business
    effect, including when deliveries race.
    """
    event_id = _required_text(event, "id")
    event_type = _required_text(event, "type")
    if event_type not in SUPPORTED_STRIPE_EVENT_TYPES:
        return WebhookProcessResult(handled=False, idempotent_replay=False)

    event_object = _event_object(event)
    event_created_at = _stripe_event_created_at(event)
    existing = session.scalar(
        select(ProcessedWebhookEvent).where(
            ProcessedWebhookEvent.stripe_event_id == event_id
        )
    )
    if existing is not None:
        return WebhookProcessResult(handled=True, idempotent_replay=True)
    # The receipt lookup starts SQLAlchemy's implicit read transaction. Close it
    # before the transaction that locks and mutates a subscription.
    session.rollback()
    try:
        with session.begin():
            prepared = _prepare_event(
                session,
                event_type=event_type,
                event_object=event_object,
                pro_price_id=pro_price_id,
                event_created_at=event_created_at,
            )
            if prepared.replaces_stripe_subscription_link:
                pass
            elif _requires_authoritative_reconciliation(
                prepared.subscription, event_created_at
            ) or _has_ambiguous_stripe_event_order(
                prepared.subscription, event_created_at
            ):
                if subscription_resolver is None:
                    raise WebhookAuthoritativeStateUnavailable(
                        "A same-second Stripe event requires authoritative reconciliation."
                    )
                stripe_subscription_id = prepared.subscription.stripe_subscription_id
                if not stripe_subscription_id:
                    raise WebhookEventProcessingError(
                        "An ambiguous event has no local Stripe subscription mapping."
                    )
                prepared = _prepare_subscription_update(
                    session,
                    subscription_resolver(stripe_subscription_id),
                    pro_price_id,
                    event_type=event_type,
                    event_created_at=event_created_at,
                    authoritative_reconciled_at=datetime.now(UTC),
                )
            elif _is_older_stripe_event(prepared.subscription, event_created_at):
                prepared = _without_mutation(prepared)
            session.add(
                ProcessedWebhookEvent(
                    tenant_id=prepared.tenant_id,
                    stripe_event_id=event_id,
                    event_type=event_type,
                )
            )
            # Claim the receipt before mutating the subscription. This flush
            # makes the database uniqueness constraint the concurrency backstop.
            session.flush()
            prepared.apply()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(ProcessedWebhookEvent).where(
                ProcessedWebhookEvent.stripe_event_id == event_id
            )
        )
        if existing is None:
            raise
        return WebhookProcessResult(handled=True, idempotent_replay=True)

    return WebhookProcessResult(handled=True, idempotent_replay=False)


def _prepare_event(
    session: Session,
    *,
    event_type: str,
    event_object: Mapping[str, Any],
    pro_price_id: str,
    event_created_at: datetime,
) -> _PreparedEvent:
    if event_type == "checkout.session.completed":
        return _prepare_checkout_completion(
            session,
            event_object,
            event_type=event_type,
            event_created_at=event_created_at,
        )
    if event_type == "customer.subscription.updated":
        return _prepare_subscription_update(
            session,
            event_object,
            pro_price_id,
            event_type=event_type,
            event_created_at=event_created_at,
        )
    return _prepare_subscription_deletion(
        session,
        event_object,
        event_type=event_type,
        event_created_at=event_created_at,
    )


def _prepare_checkout_completion(
    session: Session,
    event_object: Mapping[str, Any],
    *,
    event_type: str,
    event_created_at: datetime,
) -> _PreparedEvent:
    """Resolve a Checkout tenant only from verified Stripe-owned references."""
    tenant_id = _checkout_tenant_id(event_object)
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise WebhookEventProcessingError("Checkout event references an unknown tenant.")

    customer_id = _required_text(event_object, "customer")
    subscription_id = _required_text(event_object, "subscription")
    if _required_text(event_object, "mode") != "subscription":
        raise WebhookEventProcessingError(
            "Checkout completion is not a subscription-mode session."
        )
    conflicting_subscription = session.scalar(
        select(Subscription).where(
            Subscription.stripe_subscription_id == subscription_id,
            Subscription.tenant_id != tenant_id,
        )
    )
    if conflicting_subscription is not None:
        raise WebhookEventProcessingError(
            "Stripe subscription identifier is already mapped to another tenant."
        )

    subscription = _latest_subscription_for_tenant(session, tenant_id)
    replaces_stripe_subscription_link = (
        subscription.stripe_subscription_id != subscription_id
    )

    def apply() -> None:
        subscription.stripe_customer_id = customer_id
        subscription.stripe_subscription_id = subscription_id
        if replaces_stripe_subscription_link:
            subscription.stripe_last_event_created_at = None
            subscription.stripe_last_event_type = None
            subscription.stripe_authoritative_reconciled_at = None
        else:
            _record_stripe_event_order(subscription, event_created_at, event_type)

    return _PreparedEvent(
        tenant_id=tenant_id,
        subscription=subscription,
        apply=apply,
        replaces_stripe_subscription_link=replaces_stripe_subscription_link,
    )


def _prepare_subscription_update(
    session: Session,
    event_object: Mapping[str, Any],
    pro_price_id: str,
    *,
    event_type: str,
    event_created_at: datetime,
    authoritative_reconciled_at: datetime | None = None,
) -> _PreparedEvent:
    """Synchronize only the local record already linked by verified Checkout."""
    subscription_id = _required_text(event_object, "id")
    subscription = _subscription_by_stripe_id(session, subscription_id)
    customer_id = _required_text(event_object, "customer")
    stripe_status = _required_text(event_object, "status")
    has_configured_pro_price = _contains_price(event_object, pro_price_id)
    current_period_start = _stripe_timestamp(event_object.get("current_period_start"))
    current_period_end = _stripe_timestamp(event_object.get("current_period_end"))
    pro_plan = _plan_by_code(session, "pro")
    free_plan = _plan_by_code(session, "free")

    def apply() -> None:
        subscription.stripe_customer_id = customer_id
        subscription.status = stripe_status
        subscription.current_period_start = current_period_start
        subscription.current_period_end = current_period_end
        subscription.plan_id = (
            pro_plan.id
            if stripe_status == "active" and has_configured_pro_price
            else free_plan.id
        )
        _record_stripe_event_order(
            subscription,
            event_created_at,
            event_type,
            authoritative_reconciled_at=authoritative_reconciled_at,
        )

    return _PreparedEvent(
        tenant_id=subscription.tenant_id,
        subscription=subscription,
        apply=apply,
    )


def _prepare_subscription_deletion(
    session: Session,
    event_object: Mapping[str, Any],
    *,
    event_type: str,
    event_created_at: datetime,
) -> _PreparedEvent:
    """Remove entitlement from the one local subscription linked to Stripe."""
    subscription_id = _required_text(event_object, "id")
    subscription = _subscription_by_stripe_id(session, subscription_id)
    customer_id = _required_text(event_object, "customer")
    stripe_status = _required_text(event_object, "status")
    current_period_start = _stripe_timestamp(event_object.get("current_period_start"))
    current_period_end = _stripe_timestamp(event_object.get("current_period_end"))
    free_plan = _plan_by_code(session, "free")

    def apply() -> None:
        subscription.plan_id = free_plan.id
        subscription.status = stripe_status
        subscription.stripe_customer_id = customer_id
        subscription.current_period_start = current_period_start
        subscription.current_period_end = current_period_end
        _record_stripe_event_order(subscription, event_created_at, event_type)

    return _PreparedEvent(
        tenant_id=subscription.tenant_id,
        subscription=subscription,
        apply=apply,
    )


def _checkout_tenant_id(event_object: Mapping[str, Any]) -> uuid.UUID:
    metadata = event_object.get("metadata")
    metadata_tenant_id = (
        metadata.get("tenant_id") if isinstance(metadata, Mapping) else None
    )
    client_reference_id = event_object.get("client_reference_id")
    references = [
        value
        for value in (metadata_tenant_id, client_reference_id)
        if isinstance(value, str) and value
    ]
    if not references:
        raise WebhookEventProcessingError(
            "Checkout event does not include a tenant metadata or client reference."
        )
    try:
        resolved = uuid.UUID(references[0])
        if any(uuid.UUID(value) != resolved for value in references[1:]):
            raise WebhookEventProcessingError(
                "Checkout metadata and client reference identify different tenants."
            )
    except ValueError as error:
        raise WebhookEventProcessingError(
            "Checkout tenant reference is not a valid UUID."
        ) from error
    return resolved


def _latest_subscription_for_tenant(session: Session, tenant_id: uuid.UUID) -> Subscription:
    subscription = session.scalar(
        select(Subscription)
        .where(Subscription.tenant_id == tenant_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if subscription is None:
        raise WebhookEventProcessingError("Tenant has no local subscription to update.")
    return subscription


def _subscription_by_stripe_id(session: Session, subscription_id: str) -> Subscription:
    subscription = session.scalar(
        select(Subscription)
        .where(Subscription.stripe_subscription_id == subscription_id)
        .with_for_update()
    )
    if subscription is None:
        raise WebhookEventProcessingError(
            "Stripe subscription is not mapped by a verified Checkout completion."
        )
    return subscription


def _plan_by_code(session: Session, code: str) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        raise WebhookEventProcessingError(f"Required {code} plan is not configured.")
    return plan


def _contains_price(event_object: Mapping[str, Any], pro_price_id: str) -> bool:
    items = event_object.get("items")
    item_data = items.get("data") if isinstance(items, Mapping) else None
    if not isinstance(item_data, list):
        return False
    for item in item_data:
        if not isinstance(item, Mapping):
            continue
        price = item.get("price")
        if isinstance(price, Mapping) and price.get("id") == pro_price_id:
            return True
    return False


def _stripe_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WebhookEventProcessingError(
            "Stripe subscription period timestamps must be non-negative integers."
        )
    return datetime.fromtimestamp(value, UTC)


def _stripe_event_created_at(event: Mapping[str, Any]) -> datetime:
    event_created_at = _stripe_timestamp(event.get("created"))
    if event_created_at is None:
        raise WebhookEventProcessingError(
            "Stripe event must include a creation timestamp for safe ordering."
        )
    return event_created_at


def _is_older_stripe_event(
    subscription: Subscription, event_created_at: datetime
) -> bool:
    """Return whether an event predates the already applied Stripe state."""
    previous_created_at = subscription.stripe_last_event_created_at
    if previous_created_at is None:
        return False
    if previous_created_at.tzinfo is None:
        previous_created_at = previous_created_at.replace(tzinfo=UTC)
    return event_created_at < previous_created_at


def _has_ambiguous_stripe_event_order(
    subscription: Subscription, event_created_at: datetime
) -> bool:
    """Same-second distinct events require Stripe's current subscription state."""
    previous_created_at = subscription.stripe_last_event_created_at
    if previous_created_at is None:
        return False
    if previous_created_at.tzinfo is None:
        previous_created_at = previous_created_at.replace(tzinfo=UTC)
    return event_created_at == previous_created_at


def _record_stripe_event_order(
    subscription: Subscription,
    event_created_at: datetime,
    event_type: str,
    *,
    authoritative_reconciled_at: datetime | None = None,
) -> None:
    subscription.stripe_last_event_created_at = event_created_at
    subscription.stripe_last_event_type = event_type
    subscription.stripe_authoritative_reconciled_at = authoritative_reconciled_at


def _requires_authoritative_reconciliation(
    subscription: Subscription, event_created_at: datetime
) -> bool:
    """Re-fetch state for deliveries potentially subsumed by a prior fetch."""
    reconciled_at = subscription.stripe_authoritative_reconciled_at
    if reconciled_at is None:
        return False
    if reconciled_at.tzinfo is None:
        reconciled_at = reconciled_at.replace(tzinfo=UTC)
    return event_created_at <= reconciled_at


def _without_mutation(prepared: _PreparedEvent) -> _PreparedEvent:
    """Keep a durable receipt for a stale delivery without changing entitlement."""
    return _PreparedEvent(
        tenant_id=prepared.tenant_id,
        subscription=prepared.subscription,
        apply=lambda: None,
    )


def _event_object(event: Mapping[str, Any]) -> Mapping[str, Any]:
    data = event.get("data")
    event_object = data.get("object") if isinstance(data, Mapping) else None
    if not isinstance(event_object, Mapping):
        raise WebhookEventProcessingError("Stripe event does not contain an object payload.")
    return event_object


def _required_text(source: Mapping[str, Any], field_name: str) -> str:
    value = source.get(field_name)
    if not isinstance(value, str) or not value:
        raise WebhookEventProcessingError(
            f"Stripe event field '{field_name}' must be a non-empty string."
        )
    return value