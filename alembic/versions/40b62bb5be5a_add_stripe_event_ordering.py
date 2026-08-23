"""add Stripe event ordering to subscriptions

Revision ID: 40b62bb5be5a
Revises: dd3399d4697c
Create Date: 2026-08-23 11:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "40b62bb5be5a"
down_revision: Union[str, Sequence[str], None] = "dd3399d4697c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store the most recent Stripe event order applied to a subscription."""
    op.add_column(
        "subscriptions",
        sa.Column("stripe_last_event_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("stripe_last_event_type", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Remove Stripe event ordering state."""
    op.drop_column("subscriptions", "stripe_last_event_type")
    op.drop_column("subscriptions", "stripe_last_event_created_at")