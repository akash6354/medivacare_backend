from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str


class ActiveIngredientRead(BaseModel):
    name: str
    strength_amount: Decimal
    strength_unit: str


class CatalogProductRead(BaseModel):
    id: UUID
    slug: str
    name: str
    category: str
    description: str
    dosage_form: str
    manufacturer: str
    pack_quantity: int
    pack_unit: str
    mrp: Decimal
    selling_price: Decimal
    savings: Decimal
    unit_price: Decimal
    currency: Literal["INR"] = "INR"
    stock_quantity: int
    in_stock: bool
    prescription_required: bool
    synthetic_data: bool
    active_ingredients: list[ActiveIngredientRead]


class CatalogPage(BaseModel):
    items: list[CatalogProductRead]
    total: int
    page: int
    page_size: int
    total_pages: int
