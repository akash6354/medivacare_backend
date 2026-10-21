"""Add customer carts and persistent COD orders.

Revision ID: 0003_orders
Revises: 0002_customers
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_orders"
down_revision: Union[str, None] = "0002_customers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_cart_items",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity BETWEEN 1 AND 20", name="ck_cart_quantity_range"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("customer_id", "product_id"),
    )

    op.create_table(
        "customer_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payment_method", sa.String(length=20), nullable=False),
        sa.Column("payment_status", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Numeric(10, 2), nullable=False),
        sa.Column("discount", sa.Numeric(10, 2), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(10, 2), nullable=False),
        sa.Column("total", sa.Numeric(10, 2), nullable=False),
        sa.Column("recipient_name", sa.String(length=120), nullable=False),
        sa.Column("recipient_phone", sa.String(length=16), nullable=False),
        sa.Column("address_line1", sa.String(length=200), nullable=False),
        sa.Column("address_line2", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=100), nullable=False),
        sa.Column("postal_code", sa.String(length=12), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_payment', 'placed', 'awaiting_prescription_review', "
            "'confirmed', 'processing', 'shipped', 'out_for_delivery', 'delivered', "
            "'cancelled', 'returned')",
            name="ck_orders_status_valid",
        ),
        sa.CheckConstraint("payment_method IN ('cod', 'razorpay')", name="ck_orders_payment_method_valid"),
        sa.CheckConstraint(
            "payment_status IN ('pending', 'authorized', 'captured', 'failed', "
            "'refund_pending', 'partially_refunded', 'refunded')",
            name="ck_orders_payment_status_valid",
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND discount >= 0 AND delivery_fee >= 0 AND total >= 0",
            name="ck_orders_nonnegative_totals",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_orders_customer_id", "customer_orders", ["customer_id"])
    op.create_index("ix_customer_orders_order_number", "customer_orders", ["order_number"], unique=True)
    op.create_index(
        "uq_customer_order_idempotency",
        "customer_orders",
        ["customer_id", "idempotency_key"],
        unique=True,
    )

    op.create_table(
        "customer_order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("product_sku", sa.String(length=80), nullable=False),
        sa.Column("dosage_form", sa.String(length=80), nullable=False),
        sa.Column("pack_quantity", sa.Integer(), nullable=False),
        sa.Column("pack_unit", sa.String(length=40), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("prescription_required", sa.Boolean(), nullable=False),
        sa.CheckConstraint("quantity BETWEEN 1 AND 20", name="ck_order_item_quantity_range"),
        sa.CheckConstraint("unit_price >= 0 AND line_total >= 0", name="ck_order_item_nonnegative_prices"),
        sa.ForeignKeyConstraint(["order_id"], ["customer_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_order_items_order_id", "customer_order_items", ["order_id"])
    op.create_index("ix_customer_order_items_product_id", "customer_order_items", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_order_items_product_id", table_name="customer_order_items")
    op.drop_index("ix_customer_order_items_order_id", table_name="customer_order_items")
    op.drop_table("customer_order_items")
    op.drop_index("uq_customer_order_idempotency", table_name="customer_orders")
    op.drop_index("ix_customer_orders_order_number", table_name="customer_orders")
    op.drop_index("ix_customer_orders_customer_id", table_name="customer_orders")
    op.drop_table("customer_orders")
    op.drop_table("customer_cart_items")
