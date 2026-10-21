from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationInfo, field_validator

PHONE_PATTERN = r"^\+[1-9]\d{7,14}$"
INDIA_POSTAL_PATTERN = r"^[1-9]\d{5}$"


class CustomerRead(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    phone: str
    role: str
    created_at: datetime


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(pattern=PHONE_PATTERN, min_length=8, max_length=16)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return value.strip()

    @field_validator("password")
    @classmethod
    def require_nonblank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot be blank")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class CustomerUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN, min_length=8, max_length=16)

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Name cannot be null")
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Phone cannot be null")
        return value.strip()


class AddressFields(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    recipient_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(pattern=PHONE_PATTERN, min_length=8, max_length=16)
    address_line1: str = Field(min_length=3, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(pattern=INDIA_POSTAL_PATTERN, min_length=6, max_length=6)
    country_code: Literal["IN"] = "IN"

    @field_validator("label", "recipient_name", "address_line1", "address_line2", "city", "state")
    @classmethod
    def trim_address_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value and info.field_name == "address_line2":
            return None
        if not value:
            raise ValueError("Address fields cannot be blank")
        return value

    @field_validator("phone")
    @classmethod
    def normalize_address_phone(cls, value: str) -> str:
        return value.strip()

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str) -> str:
        return value.upper()

    @field_validator("postal_code")
    @classmethod
    def normalize_postal_code(cls, value: str) -> str:
        return value.strip()


class AddressCreate(AddressFields):
    is_default: bool = False


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=40)
    recipient_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN, min_length=8, max_length=16)
    address_line1: str | None = Field(default=None, min_length=3, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = Field(default=None, min_length=1, max_length=100)
    postal_code: str | None = Field(default=None, pattern=INDIA_POSTAL_PATTERN, min_length=6, max_length=6)
    country_code: Literal["IN"] | None = None
    is_default: bool | None = None

    @field_validator(
        "label",
        "recipient_name",
        "phone",
        "address_line1",
        "city",
        "state",
        "postal_code",
        "country_code",
        "is_default",
    )
    @classmethod
    def reject_null_for_required_patch_fields(cls, value):
        if value is None:
            raise ValueError("This field cannot be null")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("This field cannot be blank")
        return value.upper() if isinstance(value, str) and len(value) == 2 else value


class AddressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    recipient_name: str
    phone: str
    address_line1: str
    address_line2: str | None
    city: str
    state: str
    postal_code: str
    country_code: str
    is_default: bool
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    customer: CustomerRead
