from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


DeliveryStatus = Literal[
    "assigned",
    "picked_up",
    "in_transit",
    "out_for_delivery",
    "delivered",
    "failed",
    "returned",
    "cancelled",
]


class DeliveryAssignmentRequest(BaseModel):
    carrier_name: str = Field(min_length=2, max_length=100)
    courier_name: str = Field(min_length=2, max_length=120)
    courier_phone: str = Field(pattern=r"^\+?[1-9]\d{7,14}$", max_length=16)


class DeliveryStatusUpdate(BaseModel):
    status: Literal["picked_up", "in_transit", "out_for_delivery", "delivered", "failed", "returned"]
    note: str | None = Field(default=None, max_length=300)


class DeliveryEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: DeliveryStatus
    note: str | None
    created_at: datetime


class DeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tracking_number: str
    carrier_name: str
    courier_name: str
    status: DeliveryStatus
    assigned_at: datetime
    events: list[DeliveryEventRead]
