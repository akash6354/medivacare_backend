from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CartItem(Base):
    __tablename__ = "customer_cart_items"
    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 20", name="ck_cart_quantity_range"),
    )

    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    product: Mapped["Product"] = relationship()


class Order(Base):
    __tablename__ = "customer_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_payment', 'placed', 'awaiting_prescription_review', "
            "'confirmed', 'processing', 'shipped', 'out_for_delivery', 'delivered', "
            "'cancelled', 'returned')",
            name="ck_orders_status_valid",
        ),
        CheckConstraint("payment_method IN ('cod', 'razorpay')", name="ck_orders_payment_method_valid"),
        CheckConstraint(
            "payment_status IN ('pending', 'authorized', 'captured', 'failed', "
            "'refund_pending', 'partially_refunded', 'refunded')",
            name="ck_orders_payment_status_valid",
        ),
        CheckConstraint("subtotal >= 0 AND discount >= 0 AND delivery_fee >= 0 AND total >= 0", name="ck_orders_nonnegative_totals"),
        Index("uq_customer_order_idempotency", "customer_id", "idempotency_key", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="placed")
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False, default="cod")
    payment_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    recipient_name: Mapped[str] = mapped_column(String(120), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(16), nullable=False)
    address_line1: Mapped[str] = mapped_column(String(200), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(12), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )
    payment_attempt: Mapped["PaymentAttempt | None"] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False
    )
    delivery: Mapped["Delivery | None"] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False
    )


class OrderItem(Base):
    __tablename__ = "customer_order_items"
    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 20", name="ck_order_item_quantity_range"),
        CheckConstraint("unit_price >= 0 AND line_total >= 0", name="ck_order_item_nonnegative_prices"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(80), nullable=False)
    dosage_form: Mapped[str] = mapped_column(String(80), nullable=False)
    pack_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    pack_unit: Mapped[str] = mapped_column(String(40), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    prescription_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    prescription_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    order: Mapped[Order] = relationship(back_populates="items")


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('creating', 'pending', 'authorized', 'captured', 'failed', 'expired')",
            name="ck_payment_attempt_status_valid",
        ),
        CheckConstraint("provider_mode IN ('test', 'live')", name="ck_payment_attempt_provider_mode_valid"),
        CheckConstraint("amount_paise > 0", name="ck_payment_attempt_amount_positive"),
        UniqueConstraint("order_id", name="uq_payment_attempt_order"),
        UniqueConstraint("provider_order_id", name="uq_payment_attempt_provider_order_id"),
        UniqueConstraint("provider_payment_id", name="uq_payment_attempt_provider_payment_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="CASCADE"), nullable=False
    )
    provider_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_mode: Mapped[str] = mapped_column(String(4), nullable=False, default="test")
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="creating")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    order: Mapped[Order] = relationship(back_populates="payment_attempt")


class RazorpayWebhookEvent(Base):
    __tablename__ = "razorpay_webhook_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('processed', 'ignored', 'unmatched')",
            name="ck_razorpay_webhook_outcome_valid",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
