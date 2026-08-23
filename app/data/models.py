"""SQLAlchemy persistence models for the capstone's billing domain."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all persistence models."""


class Plan(Base):
    """A service offering with integer-safe limits and monthly pricing."""

    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("code", name="uq_plans_code"),
        CheckConstraint(
            "monthly_price_cents >= 0",
            name="ck_plans_monthly_price_cents_nonnegative",
        ),
        CheckConstraint(
            "included_api_calls >= 0",
            name="ck_plans_included_api_calls_nonnegative",
        ),
        CheckConstraint(
            "included_ai_tokens >= 0",
            name="ck_plans_included_ai_tokens_nonnegative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    monthly_price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    included_api_calls: Mapped[int] = mapped_column(BigInteger, nullable=False)
    included_ai_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Tenant(Base):
    """A customer organization that isolates subscriptions and usage."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Subscription(Base):
    """The persisted link between a tenant and its current plan."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "stripe_subscription_id",
            name="uq_subscriptions_stripe_subscription_id",
        ),
        Index("ix_subscriptions_tenant_id", "tenant_id"),
        Index("ix_subscriptions_plan_id", "plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", name="fk_subscriptions_tenant_id"),
        nullable=False,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", name="fk_subscriptions_plan_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stripe_last_event_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    stripe_last_event_type: Mapped[str | None] = mapped_column(String(255))
    stripe_authoritative_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UsageEvent(Base):
    """An immutable, tenant-scoped billable usage record."""

    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_usage_events_tenant_idempotency_key",
        ),
        CheckConstraint("quantity > 0", name="ck_usage_events_quantity_positive"),
        CheckConstraint(
            "usage_type IN ('api_call', 'ai_token')",
            name="ck_usage_events_usage_type",
        ),
        CheckConstraint(
            "(usage_type = 'api_call' AND token_category IS NULL) OR "
            "(usage_type = 'ai_token' AND token_category IN "
            "('input', 'cached_input', 'output', 'reasoning'))",
            name="ck_usage_events_token_category",
        ),
        Index("ix_usage_events_tenant_occurred_at", "tenant_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", name="fk_usage_events_tenant_id"),
        nullable=False,
    )
    usage_type: Mapped[str] = mapped_column(String(32), nullable=False)
    token_category: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MonthlyUsageRollup(Base):
    """A reconciled tenant/month summary maintained by the standalone job."""

    __tablename__ = "monthly_usage_rollups"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "billing_period_start",
            name="uq_monthly_usage_rollups_tenant_period",
        ),
        Index(
            "ix_monthly_usage_rollups_tenant_period",
            "tenant_id",
            "billing_period_start",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", name="fk_monthly_usage_rollups_tenant_id"),
        nullable=False,
    )
    billing_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    billing_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    api_calls: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_ai_cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProcessedWebhookEvent(Base):
    """A tenant-scoped Stripe event receipt retained for deduplication."""

    __tablename__ = "processed_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "stripe_event_id",
            name="uq_processed_webhook_events_stripe_event_id",
        ),
        Index("ix_processed_webhook_events_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", name="fk_processed_webhook_events_tenant_id"),
        nullable=False,
    )
    stripe_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )