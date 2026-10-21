from app.core.config import get_settings
from .test_admin import make_staff

API_PREFIX = get_settings().api_v1_prefix


def test_admin_can_create_update_and_deactivate_catalog_products(client, db_session, catalog_rows):
    _, admin_headers = make_staff(db_session)
    category_id = str(catalog_rows["alpha"].category_id)
    body = {
        "name": "Demo Product Gamma", "sku": "DEMO-GAMMA", "category_id": category_id,
        "description": "Fictional college project listing.", "dosage_form": "Tablet",
        "manufacturer": "Example Labs", "pack_quantity": 10, "pack_unit": "tablets",
        "mrp": "50.00", "selling_price": "40.00", "stock_quantity": 8,
        "low_stock_threshold": 3,
        "ingredients": [{"name": "Sample Active Gamma", "strength_amount": "25", "strength_unit": "mg"}],
    }
    created = client.post(f"{API_PREFIX}/admin/catalog/products", headers=admin_headers, json=body)
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["slug"] == "demo-product-gamma"
    assert item["stock_quantity"] == 8
    assert item["active_ingredients"][0]["name"] == "Sample Active Gamma"
    assert client.post(f"{API_PREFIX}/admin/catalog/products", headers=admin_headers, json=body).status_code == 409

    updated = client.patch(f"{API_PREFIX}/admin/catalog/products/{item['id']}", headers=admin_headers, json={
        "selling_price": 35, "stock_quantity": 2, "low_stock_threshold": 4,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["selling_price"] == "35.00"
    assert updated.json()["stock_quantity"] == 2
    hidden = client.patch(f"{API_PREFIX}/admin/catalog/products/{item['id']}", headers=admin_headers, json={"is_active": False})
    assert hidden.status_code == 200
    assert hidden.json()["is_active"] is False
    assert client.get(f"{API_PREFIX}/catalog/demo-product-gamma").status_code == 404


def test_catalog_management_is_admin_only(client, catalog_rows):
    assert client.get(f"{API_PREFIX}/admin/catalog/products").status_code == 401
