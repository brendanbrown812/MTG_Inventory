from __future__ import annotations

import hmac
from urllib.parse import urlparse

from app.config import settings


AUTH_MODES = {"auto", "disabled", "session", "api_key", "external"}


def resolved_auth_mode() -> str:
    mode = settings.auth_mode.strip().lower()
    if mode not in AUTH_MODES:
        raise RuntimeError(f"Invalid AUTH_MODE {settings.auth_mode!r}")
    if mode != "auto":
        return mode
    if settings.app_api_key:
        return "api_key"
    if settings.external_auth_enabled:
        return "external"
    if settings.require_auth:
        return "session"
    return "disabled"


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
    mode = resolved_auth_mode()
    if mode == "api_key" and not settings.app_api_key:
        raise RuntimeError(
            "AUTH_MODE=api_key requires APP_API_KEY."
        )
    if mode == "external" and not settings.external_auth_enabled:
        raise RuntimeError("AUTH_MODE=external requires EXTERNAL_AUTH_ENABLED=true.")


def has_unprotected_remote_origin() -> bool:
    return has_remote_cors_origin() and resolved_auth_mode() == "disabled"
