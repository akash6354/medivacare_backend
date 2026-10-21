from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.models.support import SupportTicket
from .test_admin import make_staff, register_customer

API_PREFIX = get_settings().api_v1_prefix


def test_customer_ticket_is_private_and_support_staff_can_update_it(client, db_session):
    owner_headers = register_customer(client, email="support-owner@example.com", phone="+919876543224")
    other_headers = register_customer(client, email="support-other@example.com", phone="+919876543225")
    created = client.post(f"{API_PREFIX}/support/tickets", headers=owner_headers, json={
        "subject": "Question about an order", "message": "Please explain the delivery status for my order.",
    })
    assert created.status_code == 201, created.text
    assert len(client.get(f"{API_PREFIX}/support/tickets", headers=owner_headers).json()) == 1
    assert client.get(f"{API_PREFIX}/support/tickets", headers=other_headers).json() == []
    assert client.get(f"{API_PREFIX}/admin/support/tickets", headers=other_headers).status_code == 403

    staff, staff_headers = make_staff(db_session, role="support")
    rows = client.get(f"{API_PREFIX}/admin/support/tickets", headers=staff_headers)
    assert rows.status_code == 200
    assert rows.json()[0]["customer_email"] == "support-owner@example.com"
    updated = client.patch(f"{API_PREFIX}/admin/support/tickets/{created.json()['id']}", headers=staff_headers, json={
        "status": "in_progress", "staff_note": "We are reviewing this request.",
    })
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"
    assert updated.json()["staff_note"] == "We are reviewing this request."
    owner_view = client.get(f"{API_PREFIX}/support/tickets", headers=owner_headers).json()[0]
    assert owner_view["staff_note"] == "We are reviewing this request."
    row = db_session.scalar(select(SupportTicket).where(SupportTicket.id == UUID(created.json()["id"])))
    assert row.handled_by_user_id == staff.id


def test_support_ticket_requires_valid_content_and_staff_role(client):
    headers = register_customer(client, email="support-valid@example.com", phone="+919876543226")
    short = client.post(f"{API_PREFIX}/support/tickets", headers=headers, json={"subject": "Help", "message": "Short"})
    assert short.status_code == 422
    unauthenticated = client.get(f"{API_PREFIX}/support/tickets")
    assert unauthenticated.status_code == 401
