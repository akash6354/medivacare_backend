from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.api.deps import DbSession, require_roles
from app.models.customer import User, UserRole
from app.models.orders import Order, PaymentAttempt
from app.schemas.admin_data import AdminCustomerRead, AdminPaymentRead

router = APIRouter(prefix="/admin", tags=["administrator reports"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("/customers", response_model=list[AdminCustomerRead])
def list_customers(_admin: AdminUser, db: DbSession, query: Annotated[str | None, Query(max_length=100)] = None):
    order_count = select(func.count(Order.id)).where(Order.customer_id == User.id).scalar_subquery()
    statement = select(User, order_count.label("order_count")).where(User.role == UserRole.CUSTOMER.value)
    if query and query.strip():
        term = f"%{query.strip()}%"
        statement = statement.where(or_(User.full_name.ilike(term), User.email.ilike(term), User.phone.ilike(term)))
    rows = db.execute(statement.order_by(User.created_at.desc()).limit(100)).all()
    return [AdminCustomerRead(
        id=user.id, full_name=user.full_name, email=user.email, phone=user.phone,
        order_count=count, created_at=user.created_at,
    ) for user, count in rows]


@router.get("/payments", response_model=list[AdminPaymentRead])
def list_payments(_admin: AdminUser, db: DbSession):
    rows = db.scalars(select(Order).options(joinedload(Order.customer), joinedload(Order.payment_attempt))
        .order_by(Order.created_at.desc()).limit(200)).unique().all()
    return [AdminPaymentRead(
        order_number=order.order_number, customer_name=order.customer.full_name,
        customer_email=order.customer.email, payment_method=order.payment_method,
        payment_status=order.payment_status, order_status=order.status, amount=order.total,
        currency=order.currency,
        provider_order_id=order.payment_attempt.provider_order_id if order.payment_attempt else None,
        provider_payment_id=order.payment_attempt.provider_payment_id if order.payment_attempt else None,
        attempt_status=order.payment_attempt.status if order.payment_attempt else None,
        created_at=order.created_at, updated_at=order.updated_at,
    ) for order in rows]
