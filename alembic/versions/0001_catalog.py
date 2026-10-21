"""Create persistent catalog and inventory tables.

Revision ID: 0001_catalog
Revises:
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_catalog"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_categories_slug", "categories", ["slug"], unique=True)

    op.create_table(
        "active_ingredients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_active_ingredients_slug", "active_ingredients", ["slug"], unique=True)
    op.create_index("ix_active_ingredients_name", "active_ingredients", ["name"], unique=True)

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("dosage_form", sa.String(length=80), nullable=False),
        sa.Column("manufacturer", sa.String(length=160), nullable=False),
        sa.Column("pack_quantity", sa.Integer(), nullable=False),
        sa.Column("pack_unit", sa.String(length=40), nullable=False),
        sa.Column("mrp", sa.Numeric(10, 2), nullable=False),
        sa.Column("selling_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("prescription_required", sa.Boolean(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("pack_quantity > 0", name="ck_products_pack_quantity_positive"),
        sa.CheckConstraint("selling_price > 0 AND mrp >= selling_price", name="ck_products_valid_prices"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_slug", "products", ["slug"], unique=True)
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)
    op.create_index("ix_products_name", "products", ["name"], unique=False)
    op.create_index("ix_products_category_id", "products", ["category_id"], unique=False)
    op.create_index("ix_products_active_category", "products", ["is_active", "category_id"], unique=False)

    op.create_table(
        "product_ingredients",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingredient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strength_amount", sa.Numeric(10, 3), nullable=False),
        sa.Column("strength_unit", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["ingredient_id"], ["active_ingredients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("product_id", "ingredient_id"),
    )

    op.create_table(
        "inventory",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("available_quantity", sa.Integer(), nullable=False),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("available_quantity >= 0", name="ck_inventory_nonnegative"),
        sa.CheckConstraint("low_stock_threshold >= 0", name="ck_inventory_threshold_nonnegative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("product_id"),
    )


def downgrade() -> None:
    op.drop_table("inventory")
    op.drop_table("product_ingredients")
    op.drop_index("ix_products_active_category", table_name="products")
    op.drop_index("ix_products_category_id", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_index("ix_products_slug", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_active_ingredients_name", table_name="active_ingredients")
    op.drop_index("ix_active_ingredients_slug", table_name="active_ingredients")
    op.drop_table("active_ingredients")
    op.drop_index("ix_categories_slug", table_name="categories")
    op.drop_table("categories")
