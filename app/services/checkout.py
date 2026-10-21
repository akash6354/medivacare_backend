from datetime import UTC, datetime
from decimal import Decimal
import secrets
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import get_settings
from app.models.catalog import Inventory, Product
from app.models.customer import Address, User
from app.models.orders import CartItem, Order, OrderItem
from app.models.prescriptions import Prescription
from app.models.delivery import Delivery
from app.services.prescriptions import latest_prescriptions_for_products


def order_query():
    return select(Order).options(
        selectinload(Order.items),
        selectinload(Order.payment_attempt),
        selectinload(Order.delivery).selectinload(Delivery.events),
    )


def get_existing_order(db, customer_id: UUID, key: str) -> Order | None:
    return db.scalars(
        order_query().where(Order.customer_id == customer_id, Order.idempotency_key == key)
    ).unique().one_or_none()


def create_order_from_cart(
    db,
    user: User,
    address_id: UUID,
    idempotency_key: str,
    payment_method: str,
) -> Order:
    """Create a local order and reserve its stock in the same database transaction."""
    existing = get_existing_order(db, user.id, idempotency_key)
    if existing is not None:
        if existing.payment_method != payment_method:
            raise HTTPException(status_code=409, detail="This checkout key is already used for another payment method")
        return existing

    address = db.scalar(
        select(Address).where(Address.id == address_id, Address.customer_id == user.id)
    )
    if address is None:
        raise HTTPException(status_code=404, detail="Delivery address not found")

    cart_rows = db.scalars(
        select(CartItem)
        .where(CartItem.customer_id == user.id)
        .options(
            joinedload(CartItem.product).joinedload(Product.inventory),
            joinedload(CartItem.product).joinedload(Product.category),
        )
        .order_by(CartItem.product_id.asc())
    ).unique().all()
    if not cart_rows:
        raise HTTPException(status_code=409, detail="Your cart is empty")

    rx_product_ids = [item.product_id for item in cart_rows if item.product.prescription_required]
    current_prescriptions = latest_prescriptions_for_products(db, user.id, rx_product_ids)

    for item in cart_rows:
        product = item.product
        available = product.inventory.available_quantity if product.inventory else 0
        if not product.is_active or not product.category.is_active:
            raise HTTPException(status_code=409, detail=f"{product.name} is no longer available")
        if product.prescription_required:
            prescription = current_prescriptions.get(product.id)
            if prescription is None or prescription.status != "approved":
                raise HTTPException(status_code=409, detail=f"{product.name} requires an approved prescription")
        if available < item.quantity:
            raise HTTPException(status_code=409, detail=f"There is not enough stock for {product.name}")

    subtotal = sum(
        (item.product.selling_price * item.quantity for item in cart_rows), start=Decimal("0.00")
    ).quantize(Decimal("0.01"))
    settings = get_settings()
    delivery_fee = Decimal("0.00") if subtotal >= settings.free_delivery_minimum else settings.delivery_fee
    discount = Decimal("0.00")
    total = subtotal + delivery_fee - discount

    # Conditional updates prevent two simultaneous checkouts from overselling inventory.
    for item in cart_rows:
        result = db.execute(
            update(Inventory)
            .where(
                Inventory.product_id == item.product_id,
                Inventory.available_quantity >= item.quantity,
            )
            .values(available_quantity=Inventory.available_quantity - item.quantity)
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Stock changed while checking out {item.product.name}; review your cart",
            )

    now = datetime.now(UTC)
    order = Order(
        order_number=f"MC-{now:%y%m%d}-{secrets.token_hex(11).upper()}",
        customer_id=user.id,
        idempotency_key=idempotency_key,
        status="placed" if payment_method == "cod" else "pending_payment",
        payment_method=payment_method,
        payment_status="pending",
        currency="INR",
        subtotal=subtotal,
        discount=discount,
        delivery_fee=delivery_fee,
        total=total,
        recipient_name=address.recipient_name,
        recipient_phone=address.phone,
        address_line1=address.address_line1,
        address_line2=address.address_line2,
        city=address.city,
        state=address.state,
        postal_code=address.postal_code,
        country_code=address.country_code,
    )
    order.items = [
        OrderItem(
            product_id=item.product.id,
            product_name=item.product.name,
            product_sku=item.product.sku,
            dosage_form=item.product.dosage_form,
            pack_quantity=item.product.pack_quantity,
            pack_unit=item.product.pack_unit,
            unit_price=item.product.selling_price,
            quantity=item.quantity,
            line_total=item.product.selling_price * item.quantity,
            prescription_required=item.product.prescription_required,
            prescription_id=(
                current_prescriptions[item.product.id].id
                if item.product.prescription_required
                else None
            ),
        )
        for item in cart_rows
    ]
    db.add(order)
    for item in cart_rows:
        db.delete(item)
    try:
        db.commit()
        db.refresh(order)
    except IntegrityError as error:
        db.rollback()
        existing = get_existing_order(db, user.id, idempotency_key)
        if existing is not None:
            if existing.payment_method != payment_method:
                raise HTTPException(status_code=409, detail="This checkout key is already used for another payment method") from error
            return existing
        raise HTTPException(status_code=409, detail="The order could not be placed; review your cart") from error

    return db.scalars(order_query().where(Order.id == order.id)).unique().one()


def restore_order_stock(db, order: Order) -> None:
    for item in order.items:
        if item.product_id is not None:
            db.execute(
                update(Inventory)
                .where(Inventory.product_id == item.product_id)
                .values(available_quantity=Inventory.available_quantity + item.quantity)
            )

