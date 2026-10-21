import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.models.catalog import Product

API_PREFIX = get_settings().api_v1_prefix


def test_catalog_search_matches_active_ingredient(client, catalog_rows):
    response = client.get(f"{API_PREFIX}/catalog", params={"q": "Sample Active Alpha"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["slug"] == "demo-alpha"
    assert payload["items"][0]["active_ingredients"][0]["name"] == "Sample Active Alpha"


def test_catalog_excludes_inactive_and_supports_stock_filter(client, catalog_rows):
    response = client.get(
        f"{API_PREFIX}/catalog",
        params={"availability": "out_of_stock", "page_size": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["total_pages"] == 1
    assert payload["items"][0]["slug"] == "demo-beta"
    assert payload["items"][0]["in_stock"] is False


def test_catalog_paginates_and_sorts_by_price(client, catalog_rows):
    response = client.get(
        f"{API_PREFIX}/catalog",
        params={"sort": "price_asc", "page": 1, "page_size": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["total_pages"] == 2
    assert payload["items"][0]["slug"] == "demo-alpha"


def test_catalog_product_detail_includes_price_and_composition(client, catalog_rows):
    response = client.get(f"{API_PREFIX}/catalog/demo-alpha")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selling_price"] == "75.00"
    assert payload["mrp"] == "100.00"
    assert payload["savings"] == "25.00"
    assert payload["unit_price"] == "7.50"
    assert payload["active_ingredients"][0]["strength_amount"] == "250.000"
    assert payload["synthetic_data"] is True


def test_catalog_product_detail_hides_inactive_and_unknown_products(client, catalog_rows):
    inactive = client.get(f"{API_PREFIX}/catalog/hidden-alpha")
    missing = client.get(f"{API_PREFIX}/catalog/not-a-product")

    assert inactive.status_code == 404
    assert missing.status_code == 404


def test_catalog_rejects_oversized_page_size(client, catalog_rows):
    response = client.get(f"{API_PREFIX}/catalog", params={"page_size": 49})

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("pack_quantity", "mrp", "selling_price"),
    [(0, 100, 75), (10, 60, 75)],
)
def test_database_rejects_invalid_pack_size_or_price(
    db_session, catalog_rows, pack_quantity, mrp, selling_price
):
    invalid_product = Product(
        slug=f"invalid-{pack_quantity}-{mrp}",
        sku=f"INVALID-{pack_quantity}-{mrp}",
        name="Invalid synthetic listing",
        category=catalog_rows["alpha"].category,
        description="Test fixture only.",
        dosage_form="Tablet",
        manufacturer="Example Labs (fictional)",
        pack_quantity=pack_quantity,
        pack_unit="tablets",
        mrp=mrp,
        selling_price=selling_price,
        prescription_required=False,
        is_synthetic=True,
        is_active=True,
    )
    db_session.add(invalid_product)

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
