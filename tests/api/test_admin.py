from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.models.audit import AdminAuditLog
from app.models.catalog import Inventory
from app.models.customer import User, UserRole
from app.models.orders import Order

API_PREFIX = get_settings().api_v1_prefix


def register_customer(client, *, email="orders@example.com", phone="+919876543220"):
    response = client.post(
        f"{API_PREFIX}/auth/register",
        json={
            "full_name": "Order Demo Customer",
            "email": email,
            "phone": phone,
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_staff(db_session, role="admin"):
    staff = User(
        full_name="Demo Administrator",
        email="admin@example.com",
        phone="+919876543229",
        password_hash=hash_password("admin-long-demo-password"),
        role=role,
        is_active=True,
    )
    db_session.add(staff)
    db_session.commit()
    token, _ = create_access_token(staff.id)
    return staff, {"Authorization": f"Bearer {token}"}


def create_cod_order(client, catalog_rows):
    customer_headers = register_customer(client)
    address = client.post(
        f"{API_PREFIX}/customers/me/addresses",
        headers=customer_headers,
        json={
            "label": "Home",
            "recipient_name": "Order Demo Customer",
            "phone": "+919876543220",
            "address_line1": "12 Example Road",
            "city": "Pune",
            "state": "Maharashtra",
            "postal_code": "411001",
            "country_code": "IN",
        },
    ).json()
    product = catalog_rows["alpha"]
    assert client.put(
        f"{API_PREFIX}/cart/items",
        headers=customer_headers,
        json={"product_id": str(product.id), "quantity": 2},
    ).status_code == 200
    response = client.post(
        f"{API_PREFIX}/orders",
        headers={**customer_headers, "Idempotency-Key": "ee0cf078-82cc-41e2-a474-3be34059b730"},
        json={"address_id": address["id"], "payment_method": "cod"},
    )
    assert response.status_code == 201
    return response.json()


def test_admin_orders_require_staff_and_show_saved_customer_details(client, db_session, catalog_rows):
    order = create_cod_order(client, catalog_rows)
    _, admin_headers = make_staff(db_session)

    anonymous = client.get(f"{API_PREFIX}/admin/orders")
    customer_headers = register_customer(
        client,
        email="another@example.com",
        phone="+919876543221",
    )
    forbidden = client.get(f"{API_PREFIX}/admin/orders", headers=customer_headers)
    result = client.get(
        f"{API_PREFIX}/admin/orders?query=orders%40example.com&status=placed",
        headers=admin_headers,
    )
    detail = client.get(f"{API_PREFIX}/admin/orders/{order['order_number']}", headers=admin_headers)

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403
    assert result.status_code == 200
    assert result.json()["total"] == 1
    listed = result.json()["items"][0]
    assert listed["order_number"] == order["order_number"]
    assert listed["customer_name"] == "Order Demo Customer"
    assert listed["customer_email"] == "orders@example.com"
    assert listed["customer_phone"] == "+919876543220"
    assert listed["recipient_phone"] == "+919876543220"
    assert listed["items"][0]["quantity"] == 2
    assert detail.json()["razorpay_order_id"] is None


def test_admin_status_transition_cancellation_restores_stock_and_audits(client, db_session, catalog_rows):
    order_data = create_cod_order(client, catalog_rows)
    staff, admin_headers = make_staff(db_session)
    inventory = db_session.get(Inventory, catalog_rows["alpha"].id)
    assert inventory.available_quantity == 2

    invalid = client.patch(
        f"{API_PREFIX}/admin/orders/{order_data['order_number']}/status",
        headers=admin_headers,
        json={"status": "delivered"},
    )
    cancelled = client.patch(
        f"{API_PREFIX}/admin/orders/{order_data['order_number']}/status",
        headers=admin_headers,
        json={"status": "cancelled"},
    )
    history = client.get(
        f"{API_PREFIX}/admin/orders/{order_data['order_number']}/history",
        headers=admin_headers,
    )

    assert invalid.status_code == 409
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert inventory.available_quantity == 4
    assert db_session.scalar(select(Order.status).where(Order.id == UUID(order_data["id"]))) == "cancelled"
    assert db_session.scalar(select(AdminAuditLog.actor_user_id)) == staff.id
    assert history.json()[0]["details"] == {"from": "placed", "to": "cancelled"}


def test_cod_collection_requires_delivery_and_is_recorded_separately(client, catalog_rows, db_session):
    order_data = create_cod_order(client, catalog_rows)
    _, admin_headers = make_staff(db_session)
    order_url = f"{API_PREFIX}/admin/orders/{order_data['order_number']}"

    too_early = client.post(f"{order_url}/cod-payment/collect", headers=admin_headers)
    assert too_early.status_code == 409
    for next_status in ("confirmed", "processing", "shipped", "out_for_delivery", "delivered"):
        updated = client.patch(
            f"{order_url}/status",
            headers=admin_headers,
            json={"status": next_status},
        )
        assert updated.status_code == 200

    collected = client.post(f"{order_url}/cod-payment/collect", headers=admin_headers)
    duplicate = client.post(f"{order_url}/cod-payment/collect", headers=admin_headers)
    history = client.get(f"{order_url}/history", headers=admin_headers)

    assert collected.status_code == 200
    assert collected.json()["status"] == "delivered"
    assert collected.json()["payment_status"] == "captured"
    assert duplicate.json()["payment_status"] == "captured"
    assert len([entry for entry in history.json() if entry["action"] == "cod.payment_collected"]) == 1


def test_support_role_cannot_read_administrator_orders(client, db_session):
    _, support_headers = make_staff(db_session, role=UserRole.SUPPORT.value)
    response = client.get(f"{API_PREFIX}/admin/orders", headers=support_headers)
    assert response.status_code == 403
