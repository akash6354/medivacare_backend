from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.router import api_router
from app.core.config import get_settings
from app.core.rate_limit import limiter

settings = get_settings()

app = FastAPI(
    title="MedivaCare API",
    description="Synthetic catalog, customer accounts, and demonstration order API for the MedivaCare college project.",
    version="0.1.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get(f"{settings.api_v1_prefix}/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Report that the API process is responsive."""
    return {"status": "ok", "service": "medivacare-api"}
