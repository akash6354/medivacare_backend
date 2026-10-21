from decimal import Decimal
from math import ceil
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import get_db
from app.models.catalog import ActiveIngredient, Category, Inventory, Product, ProductIngredient
from app.schemas.catalog import (
    ActiveIngredientRead,
    CatalogPage,
    CatalogProductRead,
    CategoryRead,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])
DbSession = Annotated[Session, Depends(get_db)]


def _literal_search(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _product_read(product: Product) -> CatalogProductRead:
    inventory_quantity = product.inventory.available_quantity if product.inventory else 0
    mrp = Decimal(str(product.mrp)).quantize(Decimal("0.01"))
    selling_price = Decimal(str(product.selling_price)).quantize(Decimal("0.01"))
    savings = (mrp - selling_price).quantize(Decimal("0.01"))
    unit_price = (selling_price / product.pack_quantity).quantize(Decimal("0.01"))
    ingredients = [
        ActiveIngredientRead(
            name=link.ingredient.name,
            strength_amount=Decimal(str(link.strength_amount)).quantize(Decimal("0.001")),
            strength_unit=link.strength_unit,
        )
        for link in product.ingredients
    ]
    return CatalogProductRead(
        id=product.id,
        slug=product.slug,
        name=product.name,
        category=product.category.name,
        description=product.description,
        dosage_form=product.dosage_form,
        manufacturer=product.manufacturer,
        pack_quantity=product.pack_quantity,
        pack_unit=product.pack_unit,
        mrp=mrp,
        selling_price=selling_price,
        savings=savings,
        unit_price=unit_price,
        stock_quantity=inventory_quantity,
        in_stock=inventory_quantity > 0,
        prescription_required=product.prescription_required,
        synthetic_data=product.is_synthetic,
        active_ingredients=ingredients,
    )


def _catalog_load_options():
    return (
        joinedload(Product.category),
        joinedload(Product.inventory),
        selectinload(Product.ingredients).joinedload(ProductIngredient.ingredient),
    )


@router.get("/categories", response_model=list[CategoryRead])
def list_categories(db: DbSession) -> list[Category]:
    statement = (
        select(Category)
        .where(Category.is_active.is_(True), Category.products.any(Product.is_active.is_(True)))
        .order_by(Category.name.asc())
    )
    return list(db.scalars(statement).all())


@router.get("", response_model=CatalogPage)
def list_products(
    db: DbSession,
    q: Annotated[str | None, Query(max_length=120)] = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    ingredient: Annotated[str | None, Query(max_length=160)] = None,
    availability: Literal["all", "in_stock", "out_of_stock"] = "all",
    sort: Literal["relevance", "name", "price_asc", "price_desc", "savings"] = "relevance",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=48)] = 12,
) -> CatalogPage:
    statement = select(Product).where(
        Product.is_active.is_(True),
        Product.category.has(Category.is_active.is_(True)),
    )

    if q and q.strip():
        term = f"%{_literal_search(q.strip())}%"
        statement = statement.where(
            or_(
                Product.name.ilike(term, escape="\\"),
                Product.ingredients.any(
                    ProductIngredient.ingredient.has(ActiveIngredient.name.ilike(term, escape="\\"))
                ),
            )
        )

    if ingredient and ingredient.strip():
        term = f"%{_literal_search(ingredient.strip())}%"
        statement = statement.where(
            Product.ingredients.any(
                ProductIngredient.ingredient.has(ActiveIngredient.name.ilike(term, escape="\\"))
            )
        )

    if category:
        statement = statement.where(Product.category.has(Category.slug == category))

    if availability == "in_stock":
        statement = statement.where(Product.inventory.has(Inventory.available_quantity > 0))
    elif availability == "out_of_stock":
        statement = statement.where(
            or_(
                ~Product.inventory.has(),
                Product.inventory.has(Inventory.available_quantity == 0),
            )
        )

    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0

    if sort == "name":
        statement = statement.order_by(Product.name.asc())
    elif sort == "price_asc":
        statement = statement.order_by(Product.selling_price.asc(), Product.name.asc())
    elif sort == "price_desc":
        statement = statement.order_by(Product.selling_price.desc(), Product.name.asc())
    elif sort == "savings":
        statement = statement.order_by((Product.mrp - Product.selling_price).desc(), Product.name.asc())
    else:
        statement = statement.order_by(Product.name.asc())

    products = db.scalars(
        statement.options(*_catalog_load_options()).offset((page - 1) * page_size).limit(page_size)
    ).unique().all()
    return CatalogPage(
        items=[_product_read(product) for product in products],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
    )


@router.get("/{slug}", response_model=CatalogProductRead)
def get_product(slug: str, db: DbSession) -> CatalogProductRead:
    statement = (
        select(Product)
        .where(
            Product.slug == slug,
            Product.is_active.is_(True),
            Product.category.has(Category.is_active.is_(True)),
        )
        .options(*_catalog_load_options())
    )
    product = db.scalars(statement).unique().one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Medicine listing not found")
    return _product_read(product)
