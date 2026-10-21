import hashlib
import hmac
from typing import Any

from fastapi import HTTPException

from app.core.config import Settings, get_settings


def payment_credentials(settings: Settings | None = None) -> tuple[str, str]:
    settings = settings or get_settings()
    key_id = settings.razorpay_key_id.strip()
    key_secret = settings.razorpay_key_secret.get_secret_value().strip()
    expected_prefix = "rzp_test_" if settings.razorpay_mode == "test" else "rzp_live_"
    if not key_id or not key_secret or not key_id.startswith(expected_prefix):
        raise HTTPException(
            status_code=503,
            detail=f"Razorpay {settings.razorpay_mode} credentials are not configured correctly",
        )
    return key_id, key_secret


def webhook_secret(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    secret = settings.razorpay_webhook_secret.get_secret_value().strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Razorpay webhook verification is not configured")
    return secret


def razorpay_client():
    key_id, key_secret = payment_credentials()
    try:
        import razorpay
    except ImportError as error:
        raise HTTPException(status_code=503, detail="Razorpay server SDK is not installed") from error
    return razorpay.Client(auth=(key_id, key_secret))


def checkout_signature_is_valid(order_id: str, payment_id: str, signature: str) -> bool:
    _, secret = payment_credentials()
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def webhook_signature_is_valid(raw_body: bytes, signature: str) -> bool:
    secret = webhook_secret()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _matching_receipt_order(client, receipt: str, amount: int) -> dict[str, Any] | None:
    try:
        response = client.order.all({"receipt": receipt})
    except Exception:
        return None
    for order in response.get("items", []):
        if order.get("receipt") == receipt and order.get("amount") == amount and order.get("currency") == "INR":
            return order
    return None


def create_or_retrieve_order(client, *, amount: int, receipt: str) -> dict[str, Any]:
    """Use the local order number as a provider receipt to recover safe retries."""
    remote = _matching_receipt_order(client, receipt, amount)
    if remote is None:
        try:
            remote = client.order.create(
                {"amount": amount, "currency": "INR", "receipt": receipt}
            )
        except Exception as error:
            # The provider may have accepted a request whose response was lost.
            remote = _matching_receipt_order(client, receipt, amount)
            if remote is None:
                raise error
    if (
        not remote.get("id")
        or remote.get("amount") != amount
        or remote.get("currency") != "INR"
        or remote.get("receipt") != receipt
    ):
        raise ValueError("Razorpay returned an order that does not match the local checkout")
    return remote


def provider_payment_for_order(client, provider_order_id: str) -> list[dict[str, Any]]:
    response = client.order.payments(provider_order_id)
    return response.get("items", [])
