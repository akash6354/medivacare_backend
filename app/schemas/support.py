from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SupportTicketCreate(BaseModel):
    subject: str = Field(min_length=4, max_length=120)
    message: str = Field(min_length=10, max_length=3000)


class SupportTicketUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved"]
    staff_note: str | None = Field(default=None, max_length=500)


class SupportTicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    customer_name: str | None = None
    customer_email: str | None = None
    subject: str
    message: str
    status: Literal["open", "in_progress", "resolved"]
    staff_note: str | None
    created_at: datetime
    updated_at: datetime
