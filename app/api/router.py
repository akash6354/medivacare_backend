from fastapi import APIRouter

from app.api.routes.admin import router as admin_router
from app.api.routes.admin_catalog import router as admin_catalog_router
from app.api.routes.admin_data import router as admin_data_router
from app.api.routes.auth import router as auth_router
from app.api.routes.cart import router as cart_router
from app.api.routes.catalog import router as catalog_router
from app.api.routes.customers import router as customers_router
from app.api.routes.deliveries import router as deliveries_router
from app.api.routes.orders import router as orders_router
from app.api.routes.payments import router as payments_router, webhook_router
from app.api.routes.prescriptions import admin_router as admin_prescriptions_router
from app.api.routes.prescriptions import router as prescriptions_router
from app.api.routes.support import admin_router as admin_support_router, router as support_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(admin_catalog_router)
api_router.include_router(admin_data_router)
api_router.include_router(admin_support_router)
api_router.include_router(admin_prescriptions_router)
api_router.include_router(cart_router)
api_router.include_router(catalog_router)
api_router.include_router(customers_router)
api_router.include_router(deliveries_router)
api_router.include_router(orders_router)
api_router.include_router(payments_router)
api_router.include_router(prescriptions_router)
api_router.include_router(support_router)
api_router.include_router(webhook_router)
