from __future__ import annotations

import pytest

from app.config import settings
from app.security import validate_auth_configuration


def test_remote_origin_requires_authentication() -> None:
    original_origins = settings.cors_origins
    original_key = settings.app_api_key
    original_required = settings.require_auth
    original_external = settings.external_auth_enabled
    try:
        settings.cors_origins = "https://spellbinder.example.com"
        settings.app_api_key = ""
        settings.require_auth = False
        settings.external_auth_enabled = False
        validate_auth_configuration()

        settings.require_auth = True
        with pytest.raises(RuntimeError, match="Refusing to start"):
            validate_auth_configuration()

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
