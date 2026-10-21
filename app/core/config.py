from functools import lru_cache
from pathlib import Path
from decimal import Decimal
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://mediva:medivacare_dev@localhost:5432/medivacare"
    frontend_origins: str = "http://localhost:5173"
    secret_key: SecretStr = SecretStr("")
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    delivery_fee: Decimal = Field(default=Decimal("40.00"), ge=0, decimal_places=2)
    free_delivery_minimum: Decimal = Field(default=Decimal("499.00"), ge=0, decimal_places=2)
    razorpay_key_id: str = ""
    razorpay_key_secret: SecretStr = SecretStr("")
    razorpay_webhook_secret: SecretStr = SecretStr("")
    razorpay_mode: Literal["test", "live"] = "test"
    razorpay_order_expiry_minutes: int = Field(default=30, ge=5, le=1440)
    prescription_storage_path: Path = PROJECT_ROOT / "backend" / "private_uploads" / "prescriptions"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
