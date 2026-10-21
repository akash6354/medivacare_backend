"""Create an administrator account without placing credentials in source control."""
import getpass
import re

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import or_, select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.customer import User, UserRole

PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


def main() -> None:
    name = input("Administrator name: ").strip()
    email_input = input("Administrator email: ").strip()
    phone = input("Phone in international format (for example +919876543210): ").strip()
    password = getpass.getpass("Password (at least 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")

    if not name or len(name) > 120:
        raise SystemExit("Name must contain 1 to 120 characters.")
    if not PHONE_PATTERN.fullmatch(phone):
        raise SystemExit("Phone must use international format, such as +919876543210.")
    try:
        email = str(TypeAdapter(EmailStr).validate_python(email_input)).lower()
    except ValidationError as error:
        raise SystemExit("Enter a valid email address.") from error
    if len(password) < 12 or len(password) > 128 or not password.strip():
        raise SystemExit("Password must contain 12 to 128 nonblank characters.")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    with SessionLocal() as db:
        exists = db.scalar(
            select(User.id).where(or_(User.email == email, User.phone == phone))
        )
        if exists is not None:
            raise SystemExit("An account already uses that email or phone. No role was changed.")
        admin = User(
            full_name=name,
            email=email,
            phone=phone,
            password_hash=hash_password(password),
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        db.add(admin)
        db.commit()
    print(f"Administrator account created for {email}.")


if __name__ == "__main__":
    main()
