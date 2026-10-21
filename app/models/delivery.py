from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


DELIVERY_STATUSES = (
    "assigned",
    "picked_up",
    "in_transit",
    "out_for_delivery",
    "delivered",
    "failed",
    "returned",
    "cancelled",
)


class Delivery(Base):
    __tablename__ = "order_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('assigned', 'picked_up', 'in_transit', 'out_for_delivery', "
            "'delivered', 'failed', 'returned', 'cancelled')",
            name="ck_order_deliveries_status_valid",
        ),
        Index("ix_order_deliveries_status_updated", "status", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    tracking_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    carrier_name: Mapped[str] = mapped_column(String(100), nullable=False)
    courier_name: Mapped[str] = mapped_column(String(120), nullable=False)
    courier_phone: Mapped[str] = mapped_column(String(16), nullable=False)
    assigned_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="assigned")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    order: Mapped["Order"] = relationship(back_populates="delivery")
    events: Mapped[list["DeliveryEvent"]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan", order_by="DeliveryEvent.created_at"
    )


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('assigned', 'picked_up', 'in_transit', 'out_for_delivery', "
            "'delivered', 'failed', 'returned', 'cancelled')",
            name="ck_delivery_events_status_valid",
        ),
        Index("ix_delivery_events_delivery_created", "delivery_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    delivery_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_deliveries.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    delivery: Mapped[Delivery] = relationship(back_populates="events")
    actor: Mapped["User"] = relationship()
