"""Add Razorpay payment attempts and idempotent webhook records.

Revision ID: 0004_razorpay_payments
Revises: 0003_orders
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_razorpay_payments"
down_revision: Union[str, None] = "0003_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_order_id", sa.String(length=64), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=64), nullable=True),
        sa.Column("provider_mode", sa.String(length=4), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount_paise > 0", name="ck_payment_attempt_amount_positive"),
        sa.CheckConstraint("provider_mode IN ('test', 'live')", name="ck_payment_attempt_provider_mode_valid"),
        sa.CheckConstraint(
            "status IN ('creating', 'pending', 'authorized', 'captured', 'failed', 'expired')",
            name="ck_payment_attempt_status_valid",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["customer_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_payment_attempt_order"),
        sa.UniqueConstraint("provider_order_id", name="uq_payment_attempt_provider_order_id"),
        sa.UniqueConstraint("provider_payment_id", name="uq_payment_attempt_provider_payment_id"),
    )

    op.create_table(
        "razorpay_webhook_events",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("provider_order_id", sa.String(length=64), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=64), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('processed', 'ignored', 'unmatched')",
            name="ck_razorpay_webhook_outcome_valid",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_razorpay_webhook_events_provider_order_id",
        "razorpay_webhook_events",
        ["provider_order_id"],
    )
    op.create_index(
        "ix_razorpay_webhook_events_provider_payment_id",
        "razorpay_webhook_events",
        ["provider_payment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_razorpay_webhook_events_provider_payment_id", table_name="razorpay_webhook_events")
    op.drop_index("ix_razorpay_webhook_events_provider_order_id", table_name="razorpay_webhook_events")
    op.drop_table("razorpay_webhook_events")
    op.drop_table("payment_attempts")
