from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field
from app.schemas.catalog import CatalogProductRead


class AdminProductRead(CatalogProductRead):
    sku: str
    is_active: bool
    low_stock_threshold: int


class AdminIngredientInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    strength_amount: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    strength_unit: str = Field(min_length=1, max_length=40)


class AdminProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    sku: str = Field(min_length=2, max_length=80)
    category_id: UUID
    description: str = Field(min_length=4, max_length=4000)
    dosage_form: str = Field(min_length=2, max_length=80)
    manufacturer: str = Field(min_length=2, max_length=160)
    pack_quantity: int = Field(gt=0, le=10000)
    pack_unit: str = Field(min_length=1, max_length=40)
    mrp: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    selling_price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    prescription_required: bool = False
    stock_quantity: int = Field(default=0, ge=0, le=100000)
    low_stock_threshold: int = Field(default=5, ge=0, le=100000)
    ingredients: list[AdminIngredientInput] = Field(default_factory=list, max_length=10)


class AdminProductUpdate(BaseModel):
    is_active: bool | None = None
    selling_price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    mrp: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    stock_quantity: int | None = Field(default=None, ge=0, le=100000)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=100000)

