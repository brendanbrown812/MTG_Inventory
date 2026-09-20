from __future__ import annotations

import pytest

from app.config import settings
from app.security import resolved_auth_mode, validate_auth_configuration


def test_remote_origin_requires_authentication() -> None:
    original_origins = settings.cors_origins
    original_key = settings.app_api_key
    original_required = settings.require_auth
    original_external = settings.external_auth_enabled
    original_mode = settings.auth_mode
    try:
        settings.cors_origins = "https://spellbinder.example.com"
        settings.app_api_key = ""
        settings.require_auth = False
        settings.external_auth_enabled = False
        settings.auth_mode = "auto"
        validate_auth_configuration()

        settings.require_auth = True
        validate_auth_configuration()
        assert resolved_auth_mode() == "session"

        settings.app_api_key = "secret"
        validate_auth_configuration()

        settings.app_api_key = ""
        settings.external_auth_enabled = True
        validate_auth_configuration()
    finally:
        settings.cors_origins = original_origins
        settings.app_api_key = original_key
        settings.require_auth = original_required
        settings.external_auth_enabled = original_external
        settings.auth_mode = original_mode


def test_explicit_auth_modes_require_their_configuration() -> None:
    original_mode = settings.auth_mode
    original_key = settings.app_api_key
    original_external = settings.external_auth_enabled
    try:
        settings.auth_mode = "api_key"
        settings.app_api_key = ""
        with pytest.raises(RuntimeError, match="APP_API_KEY"):
            validate_auth_configuration()
        settings.auth_mode = "external"
        settings.external_auth_enabled = False
        with pytest.raises(RuntimeError, match="EXTERNAL_AUTH_ENABLED"):
            validate_auth_configuration()
    finally:
        settings.auth_mode = original_mode
        settings.app_api_key = original_key
        settings.external_auth_enabled = original_external
