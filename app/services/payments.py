from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.catalog import Inventory, Product
from app.models.orders import CartItem, Order, PaymentAttempt
from app.schemas.orders import PaymentStatusRead
from app.services.checkout import restore_order_stock
from app.services.razorpay import provider_payment_for_order


def new_payment_attempt(db: Session, order: Order) -> PaymentAttempt:
    amount_paise = int((order.total * Decimal("100")).quantize(Decimal("1")))
    attempt = PaymentAttempt(
        order_id=order.id,
        amount_paise=amount_paise,
        provider_mode=get_settings().razorpay_mode,
        currency="INR",
        status="creating",
        expires_at=datetime.now(UTC)
        + timedelta(minutes=get_settings().razorpay_order_expiry_minutes),
    )
    db.add(attempt)
    try:
        db.commit()
        db.refresh(attempt)
        return attempt
    except IntegrityError:
        db.rollback()
        # A simultaneous retry may have inserted the one allowed attempt already.
        existing = db.scalar(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id))
        if existing is not None:
            return existing
        raise


def payment_status(attempt: PaymentAttempt) -> PaymentStatusRead:
    return PaymentStatusRead(
        payment_attempt_id=attempt.id,
        order_number=attempt.order.order_number,
        provider_order_id=attempt.provider_order_id,
        provider_payment_id=attempt.provider_payment_id,
        payment_status=attempt.order.payment_status,
        order_status=attempt.order.status,
        amount_paise=attempt.amount_paise,
        currency="INR",
        expires_at=attempt.expires_at,
    )


def apply_payment_state(attempt: PaymentAttempt, payment: dict[str, Any]) -> bool:
    """Apply a provider-verified payment snapshot without allowing downgrades."""
    if (
        payment.get("order_id") != attempt.provider_order_id
        or payment.get("amount") != attempt.amount_paise
        or payment.get("currency") != "INR"
    ):
        return False

    provider_status = payment.get("status")
    payment_id = payment.get("id")
    if provider_status == "captured":
        if not payment_id:
            return False
        if attempt.status == "captured" and attempt.provider_payment_id not in (None, payment_id):
            return False
        attempt.provider_payment_id = payment_id
        attempt.status = "captured"
        if attempt.order.status == "cancelled":
            # A late capture after stock release needs refund handling, not fulfillment.
            if attempt.order.payment_status not in {"refunded", "partially_refunded"}:
                attempt.order.payment_status = "refund_pending"
        else:
            if attempt.order.payment_status not in {"refunded", "partially_refunded", "refund_pending"}:
                attempt.order.payment_status = "captured"
            if attempt.order.status == "pending_payment":
                attempt.order.status = "placed"
        return True

    if attempt.status == "captured":
        return True
    if provider_status == "authorized":
        attempt.provider_payment_id = payment_id or attempt.provider_payment_id
        attempt.status = "authorized"
        attempt.order.payment_status = "authorized"
    elif provider_status == "failed":
        attempt.provider_payment_id = payment_id or attempt.provider_payment_id
        attempt.status = "failed"
        attempt.order.payment_status = "failed"
    else:
        attempt.status = "pending"
    return True


def expired(attempt: PaymentAttempt, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    expiry = attempt.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry <= now


def lock_payment_order(db: Session, attempt: PaymentAttempt) -> Order | None:
    """Serialize payment and reservation transitions for the same local order."""
    order = db.scalar(
        select(Order)
        .where(Order.id == attempt.order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is not None:
        db.refresh(attempt, attribute_names=["status", "provider_payment_id"])
    return order


def expire_pending_attempt(db: Session, attempt: PaymentAttempt, client) -> bool:
    """Release expired inventory only after checking the provider's payment records."""
    if attempt.provider_mode != get_settings().razorpay_mode:
        return False
    if attempt.status in {"captured", "expired"} or attempt.order.status != "pending_payment":
        return False
    if not expired(attempt):
        return False

    provider_payments = None
    if attempt.provider_order_id:
        try:
            provider_payments = provider_payment_for_order(client, attempt.provider_order_id)
        except Exception:
            # Keep stock reserved when Razorpay cannot be reached; a later cleanup run retries.
            return False


    order = lock_payment_order(db, attempt)
    if order is None or order.status != "pending_payment" or attempt.status in {"captured", "expired"}:
        return False
    attempt.order = order

    captured = next((item for item in provider_payments or [] if item.get("status") == "captured"), None)
    if captured is not None:
        if apply_payment_state(attempt, captured):
            db.commit()
        return False
    if any(item.get("status") == "authorized" for item in provider_payments or []):
        attempt.status = "authorized"
        order.payment_status = "authorized"
        db.commit()
        return False
    if any(item.get("status") not in {"created", "failed"} for item in provider_payments or []):
        return False

    attempt.status = "expired"
    order.status = "cancelled"
    order.payment_status = "failed"
    restore_order_stock(db, order)
    restore_order_cart(db, order)
    db.commit()
    return True


def restore_order_cart(db: Session, order: Order) -> None:
    """Put still-active items back into an empty cart after an expired reservation."""
    for item in order.items:
        if item.product_id is None or db.get(CartItem, (order.customer_id, item.product_id)) is not None:
            continue
        product = db.get(Product, item.product_id)
        if product is None or not product.is_active or not product.category.is_active or product.prescription_required:
            continue
        available = db.scalar(
            select(Inventory.available_quantity).where(Inventory.product_id == item.product_id)
        ) or 0
        quantity = min(item.quantity, available, 20)
        if quantity > 0:
            db.add(CartItem(customer_id=order.customer_id, product_id=item.product_id, quantity=quantity))


def owned_attempt_query():
    return select(PaymentAttempt).options(
        selectinload(PaymentAttempt.order).selectinload(Order.items)
    )
