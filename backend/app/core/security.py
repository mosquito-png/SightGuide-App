import hashlib
import hmac

from fastapi import Header

from app.core.config import settings
from app.core.errors import AuthenticationError


async def authenticate(authorization: str | None = Header(default=None)) -> str:
    if not settings.auth_enabled:
        return "development-user"
    if not settings.api_key or not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("Valid bearer authentication is required")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(hashlib.sha256(supplied.encode()).hexdigest(), hashlib.sha256(settings.api_key.encode()).hexdigest()):
        raise AuthenticationError("Invalid credentials")
    return "authenticated-user"
