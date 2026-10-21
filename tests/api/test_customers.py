from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import verify_password
from app.models.customer import User, UserRole

API_PREFIX = get_settings().api_v1_prefix

CUSTOMER = {
    "full_name": "Demo Customer",
    "email": "customer@example.com",
    "phone": "+919876543210",
    "password": "correct-horse-battery",
}

ADDRESS = {
    "label": "Home",
    "recipient_name": "Demo Customer",
    "phone": "+919876543210",
    "address_line1": "12 Example Road",
    "city": "Pune",
    "state": "Maharashtra",
    "postal_code": "411001",
    "country_code": "IN",
}


def register(client, **overrides):
    payload = {**CUSTOMER, **overrides}
    return client.post(f"{API_PREFIX}/auth/register", json=payload)


def bearer(response):
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_registration_hashes_password_and_ignores_supplied_role(client, db_session):
    response = register(client, role="admin")

    assert response.status_code == 201
    user = db_session.scalar(select(User).where(User.email == CUSTOMER["email"]))
    assert user is not None
    assert user.role == UserRole.CUSTOMER.value
    assert user.password_hash != CUSTOMER["password"]
    assert verify_password(CUSTOMER["password"], user.password_hash)
    assert "password_hash" not in response.json()["customer"]


def test_registration_validates_password_phone_and_duplicate_accounts(client):
    weak_password = register(client, password="short")
    invalid_phone = register(client, phone="555-1234")
    assert weak_password.status_code == 422
    assert invalid_phone.status_code == 422

    assert register(client).status_code == 201
    assert register(client).status_code == 409


def test_authentication_is_unavailable_without_a_signing_secret(client, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "secret_key", SecretStr(""))
    response = register(client)

    assert response.status_code == 503
    assert "SECRET_KEY" in response.json()["detail"]


def test_login_returns_bearer_token_and_rejects_invalid_password(client):
    assert register(client).status_code == 201

    successful_login = client.post(
        f"{API_PREFIX}/auth/login",
        json={"email": CUSTOMER["email"], "password": CUSTOMER["password"]},
    )
    failed_login = client.post(
        f"{API_PREFIX}/auth/login",
        json={"email": CUSTOMER["email"], "password": "incorrect-password"},
    )

    assert successful_login.status_code == 200
    assert successful_login.json()["token_type"] == "bearer"
    assert successful_login.json()["expires_in"] > 0
    assert failed_login.status_code == 401
    assert "access_token" not in failed_login.json()


def test_profile_requires_authentication_and_only_updates_current_customer(client):
    unauthenticated = client.get(f"{API_PREFIX}/customers/me")
    registered = register(client)
    headers = bearer(registered)
    profile = client.get(f"{API_PREFIX}/customers/me", headers=headers)
    updated = client.patch(
        f"{API_PREFIX}/customers/me",
        headers=headers,
        json={"full_name": "Updated Demo Customer"},
    )

    assert unauthenticated.status_code == 401
    assert profile.status_code == 200
    assert profile.json()["email"] == CUSTOMER["email"]
    assert updated.json()["full_name"] == "Updated Demo Customer"


def test_address_crud_maintains_one_default_address(client):
    registered = register(client)
    headers = bearer(registered)
    first = client.post(f"{API_PREFIX}/customers/me/addresses", headers=headers, json=ADDRESS)
    second = client.post(
        f"{API_PREFIX}/customers/me/addresses",
        headers=headers,
        json={**ADDRESS, "label": "Work", "address_line1": "45 Sample Avenue"},
    )
    assert first.status_code == 201
    assert first.json()["is_default"] is True
    assert second.status_code == 201
    assert second.json()["is_default"] is False

    changed = client.patch(
        f"{API_PREFIX}/customers/me/addresses/{second.json()['id']}",
        headers=headers,
        json={"is_default": True},
    )
    addresses = client.get(f"{API_PREFIX}/customers/me/addresses", headers=headers).json()
    assert changed.status_code == 200
    assert sum(address["is_default"] for address in addresses) == 1
    assert next(address for address in addresses if address["is_default"])["id"] == second.json()["id"]

    deleted = client.delete(
        f"{API_PREFIX}/customers/me/addresses/{second.json()['id']}", headers=headers
    )
    addresses_after_delete = client.get(f"{API_PREFIX}/customers/me/addresses", headers=headers).json()
    assert deleted.status_code == 204
    assert len(addresses_after_delete) == 1
    assert addresses_after_delete[0]["is_default"] is True


def test_customer_cannot_read_or_change_another_customers_address(client):
    customer_a = register(client)
    customer_b = register(
        client,
        full_name="Second Demo Customer",
        email="second@example.com",
        phone="+919876543211",
    )
    created_address = client.post(
        f"{API_PREFIX}/customers/me/addresses", headers=bearer(customer_a), json=ADDRESS
    )

    unauthorized_update = client.patch(
        f"{API_PREFIX}/customers/me/addresses/{created_address.json()['id']}",
        headers=bearer(customer_b),
        json={"city": "Mumbai"},
    )
    unauthorized_delete = client.delete(
        f"{API_PREFIX}/customers/me/addresses/{created_address.json()['id']}",
        headers=bearer(customer_b),
    )

    assert unauthorized_update.status_code == 404
    assert unauthorized_delete.status_code == 404


def test_address_rejects_invalid_phone_and_postal_code(client):
    registered = register(client)
    bad_phone = client.post(
        f"{API_PREFIX}/customers/me/addresses",
        headers=bearer(registered),
        json={**ADDRESS, "phone": "not-a-phone"},
    )
    bad_postal_code = client.post(
        f"{API_PREFIX}/customers/me/addresses",
        headers=bearer(registered),
        json={**ADDRESS, "postal_code": "123"},
    )

    assert bad_phone.status_code == 422
    assert bad_postal_code.status_code == 422
