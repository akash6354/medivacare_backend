from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.models.catalog import Inventory
from app.models.customer import User
from app.models.orders import OrderItem
from app.models.prescriptions import PrescriptionReviewAudit

API_PREFIX = get_settings().api_v1_prefix
PDF_BYTES = b"%PDF-1.7 synthetic test document"


def register(client, *, name="Prescription Customer", email="rx-customer@example.com", phone="+919876543240"):
    response = client.post(
        f"{API_PREFIX}/auth/register",
        json={"full_name": name, "email": email, "phone": phone, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_staff(db_session, role="pharmacist"):
    staff = User(
        full_name="Demo Pharmacy Staff",
        email=f"{role}-staff@example.com",
        phone="+919876543249" if role == "pharmacist" else "+919876543248",
        password_hash=hash_password("staff-long-demo-password"),
        role=role,
        is_active=True,
    )
    db_session.add(staff)
    db_session.commit()
    token, _ = create_access_token(staff.id)
    return staff, {"Authorization": f"Bearer {token}"}


def upload(client, headers, product_id, content=PDF_BYTES, media_type="application/pdf", filename="../../private.pdf"):
    return client.post(
        f"{API_PREFIX}/prescriptions",
        headers=headers,
        data={"product_id": str(product_id)},
        files={"file": (filename, content, media_type)},
    )


def test_private_upload_checks_signature_ownership_and_allowed_staff_access(
    client, db_session, catalog_rows, monkeypatch, tmp_path
):
    monkeypatch.setattr(get_settings(), "prescription_storage_path", tmp_path)
    customer_headers = register(client)
    upload_response = upload(client, customer_headers, catalog_rows["beta"].id)
    assert upload_response.status_code == 201
    prescription = upload_response.json()
    stored_files = list(tmp_path.iterdir())

    own_file = client.get(f"{API_PREFIX}/prescriptions/{prescription['id']}/file", headers=customer_headers)
    other_customer = register(
        client,
        name="Other Customer",
        email="other-rx@example.com",
        phone="+919876543241",
    )
    forbidden_file = client.get(f"{API_PREFIX}/prescriptions/{prescription['id']}/file", headers=other_customer)
    invalid_signature = upload(client, customer_headers, catalog_rows["beta"].id, b"not a PDF")
    oversized = upload(
        client,
        customer_headers,
        catalog_rows["beta"].id,
        b"%PDF-1.7" + b"x" * (5 * 1024 * 1024),
    )
    unflagged_product = upload(client, customer_headers, catalog_rows["alpha"].id)
    pharmacist, pharmacist_headers = make_staff(db_session)
    staff_file = client.get(f"{API_PREFIX}/prescriptions/{prescription['id']}/file", headers=pharmacist_headers)
    staff_queue = client.get(f"{API_PREFIX}/admin/prescriptions?status=pending", headers=pharmacist_headers)
    _, support_headers = make_staff(db_session, role="support")
    support_queue = client.get(f"{API_PREFIX}/admin/prescriptions", headers=support_headers)

    assert prescription["status"] == "pending"
    assert "storage_key" not in prescription
    assert len(stored_files) == 1 and stored_files[0].name.endswith(".pdf")
    assert own_file.status_code == 200 and own_file.content == PDF_BYTES
    assert own_file.headers["cache-control"] == "no-store, private"
    assert forbidden_file.status_code == 404
    assert invalid_signature.status_code == 422
    assert oversized.status_code == 422
    assert unflagged_product.status_code == 404
    assert staff_file.status_code == 200 and staff_file.content == PDF_BYTES
    assert staff_queue.json()["items"][0]["customer_name"] == "Prescription Customer"
    assert support_queue.status_code == 403


def test_review_is_audited_and_checkout_requires_linked_approval(
    client, db_session, catalog_rows, monkeypatch, tmp_path
):
    monkeypatch.setattr(get_settings(), "prescription_storage_path", tmp_path)
    inventory = db_session.get(Inventory, catalog_rows["beta"].id)
    inventory.available_quantity = 2
    db_session.commit()
    customer_headers = register(client)
    address = client.post(
        f"{API_PREFIX}/customers/me/addresses",
        headers=customer_headers,
        json={
            "label": "Home",
            "recipient_name": "Prescription Customer",
            "phone": "+919876543240",
            "address_line1": "12 Example Road",
            "city": "Pune",
            "state": "Maharashtra",
            "postal_code": "411001",
            "country_code": "IN",
        },
    ).json()
    prescription_response = upload(client, customer_headers, catalog_rows["beta"].id)
    prescription_id = prescription_response.json()["id"]
    assert client.put(
        f"{API_PREFIX}/cart/items",
        headers=customer_headers,
        json={"product_id": str(catalog_rows["beta"].id), "quantity": 1},
    ).status_code == 200
    blocked = client.post(
        f"{API_PREFIX}/orders",
        headers={**customer_headers, "Idempotency-Key": str(uuid4())},
        json={"address_id": address["id"], "payment_method": "cod"},
    )
    assert blocked.status_code == 409
    assert "approved prescription" in blocked.json()["detail"]

    staff, pharmacist_headers = make_staff(db_session, role="admin")
    reject_without_note = client.patch(
        f"{API_PREFIX}/admin/prescriptions/{prescription_id}/review",
        headers=pharmacist_headers,
        json={"status": "rejected", "note": "  "},
    )
    approved = client.patch(
        f"{API_PREFIX}/admin/prescriptions/{prescription_id}/review",
        headers=pharmacist_headers,
        json={"status": "approved"},
    )
    listed = client.get(f"{API_PREFIX}/prescriptions?product_id={catalog_rows['beta'].id}", headers=customer_headers)
    review_history = client.get(
        f"{API_PREFIX}/admin/prescriptions/{prescription_id}/history", headers=pharmacist_headers
    )
    cart = client.get(f"{API_PREFIX}/cart", headers=customer_headers)
    order = client.post(
        f"{API_PREFIX}/orders",
        headers={**customer_headers, "Idempotency-Key": str(uuid4())},
        json={"address_id": address["id"], "payment_method": "cod"},
    )
    audits = db_session.scalars(
        select(PrescriptionReviewAudit).where(PrescriptionReviewAudit.prescription_id == UUID(prescription_id))
    ).all()
    saved_item = db_session.scalar(select(OrderItem).where(OrderItem.order_id == UUID(order.json()["id"])))

    assert reject_without_note.status_code == 422
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert review_history.status_code == 200
    assert review_history.json()[0]["status"] == "approved"
    assert review_history.json()[0]["reviewer_name"] == staff.full_name
    assert listed.json()[0]["status"] == "approved"
    assert cart.json()["items"][0]["prescription_approved"] is True
    assert order.status_code == 201
    assert order.json()["items"][0]["prescription_id"] == prescription_id
    assert saved_item.prescription_id.hex == prescription_id.replace("-", "")
    assert len(audits) == 1 and audits[0].reviewer_user_id == staff.id

    client.patch(
        f"{API_PREFIX}/admin/prescriptions/{prescription_id}/review",
        headers=pharmacist_headers,
        json={"status": "rejected", "note": "The submitted example is incomplete."},
    )
    confirmed = client.patch(
        f"{API_PREFIX}/admin/orders/{order.json()['order_number']}/status",
        headers=pharmacist_headers,
        json={"status": "confirmed"},
    )
    blocked_fulfillment = client.patch(
        f"{API_PREFIX}/admin/orders/{order.json()['order_number']}/status",
        headers=pharmacist_headers,
        json={"status": "processing"},
    )
    assert confirmed.status_code == 200
    assert blocked_fulfillment.status_code == 409
