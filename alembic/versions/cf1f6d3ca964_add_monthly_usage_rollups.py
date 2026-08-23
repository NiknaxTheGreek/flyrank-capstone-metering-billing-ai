"""add monthly usage rollups

Revision ID: cf1f6d3ca964
Revises: 79ec43ab98d2
Create Date: 2026-08-23 12:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "cf1f6d3ca964"
down_revision: Union[str, Sequence[str], None] = "79ec43ab98d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add token categories and idempotent monthly reconciliation storage."""
    op.add_column(
        "usage_events",
        sa.Column("token_category", sa.String(length=32), nullable=True),
    )
    op.execute(
        "UPDATE usage_events SET token_category = 'input' "
        "WHERE usage_type = 'ai_token'"
    )
    op.create_check_constraint(
        "ck_usage_events_token_category",
        "usage_events",
        "(usage_type = 'api_call' AND token_category IS NULL) OR "
        "(usage_type = 'ai_token' AND token_category IN "
        "('input', 'cached_input', 'output', 'reasoning'))",
    )
    op.create_table(
        "monthly_usage_rollups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("billing_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("billing_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("api_calls", sa.BigInteger(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reasoning_tokens", sa.BigInteger(), nullable=False),
        sa.Column("estimated_ai_cost_cents", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_monthly_usage_rollups_tenant_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "billing_period_start",
            name="uq_monthly_usage_rollups_tenant_period",
        ),
    )
    op.create_index(
        "ix_monthly_usage_rollups_tenant_period",
        "monthly_usage_rollups",
        ["tenant_id", "billing_period_start"],
        unique=False,
    )


def downgrade() -> None:
    """Remove monthly reconciliation storage and token-category metadata."""
    op.drop_index(
        "ix_monthly_usage_rollups_tenant_period",
        table_name="monthly_usage_rollups",
    )
    op.drop_table("monthly_usage_rollups")
    op.drop_constraint(
        "ck_usage_events_token_category",
        "usage_events",
        type_="check",
    )
    op.drop_column("usage_events", "token_category")