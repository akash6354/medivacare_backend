"""Add private prescriptions and pharmacist review audit history.

Revision ID: 0006_prescriptions
Revises: 0005_admin_audit
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006_prescriptions"
down_revision: Union[str, None] = "0005_admin_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prescriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=48), nullable=False),
        sa.Column("media_type", sa.String(length=40), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_prescriptions_status_valid"),
        sa.CheckConstraint("file_size BETWEEN 1 AND 5242880", name="ck_prescriptions_file_size_valid"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_prescriptions_customer_id", "prescriptions", ["customer_id"])
    op.create_index("ix_prescriptions_product_id", "prescriptions", ["product_id"])
    op.create_index("ix_prescriptions_reviewer_user_id", "prescriptions", ["reviewer_user_id"])
    op.create_index(
        "ix_prescriptions_customer_product_created", "prescriptions", ["customer_id", "product_id", "created_at"]
    )
    op.create_index("ix_prescriptions_status_created", "prescriptions", ["status", "created_at"])

    op.create_table(
        "prescription_review_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prescription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('approved', 'rejected')", name="ck_prescription_review_audits_status_valid"),
        sa.ForeignKeyConstraint(["prescription_id"], ["prescriptions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prescription_review_audits_reviewer_user_id", "prescription_review_audits", ["reviewer_user_id"])
    op.create_index(
        "ix_prescription_review_audits_prescription_created",
        "prescription_review_audits",
        ["prescription_id", "created_at"],
    )

    op.add_column("customer_order_items", sa.Column("prescription_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_customer_order_items_prescription_id_prescriptions",
        "customer_order_items",
        "prescriptions",
        ["prescription_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_customer_order_items_prescription_id", "customer_order_items", ["prescription_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_order_items_prescription_id", table_name="customer_order_items")
    op.drop_constraint(
        "fk_customer_order_items_prescription_id_prescriptions", "customer_order_items", type_="foreignkey"
    )
    op.drop_column("customer_order_items", "prescription_id")
    op.drop_index("ix_prescription_review_audits_prescription_created", table_name="prescription_review_audits")
    op.drop_index("ix_prescription_review_audits_reviewer_user_id", table_name="prescription_review_audits")
    op.drop_table("prescription_review_audits")
    op.drop_index("ix_prescriptions_status_created", table_name="prescriptions")
    op.drop_index("ix_prescriptions_customer_product_created", table_name="prescriptions")
    op.drop_index("ix_prescriptions_reviewer_user_id", table_name="prescriptions")
    op.drop_index("ix_prescriptions_product_id", table_name="prescriptions")
    op.drop_index("ix_prescriptions_customer_id", table_name="prescriptions")
    op.drop_table("prescriptions")
