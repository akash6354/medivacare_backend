from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from app.schemas.delivery import DeliveryRead


class CartItemSet(BaseModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=20)


class CartItemRead(BaseModel):
    product_id: UUID
    slug: str
    name: str
    manufacturer: str
    dosage_form: str
    pack_quantity: int
    pack_unit: str
    unit_price: Decimal
    mrp: Decimal
    quantity: int
    line_total: Decimal
    stock_quantity: int
    product_active: bool
    in_stock: bool
    prescription_required: bool
    prescription_approved: bool = False


class CartRead(BaseModel):
    items: list[CartItemRead]
    item_count: int
    subtotal: Decimal
    delivery_fee: Decimal
    estimated_total: Decimal
    currency: Literal["INR"] = "INR"


class CheckoutRequest(BaseModel):
    address_id: UUID
    payment_method: Literal["cod"] = "cod"


class RazorpayCreateOrderRequest(BaseModel):
    address_id: UUID


class RazorpayVerifyRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=8, max_length=64)
    razorpay_payment_id: str = Field(min_length=8, max_length=64)
    razorpay_signature: str = Field(min_length=32, max_length=128)


class RazorpayCreateOrderRead(BaseModel):
    key_id: str
    razorpay_order_id: str
    amount: int
    currency: Literal["INR"]
    order_id: UUID
    order_number: str
    payment_attempt_id: UUID
    expires_at: datetime


class PaymentStatusRead(BaseModel):
    payment_attempt_id: UUID
    order_number: str
    provider_order_id: str | None
    provider_payment_id: str | None
    payment_status: str
    order_status: str
    amount_paise: int
    currency: Literal["INR"]
    expires_at: datetime


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: UUID | None
    product_name: str
    product_sku: str
    dosage_form: str
    pack_quantity: int
    pack_unit: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal
    prescription_required: bool
    prescription_id: UUID | None = None


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    recipient_name: str
    recipient_phone: str
    address_line1: str
    address_line2: str | None
    city: str
    state: str
    postal_code: str
    country_code: str
    items: list[OrderItemRead]
    delivery: DeliveryRead | None = None
    created_at: datetime


class OrderPage(BaseModel):
    items: list[OrderRead]
    total: int
    page: int
    page_size: int
