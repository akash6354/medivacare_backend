from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.models.customer import Address, User
from app.schemas.customer import AddressCreate, AddressRead, AddressUpdate, CustomerRead, CustomerUpdate

router = APIRouter(prefix="/customers/me", tags=["customers"])


def _customer_read(user: User) -> CustomerRead:
    return CustomerRead(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        created_at=user.created_at,
    )


@router.get("", response_model=CustomerRead)
def get_profile(user: CurrentUser) -> CustomerRead:
    return _customer_read(user)


@router.patch("", response_model=CustomerRead)
def update_profile(body: CustomerUpdate, user: CurrentUser, db: DbSession) -> CustomerRead:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return _customer_read(user)
    for field, value in changes.items():
        setattr(user, field, value)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="That phone number is already used by another account") from error
    return _customer_read(user)


@router.get("/addresses", response_model=list[AddressRead])
def list_addresses(user: CurrentUser, db: DbSession) -> list[Address]:
    statement = (
        select(Address)
        .where(Address.customer_id == user.id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
    )
    return list(db.scalars(statement).all())


@router.post("/addresses", response_model=AddressRead, status_code=status.HTTP_201_CREATED)
def create_address(body: AddressCreate, user: CurrentUser, db: DbSession) -> Address:
    address_count = db.scalar(
        select(func.count()).select_from(Address).where(Address.customer_id == user.id)
    ) or 0
    should_be_default = body.is_default or address_count == 0
    if should_be_default:
        db.execute(update(Address).where(Address.customer_id == user.id).values(is_default=False))

    values = body.model_dump(exclude={"is_default"})
    address = Address(customer_id=user.id, **values, is_default=should_be_default)
    db.add(address)
    try:
        db.commit()
        db.refresh(address)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to save this address") from error
    return address


def _owned_address(db: Session, user_id: UUID, address_id: UUID) -> Address:
    address = db.scalar(
        select(Address).where(Address.id == address_id, Address.customer_id == user_id)
    )
    if address is None:
        raise HTTPException(status_code=404, detail="Address not found")
    return address


@router.patch("/addresses/{address_id}", response_model=AddressRead)
def update_address(
    address_id: UUID, body: AddressUpdate, user: CurrentUser, db: DbSession
) -> Address:
    address = _owned_address(db, user.id, address_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return address

    requested_default = changes.pop("is_default", None)
    if requested_default is True:
        db.execute(
            update(Address)
            .where(Address.customer_id == user.id, Address.id != address.id)
            .values(is_default=False)
        )
        address.is_default = True
    elif requested_default is False and address.is_default:
        address.is_default = False
        db.flush()
        replacement = db.scalar(
            select(Address)
            .where(Address.customer_id == user.id, Address.id != address.id)
            .order_by(Address.created_at.asc(), Address.id.asc())
        )
        if replacement is None:
            address.is_default = True
        else:
            replacement.is_default = True

    for field, value in changes.items():
        setattr(address, field, value)
    try:
        db.commit()
        db.refresh(address)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to update this address") from error
    return address


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(address_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    address = _owned_address(db, user.id, address_id)
    was_default = address.is_default
    db.delete(address)
    db.flush()
    if was_default:
        replacement = db.scalar(
            select(Address)
            .where(Address.customer_id == user.id)
            .order_by(Address.created_at.asc(), Address.id.asc())
        )
        if replacement is not None:
            replacement.is_default = True
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
