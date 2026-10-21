from collections.abc import Generator
import os
import secrets

os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.rate_limit import limiter
from app.db.base import Base
import app.models  # noqa: F401 - ensure all tables are registered
from app.main import app
from app.models.catalog import ActiveIngredient, Category, Inventory, Product, ProductIngredient


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = test_session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    rate_limit_was_enabled = limiter.enabled
    limiter.enabled = False
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        limiter.enabled = rate_limit_was_enabled
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def catalog_rows(db_session: Session) -> dict[str, Product]:
    category = Category(slug="demo", name="Demo catalog")
    alpha = ActiveIngredient(slug="alpha", name="Sample Active Alpha")
    beta = ActiveIngredient(slug="beta", name="Sample Active Beta")
    db_session.add_all([category, alpha, beta])
    db_session.flush()

    products = {
        "alpha": Product(
            slug="demo-alpha",
            sku="DEMO-ALPHA",
            name="Demo Tablet Alpha",
            category=category,
            description="Fictional test listing.",
            dosage_form="Tablet",
            manufacturer="Example Labs (fictional)",
            pack_quantity=10,
            pack_unit="tablets",
            mrp=100,
            selling_price=75,
            prescription_required=False,
            is_synthetic=True,
            is_active=True,
            ingredients=[ProductIngredient(ingredient=alpha, strength_amount=250, strength_unit="mg")],
            inventory=Inventory(available_quantity=4, low_stock_threshold=2),
        ),
        "beta": Product(
            slug="demo-beta",
            sku="DEMO-BETA",
            name="Demo Capsule Beta",
            category=category,
            description="Fictional test listing.",
            dosage_form="Capsule",
            manufacturer="Example Labs (fictional)",
            pack_quantity=10,
            pack_unit="capsules",
            mrp=150,
            selling_price=120,
            prescription_required=True,
            is_synthetic=True,
            is_active=True,
            ingredients=[ProductIngredient(ingredient=beta, strength_amount=100, strength_unit="mg")],
            inventory=Inventory(available_quantity=0, low_stock_threshold=2),
        ),
        "inactive": Product(
            slug="hidden-alpha",
            sku="HIDDEN-ALPHA",
            name="Hidden Alpha Listing",
            category=category,
            description="Inactive fictional test listing.",
            dosage_form="Tablet",
            manufacturer="Example Labs (fictional)",
            pack_quantity=10,
            pack_unit="tablets",
            mrp=100,
            selling_price=75,
            prescription_required=False,
            is_synthetic=True,
            is_active=False,
            ingredients=[ProductIngredient(ingredient=alpha, strength_amount=250, strength_unit="mg")],
            inventory=Inventory(available_quantity=9, low_stock_threshold=2),
        ),
    }
    db_session.add_all(products.values())
    db_session.commit()
    return products
