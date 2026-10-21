"""Add simple customer support tickets.

Revision ID: 0008_support_tickets
Revises: 0007_deliveries
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_support_tickets"
down_revision: Union[str, None] = "0007_deliveries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "support_tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("staff_note", sa.String(length=500), nullable=True),
        sa.Column("handled_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'resolved')", name="ck_support_tickets_status_valid"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["handled_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_tickets_customer_id", "support_tickets", ["customer_id"])
    op.create_index("ix_support_tickets_status_created", "support_tickets", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_support_tickets_status_created", table_name="support_tickets")
    op.drop_index("ix_support_tickets_customer_id", table_name="support_tickets")
    op.drop_table("support_tickets")
