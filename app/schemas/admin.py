from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.orders import OrderItemRead
from app.schemas.delivery import DeliveryRead

OrderStatus = Literal[
    "pending_payment",
    "placed",
    "awaiting_prescription_review",
    "confirmed",
    "processing",
    "shipped",
    "out_for_delivery",
    "delivered",
    "cancelled",
    "returned",
]


class AdminOrderStatusUpdate(BaseModel):
    status: OrderStatus


class AdminOrderRead(BaseModel):
    id: UUID
    order_number: str
    status: str
    payment_method: str
    payment_status: str
    currency: Literal["INR"]
    subtotal: Decimal
    discount: Decimal
    delivery_fee: Decimal
    total: Decimal
    customer_name: str
    customer_email: str
    customer_phone: str
    recipient_name: str
    recipient_phone: str
    address_line1: str
    address_line2: str | None
    city: str
    state: str
    postal_code: str
    country_code: str
    razorpay_order_id: str | None
    razorpay_payment_id: str | None
    items: list[OrderItemRead]
    delivery: DeliveryRead | None = None
    created_at: datetime
    updated_at: datetime


class AdminOrderPage(BaseModel):
    items: list[AdminOrderRead]
    total: int
    page: int
    page_size: int


class AdminDashboardRead(BaseModel):
    total_orders: int
    active_orders: int
    awaiting_payment: int
    captured_sales: Decimal


class AdminAuditRead(BaseModel):
    id: UUID
    actor_name: str
    action: str
    details: dict[str, str]
    created_at: datetime
