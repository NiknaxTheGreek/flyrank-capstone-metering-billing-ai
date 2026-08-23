"""add Stripe reconciliation watermark

Revision ID: 79ec43ab98d2
Revises: 40b62bb5be5a
Create Date: 2026-08-23 11:25:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "79ec43ab98d2"
down_revision: Union[str, Sequence[str], None] = "40b62bb5be5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store when current Stripe state was authoritatively reconciled."""
    op.add_column(
        "subscriptions",
        sa.Column("stripe_authoritative_reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove the Stripe reconciliation watermark."""
    op.drop_column("subscriptions", "stripe_authoritative_reconciled_at")