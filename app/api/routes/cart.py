from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.models.catalog import Category, Product
from app.models.customer import User
from app.models.orders import CartItem
from app.schemas.orders import CartItemRead, CartItemSet, CartRead
from app.services.prescriptions import latest_prescriptions_for_products

router = APIRouter(prefix="/cart", tags=["shopping cart"])


def _cart_read(db: DbSession, user: User) -> CartRead:
    rows = db.scalars(
        select(CartItem)
        .where(CartItem.customer_id == user.id)
        .options(
            joinedload(CartItem.product).joinedload(Product.inventory),
            joinedload(CartItem.product).joinedload(Product.category),
        )
        .order_by(CartItem.created_at.asc())
    ).unique().all()
    items = []
    subtotal = Decimal("0.00")
    item_count = 0
    rx_products = [row.product_id for row in rows if row.product.prescription_required]
    latest_prescriptions = latest_prescriptions_for_products(db, user.id, rx_products)
    for row in rows:
        product = row.product
        stock = product.inventory.available_quantity if product.inventory else 0
        line_total = product.selling_price * row.quantity
        subtotal += line_total
        item_count += row.quantity
        items.append(
            CartItemRead(
                product_id=product.id,
                slug=product.slug,
                name=product.name,
                manufacturer=product.manufacturer,
                dosage_form=product.dosage_form,
                pack_quantity=product.pack_quantity,
                pack_unit=product.pack_unit,
                unit_price=product.selling_price,
                mrp=product.mrp,
                quantity=row.quantity,
                line_total=line_total,
                stock_quantity=stock,
                product_active=product.is_active and product.category.is_active,
                in_stock=stock >= row.quantity,
                prescription_required=product.prescription_required,
                prescription_approved=(
                    latest_prescriptions.get(product.id) is not None
                    and latest_prescriptions[product.id].status == "approved"
                ),
            )
        )
    settings = get_settings()
    delivery_fee = (
        Decimal("0.00")
        if subtotal == 0 or subtotal >= settings.free_delivery_minimum
        else settings.delivery_fee
    )
    return CartRead(
        items=items,
        item_count=item_count,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        estimated_total=subtotal + delivery_fee,
    )


@router.get("", response_model=CartRead)
def get_cart(user: CurrentUser, db: DbSession) -> CartRead:
    return _cart_read(db, user)


@router.put("/items", response_model=CartRead)
def set_cart_item(body: CartItemSet, user: CurrentUser, db: DbSession) -> CartRead:
    product = db.scalar(
        select(Product)
        .where(
            Product.id == body.product_id,
            Product.is_active.is_(True),
            Product.category.has(Category.is_active.is_(True)),
        )
        .options(joinedload(Product.inventory), joinedload(Product.category))
    )
    if product is None:
        raise HTTPException(status_code=404, detail="This catalog listing is unavailable")
    available = product.inventory.available_quantity if product.inventory else 0
    if available < body.quantity:
        raise HTTPException(status_code=409, detail="There is not enough stock for that quantity")

    item = db.get(CartItem, (user.id, product.id))
    if item is None:
        item = CartItem(customer_id=user.id, product_id=product.id, quantity=body.quantity)
        db.add(item)
    else:
        item.quantity = body.quantity
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Concurrent absolute-quantity updates converge on the last requested value.
        item = db.get(CartItem, (user.id, product.id))
        if item is None:
            raise HTTPException(status_code=409, detail="Cart item could not be updated")
        item.quantity = body.quantity
        db.commit()
    return _cart_read(db, user)


@router.delete("/items/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_cart_item(product_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    item = db.get(CartItem, (user.id, product_id))
    if item is not None:
        db.delete(item)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
