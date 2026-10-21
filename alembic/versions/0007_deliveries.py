"""Add simulated delivery assignments and tracking events.

Revision ID: 0007_deliveries
Revises: 0006_prescriptions
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_deliveries"
down_revision: Union[str, None] = "0006_prescriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DELIVERY_STATUS_CHECK = (
    "status IN ('assigned', 'picked_up', 'in_transit', 'out_for_delivery', "
    "'delivered', 'failed', 'returned', 'cancelled')"
)


def upgrade() -> None:
    op.create_table(
        "order_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracking_number", sa.String(length=32), nullable=False),
        sa.Column("carrier_name", sa.String(length=100), nullable=False),
        sa.Column("courier_name", sa.String(length=120), nullable=False),
        sa.Column("courier_phone", sa.String(length=16), nullable=False),
        sa.Column("assigned_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(DELIVERY_STATUS_CHECK, name="ck_order_deliveries_status_valid"),
        sa.ForeignKeyConstraint(["order_id"], ["customer_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
        sa.UniqueConstraint("tracking_number"),
    )
    op.create_index("ix_order_deliveries_assigned_by_user_id", "order_deliveries", ["assigned_by_user_id"])
    op.create_index("ix_order_deliveries_status_updated", "order_deliveries", ["status", "updated_at"])

    op.create_table(
        "delivery_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(DELIVERY_STATUS_CHECK, name="ck_delivery_events_status_valid"),
        sa.ForeignKeyConstraint(["delivery_id"], ["order_deliveries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_events_actor_user_id", "delivery_events", ["actor_user_id"])
    op.create_index("ix_delivery_events_delivery_created", "delivery_events", ["delivery_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_delivery_events_delivery_created", table_name="delivery_events")
    op.drop_index("ix_delivery_events_actor_user_id", table_name="delivery_events")
    op.drop_table("delivery_events")
    op.drop_index("ix_order_deliveries_status_updated", table_name="order_deliveries")
    op.drop_index("ix_order_deliveries_assigned_by_user_id", table_name="order_deliveries")
    op.drop_table("order_deliveries")
