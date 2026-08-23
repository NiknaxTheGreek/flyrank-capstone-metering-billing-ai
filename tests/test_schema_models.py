from sqlalchemy import BigInteger, UniqueConstraint

from app.data.database import metadata


def test_usage_events_have_tenant_scoped_idempotency_constraint() -> None:
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in metadata.tables["usage_events"].constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert constraints["uq_usage_events_tenant_idempotency_key"] == (
        "tenant_id",
        "idempotency_key",
    )


def test_processed_webhook_events_have_global_stripe_event_deduplication() -> None:
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in metadata.tables["processed_webhook_events"].constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert constraints["uq_processed_webhook_events_stripe_event_id"] == (
        "stripe_event_id",
    )


def test_required_tenant_foreign_keys_are_declared() -> None:
    expected_foreign_keys = {
        "subscriptions": {"tenant_id", "plan_id"},
        "usage_events": {"tenant_id"},
        "processed_webhook_events": {"tenant_id"},
    }

    for table_name, expected_columns in expected_foreign_keys.items():
        foreign_key_columns = {
            foreign_key.parent.name for foreign_key in metadata.tables[table_name].foreign_keys
        }
        assert foreign_key_columns == expected_columns


def test_integer_safe_money_and_usage_quantities_are_used() -> None:
    assert isinstance(metadata.tables["plans"].c.monthly_price_cents.type, BigInteger)
    assert isinstance(metadata.tables["usage_events"].c.quantity.type, BigInteger)


def test_required_lookup_indexes_are_declared() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for table in metadata.tables.values()
        for index in table.indexes
    }

    assert indexes["ix_subscriptions_tenant_id"] == ("tenant_id",)
    assert indexes["ix_usage_events_tenant_occurred_at"] == (
        "tenant_id",
        "occurred_at",
    )
    assert indexes["ix_processed_webhook_events_tenant_id"] == ("tenant_id",)