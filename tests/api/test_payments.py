from datetime import UTC, datetime, timedelta
import json
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.models.catalog import Inventory
from app.models.orders import Order, PaymentAttempt

API_PREFIX = get_settings().api_v1_prefix
CUSTOMER = {
    "full_name": "Payment Demo Customer",
    "email": "payments@example.com",
    "phone": "+919876543230",
    "password": "correct-horse-battery",
}
ADDRESS = {
    "label": "Home",
    "recipient_name": "Payment Demo Customer",
    "phone": "+919876543230",
    "address_line1": "12 Example Road",
    "city": "Pune",
    "state": "Maharashtra",
    "postal_code": "411001",
    "country_code": "IN",
}


class FakeRazorpay:
    def __init__(self):
        self.orders = []
        self.payments = {}
        self.payment_rows = {}
        self.order = self.FakeOrders(self)
        self.payment = self.FakePayments(self)

    class FakeOrders:
        def __init__(self, parent):
            self.parent = parent

        def all(self, params):
            return {"items": [row for row in self.parent.orders if row["receipt"] == params["receipt"]]}

        def create(self, data):
            row = {**data, "id": f"order_fake_{len(self.parent.orders) + 1}"}
            self.parent.orders.append(row)
            return row

        def payments(self, provider_order_id):
            return {"items": self.parent.payment_rows.get(provider_order_id, [])}

    class FakePayments:
        def __init__(self, parent):
            self.parent = parent

        def fetch(self, payment_id):
            return self.parent.payments[payment_id]


def setup_customer(client, catalog_rows):
    registered = client.post(f"{API_PREFIX}/auth/register", json=CUSTOMER)
    assert registered.status_code == 201
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    address_response = client.post(f"{API_PREFIX}/customers/me/addresses", headers=headers, json=ADDRESS)
    assert address_response.status_code == 201
    added = client.put(
        f"{API_PREFIX}/cart/items",
        headers=headers,
        json={"product_id": str(catalog_rows["alpha"].id), "quantity": 2},
    )
    assert added.status_code == 200
    return headers, address_response.json()


def configure_fake_provider(monkeypatch, fake):
    import app.api.routes.payments as payment_routes

    monkeypatch.setattr(get_settings(), "razorpay_key_id", "rzp_test_fake")
    monkeypatch.setattr(payment_routes, "payment_credentials", lambda: ("rzp_test_fake", "test-secret"))
    monkeypatch.setattr(payment_routes, "razorpay_client", lambda: fake)
    monkeypatch.setattr(payment_routes, "webhook_signature_is_valid", lambda raw, signature: signature == "valid")


def create_online_order(client, headers, address, key="a14b8007-73bb-4a33-8216-13fa6e751589"):
    return client.post(
        f"{API_PREFIX}/payments/razorpay/create-order",
        headers={**headers, "Idempotency-Key": key},
        json={"address_id": address["id"]},
    )


def test_missing_payment_configuration_does_not_create_order_or_reserve_stock(
    client, db_session, catalog_rows, monkeypatch
):
    import app.api.routes.payments as payment_routes
    from fastapi import HTTPException

    headers, address = setup_customer(client, catalog_rows)
    def missing_credentials():
        raise HTTPException(status_code=503, detail="Razorpay test credentials are not configured correctly")

    monkeypatch.setattr(payment_routes, "payment_credentials", missing_credentials)
    response = create_online_order(client, headers, address)

    assert response.status_code == 503
    assert db_session.scalar(select(Order.id)) is None
    assert db_session.get(Inventory, catalog_rows["alpha"].id).available_quantity == 4
    assert client.get(f"{API_PREFIX}/cart", headers=headers).json()["item_count"] == 2


def test_create_order_uses_server_total_reserves_stock_and_is_idempotent(
    client, db_session, catalog_rows, monkeypatch
):
    fake = FakeRazorpay()
    configure_fake_provider(monkeypatch, fake)
    headers, address = setup_customer(client, catalog_rows)

    first = create_online_order(client, headers, address)
    retry = create_online_order(client, headers, address)
    cart = client.get(f"{API_PREFIX}/cart", headers=headers)
    inventory = db_session.get(Inventory, catalog_rows["alpha"].id)

    assert first.status_code == 201
    assert first.json()["amount"] == 19000
    assert first.json()["currency"] == "INR"
    assert first.json()["razorpay_order_id"] == "order_fake_1"
    assert retry.json()["order_number"] == first.json()["order_number"]
    assert len(fake.orders) == 1
    assert inventory.available_quantity == 2
    assert cart.json()["items"] == []
    order = db_session.scalar(select(Order).where(Order.order_number == first.json()["order_number"]))
    assert order.status == "pending_payment"
    assert order.payment_status == "pending"
    assert order.payment_attempt.amount_paise == 19000


def test_verify_rejects_bad_signature_and_mismatched_amount_then_marks_only_captured(
    client, db_session, catalog_rows, monkeypatch
):
    fake = FakeRazorpay()
    configure_fake_provider(monkeypatch, fake)
    headers, address = setup_customer(client, catalog_rows)
    checkout = create_online_order(client, headers, address).json()
    body = {
        "razorpay_order_id": checkout["razorpay_order_id"],
        "razorpay_payment_id": "pay_fake_12345678",
        "razorpay_signature": "signature" * 8,
    }

    import app.services.razorpay as razorpay_service
    monkeypatch.setattr(razorpay_service, "checkout_signature_is_valid", lambda *_args: False)
    invalid_signature = client.post(f"{API_PREFIX}/payments/razorpay/verify", headers=headers, json=body)
    assert invalid_signature.status_code == 400

    monkeypatch.setattr(razorpay_service, "checkout_signature_is_valid", lambda *_args: True)
    wrong_provider_order = client.post(
        f"{API_PREFIX}/payments/razorpay/verify",
        headers=headers,
        json={**body, "razorpay_order_id": "order_wrong_12345678"},
    )
    assert wrong_provider_order.status_code == 404

    fake.payments[body["razorpay_payment_id"]] = {
        "id": body["razorpay_payment_id"],
        "order_id": checkout["razorpay_order_id"],
        "amount": 18999,
        "currency": "INR",
        "status": "captured",
    }
    wrong_amount = client.post(f"{API_PREFIX}/payments/razorpay/verify", headers=headers, json=body)
    assert wrong_amount.status_code == 409

    fake.payments[body["razorpay_payment_id"]]["amount"] = checkout["amount"]
    fake.payments[body["razorpay_payment_id"]]["status"] = "failed"
    failed = client.post(f"{API_PREFIX}/payments/razorpay/verify", headers=headers, json=body)
    assert failed.status_code == 200
    assert failed.json()["payment_status"] == "failed"

    not_captured = dict(fake.payments[body["razorpay_payment_id"]], status="authorized")
    fake.payments[body["razorpay_payment_id"]] = not_captured
    authorized = client.post(f"{API_PREFIX}/payments/razorpay/verify", headers=headers, json=body)
    assert authorized.status_code == 200
    assert authorized.json()["payment_status"] == "authorized"
    assert authorized.json()["order_status"] == "pending_payment"

    fake.payments[body["razorpay_payment_id"]]["status"] = "captured"
    captured = client.post(f"{API_PREFIX}/payments/razorpay/verify", headers=headers, json=body)
    duplicate = client.post(f"{API_PREFIX}/payments/razorpay/verify", headers=headers, json=body)
    assert captured.json()["payment_status"] == "captured"
    assert captured.json()["order_status"] == "placed"
    assert duplicate.json()["payment_status"] == "captured"
    order = db_session.scalar(select(Order).where(Order.order_number == checkout["order_number"]))
    assert order.payment_status == "captured"


def test_webhook_signature_deduplication_and_out_of_order_failure(client, catalog_rows, monkeypatch):
    fake = FakeRazorpay()
    configure_fake_provider(monkeypatch, fake)
    headers, address = setup_customer(client, catalog_rows)
    checkout = create_online_order(client, headers, address).json()

    captured_event = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_fake_webhook",
                    "order_id": checkout["razorpay_order_id"],
                    "amount": checkout["amount"],
                    "currency": "INR",
                    "status": "captured",
                }
            }
        },
    }
    captured_body = json.dumps(captured_event).encode()
    captured_headers = {"X-Razorpay-Signature": "valid", "X-Razorpay-Event-Id": "evt-captured"}
    captured = client.post(f"{API_PREFIX}/webhooks/razorpay", content=captured_body, headers=captured_headers)
    duplicate = client.post(f"{API_PREFIX}/webhooks/razorpay", content=captured_body, headers=captured_headers)
    invalid_signature = client.post(
        f"{API_PREFIX}/webhooks/razorpay",
        content=captured_body,
        headers={"X-Razorpay-Signature": "invalid"},
    )

    failure_event = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_fake_webhook",
                    "order_id": checkout["razorpay_order_id"],
                    "amount": checkout["amount"],
                    "currency": "INR",
                    "status": "failed",
                }
            }
        },
    }
    out_of_order = client.post(
        f"{API_PREFIX}/webhooks/razorpay",
        content=json.dumps(failure_event),
        headers={"X-Razorpay-Signature": "valid", "X-Razorpay-Event-Id": "evt-failed-late"},
    )
    assert captured.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert invalid_signature.status_code == 400
    assert out_of_order.status_code == 200

    db_order = client.get(f"{API_PREFIX}/orders/{checkout['order_number']}", headers=headers).json()
    assert db_order["payment_status"] == "captured"


def test_expired_unpaid_order_releases_stock_after_provider_reconciliation(
    client, db_session, catalog_rows, monkeypatch
):
    fake = FakeRazorpay()
    configure_fake_provider(monkeypatch, fake)
    headers, address = setup_customer(client, catalog_rows)
    checkout = create_online_order(client, headers, address).json()
    attempt = db_session.get(PaymentAttempt, UUID(checkout["payment_attempt_id"]))
    attempt.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    status_response = client.get(
        f"{API_PREFIX}/payments/razorpay/{checkout['payment_attempt_id']}/status",
        headers=headers,
    )
    restored_cart = client.get(f"{API_PREFIX}/cart", headers=headers)
    inventory = db_session.get(Inventory, catalog_rows["alpha"].id)
    order = db_session.scalar(select(Order).where(Order.order_number == checkout["order_number"]))

    assert status_response.status_code == 200
    assert status_response.json()["order_status"] == "cancelled"
    assert attempt.status == "expired"
    assert inventory.available_quantity == 4
    assert order.status == "cancelled"
    assert restored_cart.json()["item_count"] == 2


def test_customer_cannot_read_another_customers_payment_attempt(client, catalog_rows, monkeypatch):
    fake = FakeRazorpay()
    configure_fake_provider(monkeypatch, fake)
    headers_a, address_a = setup_customer(client, catalog_rows)
    checkout = create_online_order(client, headers_a, address_a).json()
    other = client.post(
        f"{API_PREFIX}/auth/register",
        json={
            **CUSTOMER,
            "email": "other-payments@example.com",
            "phone": "+919876543231",
        },
    )
    headers_b = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = client.get(
        f"{API_PREFIX}/payments/razorpay/{checkout['payment_attempt_id']}/status",
        headers=headers_b,
    )
    assert response.status_code == 404
