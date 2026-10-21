import re
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import DbSession, require_roles
from app.models.catalog import ActiveIngredient, Category, Inventory, Product, ProductIngredient
from app.models.customer import User, UserRole
from app.schemas.admin_catalog import AdminProductCreate, AdminProductRead, AdminProductUpdate
from app.api.routes.catalog import _catalog_load_options, _product_read

router = APIRouter(prefix="/admin/catalog", tags=["catalog administration"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result[:150] or "medicine"


def _loaded(db: Session, product_id: UUID) -> Product:
    row = db.scalars(select(Product).where(Product.id == product_id).options(*_catalog_load_options())).unique().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return row


def _admin_read(product: Product) -> AdminProductRead:
    return AdminProductRead(
        **_product_read(product).model_dump(), sku=product.sku, is_active=product.is_active,
        low_stock_threshold=product.inventory.low_stock_threshold if product.inventory else 5,
    )


@router.get("/products", response_model=list[AdminProductRead])
def list_products(_admin: AdminUser, db: DbSession, query: Annotated[str | None, Query(max_length=100)] = None):
    statement = select(Product).options(*_catalog_load_options()).order_by(Product.name.asc())
    if query and query.strip():
        term = f"%{query.strip()}%"
        statement = statement.where(or_(Product.name.ilike(term), Product.sku.ilike(term)))
    return [_admin_read(row) for row in db.scalars(statement).unique().all()]


@router.post("/products", response_model=AdminProductRead, status_code=201)
def create_product(body: AdminProductCreate, _admin: AdminUser, db: DbSession) -> AdminProductRead:
    if body.selling_price > body.mrp:
        raise HTTPException(status_code=422, detail="Selling price cannot be higher than MRP")
    category = db.get(Category, body.category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    product = Product(
        slug=_slug(body.name), sku=body.sku.strip().upper(), name=body.name.strip(), category_id=category.id,
        description=body.description.strip(), dosage_form=body.dosage_form.strip(), manufacturer=body.manufacturer.strip(),
        pack_quantity=body.pack_quantity, pack_unit=body.pack_unit.strip(), mrp=body.mrp,
        selling_price=body.selling_price, prescription_required=body.prescription_required,
        is_synthetic=True, is_active=True,
    )
    product.inventory = Inventory(available_quantity=body.stock_quantity, low_stock_threshold=body.low_stock_threshold)
    for item in body.ingredients:
        name = item.name.strip()
        ingredient = db.scalar(select(ActiveIngredient).where(ActiveIngredient.name.ilike(name)))
        if ingredient is None:
            ingredient = ActiveIngredient(name=name, slug=_slug(name))
            db.add(ingredient)
            db.flush()
        product.ingredients.append(ProductIngredient(
            ingredient=ingredient, strength_amount=item.strength_amount, strength_unit=item.strength_unit.strip()
        ))
    db.add(product)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A product with this name, SKU, or ingredient already exists") from error
    return _admin_read(_loaded(db, product.id))


@router.patch("/products/{product_id}", response_model=AdminProductRead)
def update_product(product_id: UUID, body: AdminProductUpdate, _admin: AdminUser, db: DbSession) -> AdminProductRead:
    product = db.scalars(select(Product).where(Product.id == product_id).options(joinedload(Product.inventory))).unique().one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    changes = body.model_dump(exclude_unset=True)
    stock = changes.pop("stock_quantity", None)
    threshold = changes.pop("low_stock_threshold", None)
    for key, value in changes.items():
        if value is not None:
            setattr(product, key, value)
    if "mrp" in changes and product.mrp < product.selling_price or "selling_price" in changes and product.selling_price > product.mrp:
        raise HTTPException(status_code=422, detail="Selling price cannot be higher than MRP")
    if product.inventory is None:
        product.inventory = Inventory(available_quantity=stock if stock is not None else 0, low_stock_threshold=threshold if threshold is not None else 5)
    elif stock is not None:
        product.inventory.available_quantity = stock
    if threshold is not None:
        product.inventory.low_stock_threshold = threshold
    db.commit()
    return _admin_read(_loaded(db, product.id))
