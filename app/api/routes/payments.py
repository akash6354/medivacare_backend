from datetime import UTC, datetime
import hashlib
import json
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.models.orders import Order, PaymentAttempt, RazorpayWebhookEvent
from app.schemas.orders import (
    PaymentStatusRead,
    RazorpayCreateOrderRead,
    RazorpayCreateOrderRequest,
    RazorpayVerifyRequest,
)
from app.services.checkout import create_order_from_cart, get_existing_order, order_query
from app.services.payments import (
    apply_payment_state,
    expire_pending_attempt,
    expired,
    new_payment_attempt,
    lock_payment_order,
    owned_attempt_query,
    payment_status,
)
from app.services.razorpay import (
    create_or_retrieve_order,
    payment_credentials,
    razorpay_client,
    webhook_signature_is_valid,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments/razorpay", tags=["payments"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _create_payload(attempt: PaymentAttempt) -> RazorpayCreateOrderRead:
    settings = get_settings()
    if attempt.provider_mode != settings.razorpay_mode:
        raise HTTPException(status_code=409, detail="This payment attempt belongs to a different Razorpay mode")
    return RazorpayCreateOrderRead(
        key_id=settings.razorpay_key_id,
        razorpay_order_id=attempt.provider_order_id,
        amount=attempt.amount_paise,
        currency="INR",
        order_id=attempt.order.id,
        order_number=attempt.order.order_number,
        payment_attempt_id=attempt.id,
        expires_at=attempt.expires_at,
    )


def _get_owned_attempt(db: DbSession, user_id: UUID, attempt_reference: str) -> PaymentAttempt | None:
    query = owned_attempt_query().join(Order).where(Order.customer_id == user_id)
    try:
        attempt_id = UUID(attempt_reference)
    except ValueError:
        return db.scalars(query.where(PaymentAttempt.provider_payment_id == attempt_reference)).unique().one_or_none()
    return db.scalars(query.where(
        (PaymentAttempt.provider_payment_id == attempt_reference) | (PaymentAttempt.id == attempt_id)
    )).unique().one_or_none()


def _ensure_provider_order(db, order: Order, attempt: PaymentAttempt, client) -> RazorpayCreateOrderRead:
    if attempt.provider_order_id:
        if attempt.status == "failed":
            attempt.status = "pending"
            order.payment_status = "pending"
            db.commit()
        return _create_payload(attempt)
    try:
        provider_order = create_or_retrieve_order(
            client,
            amount=attempt.amount_paise,
            receipt=order.order_number,
        )
    except Exception as error:
        logger.warning("Razorpay order initialization failed for local order %s (%s)", order.order_number, type(error).__name__)
        raise HTTPException(status_code=502, detail="Online checkout could not be initialized; you can safely retry") from error
    attempt.provider_order_id = provider_order["id"]
    attempt.status = "pending"
    db.commit()
    db.refresh(attempt)
    return _create_payload(attempt)


@router.post("/create-order", response_model=RazorpayCreateOrderRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def create_razorpay_order(
    request: Request,
    body: RazorpayCreateOrderRequest,
    user: CurrentUser,
    db: DbSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RazorpayCreateOrderRead:
    # Validate configuration before reserving stock or clearing the customer's cart.
    payment_credentials()
    client = razorpay_client()
    key = str(idempotency_key)
    existing = get_existing_order(db, user.id, key)
    if existing is not None and existing.payment_method != "razorpay":
        raise HTTPException(status_code=409, detail="This checkout key is already used for another payment method")
    order = existing or create_order_from_cart(db, user, body.address_id, key, "razorpay")

    attempt = order.payment_attempt
    if order.status == "cancelled" or (attempt is not None and attempt.status == "expired"):
        raise HTTPException(status_code=409, detail="This checkout has expired; review your cart and start a new order")
    if attempt is None:
        attempt = new_payment_attempt(db, order)
        attempt.order = order

    if expired(attempt):
        expire_pending_attempt(db, attempt, client)
        raise HTTPException(status_code=409, detail="This checkout has expired; review your cart and start a new order")
    if attempt.status == "authorized":
        raise HTTPException(status_code=409, detail="Payment is authorized and awaiting capture confirmation")
    return _ensure_provider_order(db, order, attempt, client)


@router.post("/orders/{order_number}/retry", response_model=RazorpayCreateOrderRead)
@limiter.limit("10/minute")
def retry_razorpay_order(
    order_number: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> RazorpayCreateOrderRead:
    payment_credentials()
    client = razorpay_client()
    order = db.scalars(
        order_query().where(Order.customer_id == user.id, Order.order_number == order_number)
    ).unique().one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_method != "razorpay" or order.payment_status == "captured":
        raise HTTPException(status_code=409, detail="This order does not need online payment")
    attempt = order.payment_attempt
    if attempt is None:
        raise HTTPException(status_code=409, detail="The online payment attempt could not be found")
    if order.status == "cancelled" or attempt.status == "expired":
        raise HTTPException(status_code=409, detail="This checkout has expired; review your cart and start a new order")
    if expired(attempt):
        expire_pending_attempt(db, attempt, client)
        raise HTTPException(status_code=409, detail="This checkout has expired; review your cart and start a new order")
    if attempt.status == "authorized":
        raise HTTPException(status_code=409, detail="Payment is authorized and awaiting capture confirmation")
    return _ensure_provider_order(db, order, attempt, client)


@router.post("/verify", response_model=PaymentStatusRead)
@limiter.limit("15/minute")
def verify_razorpay_payment(
    request: Request,
    body: RazorpayVerifyRequest,
    user: CurrentUser,
    db: DbSession,
) -> PaymentStatusRead:
    attempt = db.scalars(
        owned_attempt_query()
        .join(Order)
        .where(
            Order.customer_id == user.id,
            PaymentAttempt.provider_order_id == body.razorpay_order_id,
        )
    ).unique().one_or_none()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Payment attempt not found")
    if attempt.provider_mode != get_settings().razorpay_mode:
        raise HTTPException(status_code=409, detail="This payment attempt belongs to a different Razorpay mode")

    # Use the provider order ID from the stored attempt, not an untrusted order reference.
    from app.services.razorpay import checkout_signature_is_valid

    if not checkout_signature_is_valid(
        attempt.provider_order_id,
        body.razorpay_payment_id,
        body.razorpay_signature,
    ):
        raise HTTPException(status_code=400, detail="The payment signature could not be verified")
    if attempt.status == "captured" and attempt.provider_payment_id != body.razorpay_payment_id:
        raise HTTPException(status_code=409, detail="A different payment is already recorded for this order")

    try:
        payment = razorpay_client().payment.fetch(body.razorpay_payment_id)
    except HTTPException:
        raise
    except Exception as error:
        logger.warning("Razorpay payment status fetch failed for local order %s (%s)", attempt.order.order_number, type(error).__name__)
        raise HTTPException(status_code=502, detail="Payment status is temporarily unavailable; retry verification") from error

    if payment.get("order_id") != attempt.provider_order_id:
        raise HTTPException(status_code=409, detail="The payment does not belong to this checkout")
    if lock_payment_order(db, attempt) is None:
        raise HTTPException(status_code=404, detail="Payment attempt not found")
    if attempt.status == "captured" and attempt.provider_payment_id != body.razorpay_payment_id:
        raise HTTPException(status_code=409, detail="A different payment is already recorded for this order")
    if not apply_payment_state(attempt, payment):
        raise HTTPException(status_code=409, detail="The provider payment amount or currency does not match this order")
    db.commit()
    db.refresh(attempt)
    return payment_status(attempt)


@router.get("/{payment_reference}/status", response_model=PaymentStatusRead)
def get_razorpay_payment_status(
    payment_reference: str,
    user: CurrentUser,
    db: DbSession,
) -> PaymentStatusRead:
    attempt = _get_owned_attempt(db, user.id, payment_reference)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Payment attempt not found")
    if expired(attempt) and attempt.order.status == "pending_payment":
        try:
            client = razorpay_client()
            expire_pending_attempt(db, attempt, client)
        except HTTPException:
            # Status remains readable even when credentials were removed after checkout.
            pass
    return payment_status(attempt)


@webhook_router.post("/razorpay", status_code=status.HTTP_200_OK)
async def receive_razorpay_webhook(
    request: Request,
    db: DbSession,
    signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
    provider_event_id: Annotated[str | None, Header(alias="X-Razorpay-Event-Id")] = None,
) -> dict[str, bool]:
    raw_body = await request.body()
    if not signature:
        raise HTTPException(status_code=400, detail="Razorpay signature header is required")
    try:
        valid_signature = webhook_signature_is_valid(raw_body, signature)
    except HTTPException:
        raise
    if not valid_signature:
        raise HTTPException(status_code=400, detail="Webhook signature is invalid")
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=400, detail="Webhook body is not valid JSON") from error

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object")
    event_type = payload.get("event")
    if not isinstance(event_type, str) or not event_type or len(event_type) > 80:
        raise HTTPException(status_code=400, detail="Webhook event type is invalid")
    event_id = provider_event_id or hashlib.sha256(raw_body).hexdigest()
    if len(event_id) > 128:
        raise HTTPException(status_code=400, detail="Webhook event identifier is too long")

    webhook_payload = payload.get("payload")
    if not isinstance(webhook_payload, dict):
        webhook_payload = {}
    payment_payload = webhook_payload.get("payment")
    refund_payload = webhook_payload.get("refund")
    entity = payment_payload.get("entity", {}) if isinstance(payment_payload, dict) else {}
    refund_entity = refund_payload.get("entity", {}) if isinstance(refund_payload, dict) else {}
    provider_order_id = entity.get("order_id") if isinstance(entity, dict) else None
    provider_payment_id = entity.get("id") if isinstance(entity, dict) else None
    if event_type == "refund.processed" and isinstance(refund_entity, dict):
        provider_payment_id = refund_entity.get("payment_id")

    supported = {"payment.captured", "payment.failed", "refund.processed"}
    outcome = "ignored"
    attempt = None
    if event_type in supported:
        if provider_order_id:
            attempt = db.scalars(
                owned_attempt_query().where(PaymentAttempt.provider_order_id == provider_order_id)
            ).unique().one_or_none()
        elif provider_payment_id:
            attempt = db.scalars(
                owned_attempt_query().where(PaymentAttempt.provider_payment_id == provider_payment_id)
            ).unique().one_or_none()
        if attempt is None:
            outcome = "unmatched"
        elif attempt.provider_mode != get_settings().razorpay_mode:
            outcome = "ignored"
        elif event_type in {"payment.captured", "payment.failed"}:
            lock_payment_order(db, attempt)
            if apply_payment_state(attempt, entity):
                outcome = "processed"
            else:
                outcome = "ignored"
        elif event_type == "refund.processed":
            lock_payment_order(db, attempt)
            refund_amount = refund_entity.get("amount")
            if (
                attempt.provider_payment_id == provider_payment_id
                and isinstance(refund_amount, int)
                and refund_amount > 0
            ):
                attempt.order.payment_status = (
                    "refunded" if refund_amount >= attempt.amount_paise else "partially_refunded"
                )
                outcome = "processed"

    db.add(
        RazorpayWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            outcome=outcome,
            provider_order_id=provider_order_id,
            provider_payment_id=provider_payment_id,
            processed_at=datetime.now(UTC),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Duplicate deliveries are acknowledged; applying the event is idempotent.
        return {"received": True, "duplicate": True}
    return {"received": True, "duplicate": False}
