from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID
import secrets

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import get_settings

ALGORITHM = "HS256"
ISSUER = "medivacare-api"
password_hash = PasswordHash.recommended()


class AuthenticationConfigurationError(RuntimeError):
    """Raised when a secure signing key has not been configured."""


def get_signing_key() -> str:
    secret = get_settings().secret_key.get_secret_value()
    if len(secret) < 32:
        raise AuthenticationConfigurationError(
            "Set SECRET_KEY to a random value with at least 32 characters before using authentication."
        )
    return secret


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    # Equalize the expensive password-hash step when an email address is unknown.
    return password_hash.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    if stored_hash is None:
        password_hash.verify(password, _dummy_password_hash())
        return False
    return password_hash.verify(password, stored_hash)


def create_access_token(subject: UUID) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "iss": ISSUER,
    }
    token = jwt.encode(payload, get_signing_key(), algorithm=ALGORITHM)
    return token, expires_in


def decode_access_token(token: str) -> UUID:
    payload = jwt.decode(
        token,
        get_signing_key(),
        algorithms=[ALGORITHM],
        issuer=ISSUER,
        options={"require": ["exp", "iat", "sub", "iss"]},
    )
    try:
        return UUID(payload["sub"])
    except (ValueError, TypeError, AttributeError) as error:
        raise InvalidTokenError("Invalid token subject") from error
