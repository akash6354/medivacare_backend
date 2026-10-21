from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.catalog import ActiveIngredient, Category, Inventory, Product, ProductIngredient

DEMO_DESCRIPTION = "Fictional sample listing for software demonstrations. This is not a real medicine."

PRODUCTS = [
    {
        "slug": "demo-tablet-alpha-250",
        "sku": "DEMO-TAB-ALPHA-250",
        "name": "Demo Tablet Alpha 250",
        "category": "demo-tablets-capsules",
        "dosage_form": "Tablet",
        "pack_quantity": 10,
        "pack_unit": "tablets",
        "mrp": Decimal("99.00"),
        "selling_price": Decimal("69.00"),
        "rx": False,
        "stock": 36,
        "ingredients": [("sample-active-alpha", Decimal("250"), "mg")],
    },
    {
        "slug": "demo-capsule-beta-100",
        "sku": "DEMO-CAP-BETA-100",
        "name": "Demo Capsule Beta 100",
        "category": "demo-tablets-capsules",
        "dosage_form": "Capsule",
        "pack_quantity": 10,
        "pack_unit": "capsules",
        "mrp": Decimal("149.00"),
        "selling_price": Decimal("112.50"),
        "rx": True,
        "stock": 0,
        "ingredients": [("sample-active-beta", Decimal("100"), "mg")],
    },
    {
        "slug": "demo-combination-tablet",
        "sku": "DEMO-TAB-COMBO-01",
        "name": "Demo Combination Tablet",
        "category": "demo-tablets-capsules",
        "dosage_form": "Tablet",
        "pack_quantity": 10,
        "pack_unit": "tablets",
        "mrp": Decimal("179.00"),
        "selling_price": Decimal("134.25"),
        "rx": True,
        "stock": 18,
        "ingredients": [
            ("sample-active-alpha", Decimal("125"), "mg"),
            ("sample-active-beta", Decimal("50"), "mg"),
        ],
    },
    {
        "slug": "demo-liquid-gamma-5",
        "sku": "DEMO-LIQ-GAMMA-005",
        "name": "Demo Liquid Gamma 5",
        "category": "demo-liquids",
        "dosage_form": "Oral liquid",
        "pack_quantity": 1,
        "pack_unit": "bottle",
        "mrp": Decimal("89.00"),
        "selling_price": Decimal("71.00"),
        "rx": False,
        "stock": 8,
        "ingredients": [("sample-active-gamma", Decimal("5"), "mg/5 mL")],
    },
]

CATEGORIES = [
    ("demo-tablets-capsules", "Demo tablets & capsules"),
    ("demo-liquids", "Demo liquids"),
]

INGREDIENTS = [
    ("sample-active-alpha", "Sample Active Alpha"),
    ("sample-active-beta", "Sample Active Beta"),
    ("sample-active-gamma", "Sample Active Gamma"),
]


def seed_catalog() -> int:
    created_count = 0
    with SessionLocal.begin() as session:
        categories: dict[str, Category] = {}
        ingredients: dict[str, ActiveIngredient] = {}

        for slug, name in CATEGORIES:
            category = session.scalar(select(Category).where(Category.slug == slug))
            if category is None:
                category = Category(slug=slug, name=name, description="Synthetic product examples only.")
                session.add(category)
                session.flush()
            categories[slug] = category

        for slug, name in INGREDIENTS:
            ingredient = session.scalar(select(ActiveIngredient).where(ActiveIngredient.slug == slug))
            if ingredient is None:
                ingredient = ActiveIngredient(slug=slug, name=name)
                session.add(ingredient)
                session.flush()
            ingredients[slug] = ingredient

        for item in PRODUCTS:
            if session.scalar(select(Product.id).where(Product.slug == item["slug"])) is not None:
                continue
            product = Product(
                slug=item["slug"],
                sku=item["sku"],
                name=item["name"],
                category=categories[item["category"]],
                description=DEMO_DESCRIPTION,
                dosage_form=item["dosage_form"],
                manufacturer="Example Labs (fictional)",
                pack_quantity=item["pack_quantity"],
                pack_unit=item["pack_unit"],
                mrp=item["mrp"],
                selling_price=item["selling_price"],
                prescription_required=item["rx"],
                is_synthetic=True,
                is_active=True,
            )
            product.ingredients = [
                ProductIngredient(
                    ingredient=ingredients[ingredient_slug],
                    strength_amount=amount,
                    strength_unit=unit,
                )
                for ingredient_slug, amount, unit in item["ingredients"]
            ]
            product.inventory = Inventory(
                available_quantity=item["stock"], low_stock_threshold=5
            )
            session.add(product)
            created_count += 1

    return created_count


if __name__ == "__main__":
    count = seed_catalog()
    print(f"Added {count} synthetic demo product(s); existing listings were left unchanged.")
