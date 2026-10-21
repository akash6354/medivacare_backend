from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.models.audit import AdminAuditLog
from app.models.delivery import Delivery
from .test_admin import create_cod_order, make_staff, register_customer

API_PREFIX = get_settings().api_v1_prefix


def test_delivery_assignment_updates_owned_customer_timeline_and_order_state(client, db_session, catalog_rows):
    order = create_cod_order(client, catalog_rows)
    staff, admin_headers = make_staff(db_session)
    order_url = f"{API_PREFIX}/admin/orders/{order['order_number']}"
    for status in ("confirmed", "processing"):
        response = client.patch(f"{order_url}/status", headers=admin_headers, json={"status": status})
        assert response.status_code == 200

    assignment = client.post(f"{order_url}/delivery", headers=admin_headers, json={
        "carrier_name": "Demo Express", "courier_name": "Alex Courier", "courier_phone": "+919876543222",
    })
    assert assignment.status_code == 201, assignment.text
    assert assignment.json()["status"] == "assigned"
    assert "courier_phone" not in assignment.json()
    assert assignment.json()["tracking_number"].startswith("MC-DL-")
    assert client.post(f"{order_url}/delivery", headers=admin_headers, json={
        "carrier_name": "Demo Express", "courier_name": "Alex Courier", "courier_phone": "+919876543222",
    }).status_code == 409

    customer = client.get(f"{API_PREFIX}/orders/{order['order_number']}", headers=register_customer(
        client, email="outsider@example.com", phone="+919876543221"
    ))
    assert customer.status_code == 404
    owner_headers = {"Authorization": "Bearer " + client.post(f"{API_PREFIX}/auth/login", json={
        "email": "orders@example.com", "password": "correct-horse-battery",
    }).json()["access_token"]}
    own_order = client.get(f"{API_PREFIX}/orders/{order['order_number']}", headers=owner_headers)
    assert own_order.status_code == 200
    assert own_order.json()["delivery"]["tracking_number"] == assignment.json()["tracking_number"]
    assert "courier_phone" not in own_order.json()["delivery"]

    for delivery_status, expected_order in (("picked_up", "shipped"), ("in_transit", "shipped"), ("out_for_delivery", "out_for_delivery"), ("delivered", "delivered")):
        updated = client.patch(f"{order_url}/delivery/status", headers=admin_headers, json={"status": delivery_status})
        assert updated.status_code == 200, updated.text
        detail = client.get(order_url, headers=admin_headers)
        assert detail.json()["status"] == expected_order

    assert db_session.scalar(select(Delivery).where(Delivery.order_id == UUID(order["id"]))).status == "delivered"
    actions = db_session.scalars(select(AdminAuditLog.action).where(AdminAuditLog.actor_user_id == staff.id)).all()
    assert "delivery.assigned" in actions
    assert actions.count("delivery.status_updated") == 4
    assert client.patch(f"{order_url}/delivery/status", headers=admin_headers, json={"status": "failed", "note": "late"}).status_code == 409


def test_only_admin_can_assign_delivery_and_failure_requires_note(client, db_session, catalog_rows):
    order = create_cod_order(client, catalog_rows)
    _, admin_headers = make_staff(db_session)
    order_url = f"{API_PREFIX}/admin/orders/{order['order_number']}"
    for status in ("confirmed", "processing"):
        client.patch(f"{order_url}/status", headers=admin_headers, json={"status": status})
    customer_headers = register_customer(client, email="ordinary@example.com", phone="+919876543223")
    assert client.post(f"{order_url}/delivery", headers=customer_headers, json={
        "carrier_name": "Demo Express", "courier_name": "Alex Courier", "courier_phone": "+919876543222",
    }).status_code == 403
    assigned = client.post(f"{order_url}/delivery", headers=admin_headers, json={
        "carrier_name": "Demo Express", "courier_name": "Alex Courier", "courier_phone": "+919876543222",
    })
    assert assigned.status_code == 201
    for status in ("picked_up", "in_transit"):
        assert client.patch(f"{order_url}/delivery/status", headers=admin_headers, json={"status": status}).status_code == 200
    assert client.patch(f"{order_url}/delivery/status", headers=admin_headers, json={"status": "failed"}).status_code == 422
