from __future__ import annotations

import hmac
from urllib.parse import urlparse

from app.config import settings


def api_key_is_valid(provided: str | None) -> bool:
    if not settings.app_api_key:
        return True
    return bool(provided) and hmac.compare_digest(provided, settings.app_api_key)


def has_remote_cors_origin() -> bool:
    """Return True when any configured browser origin is not loopback-only."""
    for raw in settings.cors_origins.split(","):
        origin = raw.strip()
        if not origin:
            continue
        host = (urlparse(origin).hostname or "").lower()
        if host not in {"localhost", "127.0.0.1", "::1"}:
            return True
    return False


def validate_auth_configuration() -> None:
    if settings.require_auth and not settings.app_api_key and not settings.external_auth_enabled:
        raise RuntimeError(
            "Refusing to start because authentication is required but not configured. "
            "Set APP_API_KEY, or set EXTERNAL_AUTH_ENABLED=true only when an upstream "
            "service such as Cloudflare Access protects the application."
        )


def has_unprotected_remote_origin() -> bool:
    return (
        has_remote_cors_origin()
        and not settings.require_auth
        and not settings.app_api_key
        and not settings.external_auth_enabled
    )
