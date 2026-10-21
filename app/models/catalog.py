from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class ActiveIngredient(Base):
    __tablename__ = "active_ingredients"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)

    products: Mapped[list["ProductIngredient"]] = relationship(back_populates="ingredient")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("pack_quantity > 0", name="ck_products_pack_quantity_positive"),
        CheckConstraint("selling_price > 0 AND mrp >= selling_price", name="ck_products_valid_prices"),
        Index("ix_products_active_category", "is_active", "category_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    description: Mapped[str] = mapped_column(Text)
    dosage_form: Mapped[str] = mapped_column(String(80))
    manufacturer: Mapped[str] = mapped_column(String(160))
    pack_quantity: Mapped[int] = mapped_column(Integer)
    pack_unit: Mapped[str] = mapped_column(String(40))
    mrp: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    selling_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    prescription_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category: Mapped[Category] = relationship(back_populates="products")
    ingredients: Mapped[list["ProductIngredient"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    inventory: Mapped["Inventory"] = relationship(
        back_populates="product", cascade="all, delete-orphan", uselist=False
    )


class ProductIngredient(Base):
    __tablename__ = "product_ingredients"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[UUID] = mapped_column(
        ForeignKey("active_ingredients.id", ondelete="RESTRICT"), primary_key=True
    )
    strength_amount: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    strength_unit: Mapped[str] = mapped_column(String(40))

    product: Mapped[Product] = relationship(back_populates="ingredients")
    ingredient: Mapped[ActiveIngredient] = relationship(back_populates="products")


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("available_quantity >= 0", name="ck_inventory_nonnegative"),
        CheckConstraint("low_stock_threshold >= 0", name="ck_inventory_threshold_nonnegative"),
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    available_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    product: Mapped[Product] = relationship(back_populates="inventory")
