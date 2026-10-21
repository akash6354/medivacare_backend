from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models.customer import User
from app.models.orders import Order
from app.schemas.orders import CheckoutRequest, OrderPage, OrderRead
from app.services.checkout import create_order_from_cart, order_query, restore_order_stock

router = APIRouter(prefix="/orders", tags=["orders"])


def _order_query():
    return order_query()


def _owned_order(db: DbSession, user: User, order_number: str) -> Order:
    order = db.scalars(
        _order_query().where(Order.customer_id == user.id, Order.order_number == order_number)
    ).unique().one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def create_cod_order(
    body: CheckoutRequest,
    user: CurrentUser,
    db: DbSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> OrderRead:
    return create_order_from_cart(db, user, body.address_id, str(idempotency_key), "cod")


@router.get("", response_model=OrderPage)
def list_orders(
    user: CurrentUser,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> OrderPage:
    count = db.scalar(select(func.count()).select_from(Order).where(Order.customer_id == user.id)) or 0
    orders = db.scalars(
        _order_query()
        .where(Order.customer_id == user.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()
    return OrderPage(items=orders, total=count, page=page, page_size=page_size)


@router.get("/{order_number}", response_model=OrderRead)
def get_order(order_number: str, user: CurrentUser, db: DbSession) -> OrderRead:
    return _owned_order(db, user, order_number)


@router.patch("/{order_number}/cancel", response_model=OrderRead)
def cancel_cod_order(order_number: str, user: CurrentUser, db: DbSession) -> OrderRead:
    order = db.scalars(
        _order_query()
        .where(Order.customer_id == user.id, Order.order_number == order_number)
        .with_for_update()
    ).unique().one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status == "cancelled":
        return order
    if order.status != "placed" or order.payment_method != "cod":
        raise HTTPException(status_code=409, detail="This order can no longer be cancelled from your account")

    restore_order_stock(db, order)
    order.status = "cancelled"
    db.commit()
    return db.scalars(_order_query().where(Order.id == order.id)).unique().one()
