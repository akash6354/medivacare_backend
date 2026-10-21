from sqlalchemy import select

from app.core.config import get_settings
from app.models.catalog import Inventory
from app.models.orders import CartItem, Order

API_PREFIX = get_settings().api_v1_prefix

CUSTOMER = {
    "full_name": "Order Demo Customer",
    "email": "orders@example.com",
    "phone": "+919876543220",
    "password": "correct-horse-battery",
}

ADDRESS = {
    "label": "Home",
    "recipient_name": "Order Demo Customer",
    "phone": "+919876543220",
    "address_line1": "12 Example Road",
    "city": "Pune",
    "state": "Maharashtra",
    "postal_code": "411001",
    "country_code": "IN",
}


def register(client, **overrides):
    response = client.post(f"{API_PREFIX}/auth/register", json={**CUSTOMER, **overrides})
    assert response.status_code == 201
    return response


def headers_for(response):
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_address(client, headers):
    response = client.post(f"{API_PREFIX}/customers/me/addresses", headers=headers, json=ADDRESS)
    assert response.status_code == 201
    return response.json()


def add_to_cart(client, headers, product, quantity=1):
    return client.put(
        f"{API_PREFIX}/cart/items",
        headers=headers,
        json={"product_id": str(product.id), "quantity": quantity},
    )


def checkout(client, headers, address_id, key="7bc5675e-d459-4d9a-92ba-ec21d77418ad", **extra):
    return client.post(
        f"{API_PREFIX}/orders",
        headers={**headers, "Idempotency-Key": key},
        json={"address_id": str(address_id), "payment_method": "cod", **extra},
    )


def test_cart_requires_authentication_and_enforces_stock(client, catalog_rows):
    unauthenticated = client.get(f"{API_PREFIX}/cart")
    registered = register(client)
    headers = headers_for(registered)
    empty = client.get(f"{API_PREFIX}/cart", headers=headers)
    added = add_to_cart(client, headers, catalog_rows["alpha"], quantity=2)
    excessive = add_to_cart(client, headers, catalog_rows["alpha"], quantity=5)
    inactive = add_to_cart(client, headers, catalog_rows["inactive"])

    assert unauthenticated.status_code == 401
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert added.status_code == 200
    assert added.json()["item_count"] == 2
    assert added.json()["subtotal"] == "150.00"
    assert excessive.status_code == 409
    assert inactive.status_code == 404


def test_cod_checkout_uses_database_prices_snapshots_and_idempotency(client, db_session, catalog_rows):
    registered = register(client)
    headers = headers_for(registered)
    address = create_address(client, headers)
    assert add_to_cart(client, headers, catalog_rows["alpha"], quantity=2).status_code == 200

    first = checkout(
        client,
        headers,
        address["id"],
        subtotal="0.01",
        delivery_fee="0.00",
        total="0.01",
    )
    retry = checkout(client, headers, address["id"])
    cart_after_checkout = client.get(f"{API_PREFIX}/cart", headers=headers)
    inventory_after_checkout = db_session.get(Inventory, catalog_rows["alpha"].id)

    assert first.status_code == 201
    assert first.json()["status"] == "placed"
    assert first.json()["payment_method"] == "cod"
    assert first.json()["payment_status"] == "pending"
    assert first.json()["subtotal"] == "150.00"
    assert first.json()["delivery_fee"] == str(get_settings().delivery_fee)
    assert first.json()["total"] == str(get_settings().delivery_fee + 150)
    assert first.json()["items"][0]["unit_price"] == "75.00"
    assert first.json()["items"][0]["quantity"] == 2
    assert retry.json()["order_number"] == first.json()["order_number"]
    assert cart_after_checkout.json()["items"] == []
    assert inventory_after_checkout.available_quantity == 2
    assert db_session.scalar(select(Order.id).where(Order.order_number == first.json()["order_number"])) is not None
    assert db_session.scalar(select(CartItem.product_id)) is None


def test_customers_only_see_their_own_orders(client, catalog_rows):
    customer_a = register(client)
    headers_a = headers_for(customer_a)
    address = create_address(client, headers_a)
    assert add_to_cart(client, headers_a, catalog_rows["alpha"]).status_code == 200
    order = checkout(client, headers_a, address["id"]).json()

    customer_b = register(
        client,
        full_name="Another Customer",
        email="another@example.com",
        phone="+919876543221",
    )
    headers_b = headers_for(customer_b)
    order_detail = client.get(f"{API_PREFIX}/orders/{order['order_number']}", headers=headers_b)
    order_list = client.get(f"{API_PREFIX}/orders", headers=headers_b)

    assert order_detail.status_code == 404
    assert order_list.status_code == 200
    assert order_list.json()["items"] == []


def test_customer_can_cancel_unprocessed_cod_order_and_restore_stock(client, db_session, catalog_rows):
    registered = register(client)
    headers = headers_for(registered)
    address = create_address(client, headers)
    assert add_to_cart(client, headers, catalog_rows["alpha"], quantity=2).status_code == 200
    order = checkout(client, headers, address["id"]).json()
    inventory = db_session.get(Inventory, catalog_rows["alpha"].id)
    assert inventory.available_quantity == 2

    cancelled = client.patch(f"{API_PREFIX}/orders/{order['order_number']}/cancel", headers=headers)
    retried_cancel = client.patch(f"{API_PREFIX}/orders/{order['order_number']}/cancel", headers=headers)

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert retried_cancel.json()["status"] == "cancelled"
    assert inventory.available_quantity == 4


def test_checkout_blocks_unavailable_prescription_items_and_keeps_cart(client, db_session, catalog_rows):
    registered = register(client)
    headers = headers_for(registered)
    address = create_address(client, headers)
    inventory = catalog_rows["beta"].inventory
    inventory.available_quantity = 2
    db_session.commit()
    added = add_to_cart(client, headers, catalog_rows["beta"])

    response = checkout(client, headers, address["id"])
    still_in_cart = client.get(f"{API_PREFIX}/cart", headers=headers)

    assert added.status_code == 200
    assert response.status_code == 409
    assert "approved prescription" in response.json()["detail"]
    assert still_in_cart.json()["item_count"] == 1
    assert db_session.get(Inventory, catalog_rows["beta"].id).available_quantity == 2


def test_order_history_requires_auth_and_address_must_be_owned(client, catalog_rows):
    unauthenticated = client.get(f"{API_PREFIX}/orders")
    customer_a = register(client)
    customer_b = register(
        client,
        full_name="Another Customer",
        email="another@example.com",
        phone="+919876543221",
    )
    headers_a = headers_for(customer_a)
    headers_b = headers_for(customer_b)
    address = create_address(client, headers_a)
    assert add_to_cart(client, headers_b, catalog_rows["alpha"]).status_code == 200

    response = checkout(client, headers_b, address["id"])

    assert unauthenticated.status_code == 401
    assert response.status_code == 404
