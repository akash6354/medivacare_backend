from app.core.config import get_settings
from .test_admin import create_cod_order, make_staff, register_customer

API_PREFIX = get_settings().api_v1_prefix


def test_admin_customer_and_payment_reports_show_saved_database_values(client, db_session, catalog_rows):
    order = create_cod_order(client, catalog_rows)
    _, admin_headers = make_staff(db_session)
    customer_headers = register_customer(client, email="directory@example.com", phone="+919876543227")
    assert customer_headers

    customers = client.get(f"{API_PREFIX}/admin/customers?query=orders%40example.com", headers=admin_headers)
    assert customers.status_code == 200
    assert len(customers.json()) == 1
    assert customers.json()[0]["email"] == "orders@example.com"
    assert customers.json()[0]["order_count"] == 1
    payments = client.get(f"{API_PREFIX}/admin/payments", headers=admin_headers)
    assert payments.status_code == 200
    row = next(item for item in payments.json() if item["order_number"] == order["order_number"])
    assert row["payment_method"] == "cod"
    assert row["payment_status"] == "pending"
    assert row["provider_order_id"] is None
    assert row["amount"] == order["total"]


def test_customer_cannot_read_admin_reports(client):
    headers = register_customer(client, email="reports@example.com", phone="+919876543228")
    assert client.get(f"{API_PREFIX}/admin/customers", headers=headers).status_code == 403
    assert client.get(f"{API_PREFIX}/admin/payments", headers=headers).status_code == 403
