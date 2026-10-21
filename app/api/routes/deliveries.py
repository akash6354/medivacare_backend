import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, require_roles
from app.models.audit import AdminAuditLog
from app.models.customer import User, UserRole
from app.models.delivery import Delivery, DeliveryEvent
from app.models.orders import Order
from app.schemas.delivery import DeliveryAssignmentRequest, DeliveryRead, DeliveryStatusUpdate
from app.services.checkout import order_query
from app.services.order_workflow import ORDER_STATUS_TRANSITIONS, require_approved_prescriptions

router = APIRouter(prefix="/admin/orders", tags=["delivery tracking"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
DELIVERY_TRANSITIONS = {
    "assigned": {"picked_up"}, "picked_up": {"in_transit"},
    "in_transit": {"out_for_delivery", "failed", "returned"},
    "out_for_delivery": {"delivered", "failed", "returned"},
    "failed": {"out_for_delivery", "returned"},
}


def _locked_order(db: Session, order_number: str) -> Order:
    order = db.scalars(order_query().where(Order.order_number == order_number).with_for_update()).unique().one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _audit(db: Session, admin: User, order: Order, action: str, details: dict[str, str]) -> None:
    db.add(AdminAuditLog(actor_user_id=admin.id, order_id=order.id, action=action, details=details))


@router.post("/{order_number}/delivery", response_model=DeliveryRead, status_code=201)
def assign_delivery(order_number: str, body: DeliveryAssignmentRequest, admin: AdminUser, db: DbSession) -> DeliveryRead:
    order = _locked_order(db, order_number)
    if order.status != "processing":
        raise HTTPException(status_code=409, detail="Delivery can be assigned only while an order is processing")
    if order.payment_method != "cod" and order.payment_status != "captured":
        raise HTTPException(status_code=409, detail="Online payment must be captured before delivery assignment")
    if order.delivery is not None:
        raise HTTPException(status_code=409, detail="A delivery is already assigned to this order")
    require_approved_prescriptions(db, order)
    delivery = Delivery(
        tracking_number=f"MC-DL-{secrets.token_hex(6).upper()}", carrier_name=body.carrier_name.strip(),
        courier_name=body.courier_name.strip(), courier_phone=body.courier_phone,
        assigned_by_user_id=admin.id, status="assigned",
    )
    delivery.events.append(DeliveryEvent(actor_user_id=admin.id, status="assigned", note="Courier assigned"))
    order.delivery = delivery
    db.add(delivery)
    _audit(db, admin, order, "delivery.assigned", {"tracking_number": delivery.tracking_number, "carrier": delivery.carrier_name})
    db.commit()
    return db.scalars(select(Delivery).where(Delivery.id == delivery.id).options()).one()


@router.patch("/{order_number}/delivery/status", response_model=DeliveryRead)
def update_delivery(order_number: str, body: DeliveryStatusUpdate, admin: AdminUser, db: DbSession) -> DeliveryRead:
    order = _locked_order(db, order_number)
    delivery = order.delivery
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery has not been assigned")
    if body.status not in DELIVERY_TRANSITIONS.get(delivery.status, set()):
        raise HTTPException(status_code=409, detail=f"Delivery cannot move from {delivery.status} to {body.status}")
    note = body.note.strip() if body.note else None
    if body.status == "failed" and not note:
        raise HTTPException(status_code=422, detail="A note is required when delivery fails")
    order_target = {"picked_up": "shipped", "in_transit": "shipped", "out_for_delivery": "out_for_delivery", "delivered": "delivered", "returned": "returned"}.get(body.status)
    if order_target and order.status != order_target:
        if order_target not in ORDER_STATUS_TRANSITIONS.get(order.status, set()):
            raise HTTPException(status_code=409, detail=f"Order cannot move from {order.status} to {order_target}")
        require_approved_prescriptions(db, order)
        previous_order_status = order.status
        order.status = order_target
        _audit(db, admin, order, "order.status_changed", {"from": previous_order_status, "to": order_target})
    previous = delivery.status
    delivery.status = body.status
    delivery.events.append(DeliveryEvent(actor_user_id=admin.id, status=body.status, note=note))
    _audit(db, admin, order, "delivery.status_updated", {"from": previous, "to": body.status})
    db.commit()
    return db.scalars(select(Delivery).where(Delivery.id == delivery.id)).unique().one()
