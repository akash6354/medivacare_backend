from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


PrescriptionStatus = Literal["pending", "approved", "rejected"]


class CustomerPrescriptionRead(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str
    product_slug: str
    status: PrescriptionStatus
    review_note: str | None
    created_at: datetime
    reviewed_at: datetime | None


class PrescriptionReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class PrescriptionStaffRead(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str
    customer_email: str
    customer_phone: str
    product_id: UUID
    product_name: str
    media_type: str
    file_size: int
    status: PrescriptionStatus
    review_note: str | None
    created_at: datetime
    reviewed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class PrescriptionStaffPage(BaseModel):
    items: list[PrescriptionStaffRead]
    total: int
    page: int
    page_size: int


class PrescriptionReviewAuditRead(BaseModel):
    id: UUID
    reviewer_name: str
    previous_status: str
    status: str
    note: str | None
    created_at: datetime
