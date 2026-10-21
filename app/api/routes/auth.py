from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import limiter
from app.core.security import (
    AuthenticationConfigurationError,
    create_access_token,
    get_signing_key,
    hash_password,
    verify_password,
)
from app.models.customer import User, UserRole
from app.schemas.customer import AuthResponse, CustomerRead, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["authentication"])


def _customer_read(user: User) -> CustomerRead:
    return CustomerRead(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        created_at=user.created_at,
    )


def _auth_response(user: User) -> AuthResponse:
    try:
        token, expires_in = create_access_token(user.id)
    except AuthenticationConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return AuthResponse(access_token=token, expires_in=expires_in, customer=_customer_read(user))


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, response: Response, body: RegisterRequest, db: DbSession) -> AuthResponse:
    try:
        get_signing_key()
    except AuthenticationConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    existing_user = db.scalar(
        select(User.id).where(or_(User.email == str(body.email), User.phone == body.phone))
    )
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="An account already uses that email or phone number")

    user = User(
        full_name=body.full_name,
        email=str(body.email),
        phone=body.phone,
        password_hash=hash_password(body.password),
        role=UserRole.CUSTOMER.value,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account already uses that email or phone number") from error
    return _auth_response(user)


@router.post("/login", response_model=AuthResponse)
@limiter.limit("5/minute")
def login(request: Request, response: Response, body: LoginRequest, db: DbSession) -> AuthResponse:
    try:
        get_signing_key()
    except AuthenticationConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    user = db.scalar(select(User).where(User.email == str(body.email)))
    valid_password = verify_password(body.password, user.password_hash if user else None)
    if user is None or not valid_password or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Email or password is incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _auth_response(user)


@router.get("/me", response_model=CustomerRead)
def get_authenticated_customer(user: CurrentUser) -> CustomerRead:
    return _customer_read(user)
