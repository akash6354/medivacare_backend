from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class AdminCustomerRead(BaseModel):
    id: UUID
    full_name: str
    email: str
    phone: str
    order_count: int
    created_at: datetime


class AdminPaymentRead(BaseModel):
    order_number: str
    customer_name: str
    customer_email: str
    payment_method: str
    payment_status: str
    order_status: str
    amount: Decimal
    currency: str
    provider_order_id: str | None
    provider_payment_id: str | None
    attempt_status: str | None
    created_at: datetime
    updated_at: datetime
