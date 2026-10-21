from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import DbSession, require_roles
from app.models.audit import AdminAuditLog
from app.models.customer import User, UserRole
from app.models.delivery import Delivery, DeliveryEvent
from app.models.orders import Order
from app.schemas.admin import (
    AdminAuditRead,
    AdminDashboardRead,
    AdminOrderPage,
    AdminOrderRead,
    AdminOrderStatusUpdate,
)
from app.services.checkout import restore_order_stock
from app.services.order_workflow import ORDER_STATUS_TRANSITIONS, require_approved_prescriptions

router = APIRouter(prefix="/admin", tags=["administration"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]

STATUS_TRANSITIONS = ORDER_STATUS_TRANSITIONS
VALID_ORDER_STATUSES = set(STATUS_TRANSITIONS) | set().union(*STATUS_TRANSITIONS.values()) | {
    "pending_payment",
    "awaiting_prescription_review",
}


def _order_query():
    return select(Order).options(
        joinedload(Order.customer),
        selectinload(Order.items),
        selectinload(Order.payment_attempt),
        selectinload(Order.delivery).selectinload(Delivery.events),
    )


def _admin_order(order: Order) -> AdminOrderRead:
    return AdminOrderRead(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        currency=order.currency,
        subtotal=order.subtotal,
        discount=order.discount,
        delivery_fee=order.delivery_fee,
        total=order.total,
        customer_name=order.customer.full_name,
        customer_email=order.customer.email,
        customer_phone=order.customer.phone,
        recipient_name=order.recipient_name,
        recipient_phone=order.recipient_phone,
        address_line1=order.address_line1,
        address_line2=order.address_line2,
        city=order.city,
        state=order.state,
        postal_code=order.postal_code,
        country_code=order.country_code,
        razorpay_order_id=order.payment_attempt.provider_order_id if order.payment_attempt else None,
        razorpay_payment_id=order.payment_attempt.provider_payment_id if order.payment_attempt else None,
        items=order.items,
        delivery=order.delivery,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def _find_order(db: Session, order_number: str, *, lock: bool = False) -> Order:
    query = _order_query().where(Order.order_number == order_number)
    if lock:
        query = query.with_for_update()
    order = db.scalars(query).unique().one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _record_action(db: Session, actor: User, order: Order, action: str, details: dict[str, str]) -> None:
    db.add(
        AdminAuditLog(
            actor_user_id=actor.id,
            order_id=order.id,
            action=action,
            details=details,
        )
    )


@router.get("/dashboard", response_model=AdminDashboardRead)
def dashboard(_admin: AdminUser, db: DbSession) -> AdminDashboardRead:
    total = db.scalar(select(func.count(Order.id))) or 0
    active = db.scalar(
        select(func.count(Order.id)).where(
            Order.status.notin_(("delivered", "cancelled", "returned"))
        )
    ) or 0
    awaiting_payment = db.scalar(
        select(func.count(Order.id)).where(Order.status == "pending_payment")
    ) or 0
    captured_sales = db.scalar(
        select(func.coalesce(func.sum(Order.total), 0)).where(Order.payment_status == "captured")
    ) or Decimal("0.00")
    return AdminDashboardRead(
        total_orders=total,
        active_orders=active,
        awaiting_payment=awaiting_payment,
        captured_sales=captured_sales,
    )


@router.get("/orders", response_model=AdminOrderPage)
def list_admin_orders(
    _admin: AdminUser,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
    status: Annotated[str | None, Query(max_length=40)] = None,
    query: Annotated[str | None, Query(max_length=80)] = None,
) -> AdminOrderPage:
    filters = []
    if status:
        if status not in VALID_ORDER_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown order status")
        filters.append(Order.status == status)
    if query and query.strip():
        term = f"%{query.strip()}%"
        filters.append(
            or_(
                Order.order_number.ilike(term),
                Order.customer.has(User.full_name.ilike(term)),
                Order.customer.has(User.email.ilike(term)),
                Order.customer.has(User.phone.ilike(term)),
            )
        )
    total = db.scalar(select(func.count(Order.id)).where(*filters)) or 0
    orders = db.scalars(
        _order_query()
        .where(*filters)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()
    return AdminOrderPage(
        items=[_admin_order(order) for order in orders],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/orders/{order_number}", response_model=AdminOrderRead)
def get_admin_order(order_number: str, _admin: AdminUser, db: DbSession) -> AdminOrderRead:
    return _admin_order(_find_order(db, order_number))


@router.get("/orders/{order_number}/history", response_model=list[AdminAuditRead])
def get_admin_order_history(order_number: str, _admin: AdminUser, db: DbSession) -> list[AdminAuditRead]:
    order = _find_order(db, order_number)
    rows = db.execute(
        select(AdminAuditLog, User.full_name)
        .join(User, User.id == AdminAuditLog.actor_user_id)
        .where(AdminAuditLog.order_id == order.id)
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
    ).all()
    return [
        AdminAuditRead(
            id=entry.id,
            actor_name=name,
            action=entry.action,
            details={str(key): str(value) for key, value in (entry.details or {}).items()},
            created_at=entry.created_at,
        )
        for entry, name in rows
    ]


@router.patch("/orders/{order_number}/status", response_model=AdminOrderRead)
def update_order_status(
    order_number: str,
    body: AdminOrderStatusUpdate,
    admin: AdminUser,
    db: DbSession,
) -> AdminOrderRead:
    order = _find_order(db, order_number, lock=True)
    if body.status == order.status:
        return _admin_order(order)
    if body.status not in STATUS_TRANSITIONS.get(order.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Order cannot move from {order.status.replace('_', ' ')} to {body.status.replace('_', ' ')}",
        )
    delivery_managed = {"shipped", "out_for_delivery", "delivered", "returned"}
    if order.delivery is not None and body.status in delivery_managed:
        raise HTTPException(status_code=409, detail="Update this order through its simulated delivery tracking workflow")
    if body.status in {"processing", "shipped", "out_for_delivery", "delivered"}:
        require_approved_prescriptions(db, order)
    if body.status == "cancelled":
        if order.payment_method != "cod" or order.payment_status == "captured":
            raise HTTPException(status_code=409, detail="Online or collected orders require payment reconciliation before cancellation")
        restore_order_stock(db, order)

    previous = order.status
    order.status = body.status
    if body.status == "cancelled" and order.delivery is not None and order.delivery.status == "assigned":
        order.delivery.status = "cancelled"
        order.delivery.events.append(
            DeliveryEvent(actor_user_id=admin.id, status="cancelled", note="Order cancelled before courier pickup")
        )
    _record_action(db, admin, order, "order.status_changed", {"from": previous, "to": body.status})
    db.commit()
    return _admin_order(_find_order(db, order_number))


@router.post("/orders/{order_number}/cod-payment/collect", response_model=AdminOrderRead)
def record_cod_collection(order_number: str, admin: AdminUser, db: DbSession) -> AdminOrderRead:
    order = _find_order(db, order_number, lock=True)
    if order.payment_method != "cod":
        raise HTTPException(status_code=409, detail="Only cash on delivery orders can record cash collection")
    if order.status != "delivered":
        raise HTTPException(status_code=409, detail="Cash can be recorded as collected only after delivery")
    if order.payment_status == "captured":
        return _admin_order(order)
    if order.payment_status != "pending":
        raise HTTPException(status_code=409, detail="This COD order is not awaiting collection")

    order.payment_status = "captured"
    _record_action(db, admin, order, "cod.payment_collected", {"amount": str(order.total), "currency": order.currency})
    db.commit()
    return _admin_order(_find_order(db, order_number))
