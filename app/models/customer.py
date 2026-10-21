from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, Enum):
    CUSTOMER = "customer"
    ADMIN = "admin"
    PHARMACIST = "pharmacist"
    SUPPORT = "support"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('customer', 'admin', 'pharmacist', 'support')",
            name="ck_users_role_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.CUSTOMER.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    addresses: Mapped[list["Address"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    cart_items: Mapped[list["CartItem"]] = relationship(cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Address(Base):
    __tablename__ = "customer_addresses"
    __table_args__ = (
        Index(
            "uq_customer_one_default_address",
            "customer_id",
            unique=True,
            postgresql_where=text("is_default IS TRUE"),
            sqlite_where=text("is_default = 1"),
        ),
        Index("ix_customer_addresses_customer_id", "customer_id"),
        CheckConstraint("length(country_code) = 2", name="ck_addresses_country_code_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(40), default="Home")
    recipient_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(16))
    address_line1: Mapped[str] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(100))
    postal_code: Mapped[str] = mapped_column(String(12))
    country_code: Mapped[str] = mapped_column(String(2), default="IN")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    customer: Mapped[User] = relationship(back_populates="addresses")
