from __future__ import annotations

from datetime import timedelta

import pytest

from app.auth_service import create_session, create_user, hash_password, token_hash, utcnow
from app.config import settings
from app.database import SessionLocal
from app.models import AuthSession, User


PASSWORD = "correct horse battery"


def _enable_session_auth() -> None:
    settings.auth_mode = "session"
    settings.session_cookie_secure = False


def _create_admin(username: str = "brend", password: str = PASSWORD) -> int:
    with SessionLocal() as db:
        user = create_user(db, username, password)
        db.commit()
        return user.id


def test_session_status_reports_setup_then_authenticated_user(client) -> None:
    _enable_session_auth()
    first = client.get("/api/auth/status").json()
    assert first["setup_required"] is True
    assert first["authenticated"] is False

    _create_admin()
    response = client.post("/api/auth/login", json={
        "username": "BREND", "password": PASSWORD, "remember": True,
    })
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    status = client.get("/api/auth/status").json()
    assert status["authenticated"] is True
    assert status["user"] == {"username": "brend", "role": "admin"}
    assert status["csrf_token"]


def test_session_requires_csrf_for_writes_and_logout_revokes_it(client) -> None:
    _enable_session_auth()
    _create_admin()
    login_response = client.post("/api/auth/login", json={
        "username": "brend", "password": PASSWORD, "remember": False,
    })
    csrf = login_response.json()["csrf_token"]
    assert client.post("/api/inventory/clear").status_code == 403
    assert client.post(
        "/api/inventory/clear", headers={"X-CSRF-Token": csrf}
    ).status_code == 200
    assert client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": csrf}
    ).status_code == 200
    assert client.get("/api/inventory").status_code == 401


def test_invalid_login_is_generic_and_password_is_argon2(client) -> None:
    _enable_session_auth()
    _create_admin()
    with SessionLocal() as db:
        stored = db.query(User).one()
        assert stored.password_hash.startswith("$argon2id$")
        assert PASSWORD not in stored.password_hash
    unknown = client.post("/api/auth/login", json={
        "username": "nobody", "password": "incorrect password", "remember": True,
    })
    wrong = client.post("/api/auth/login", json={
        "username": "brend", "password": "incorrect password", "remember": True,
    })
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_expired_and_disabled_sessions_are_rejected(client) -> None:
    _enable_session_auth()
    user_id = _create_admin()
    with SessionLocal() as db:
        session = create_session(db, db.get(User, user_id), remember=False)
        db.flush()
        row = db.get(AuthSession, token_hash(session.token))
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    client.cookies.set("spellbinder_session", session.token)
    assert client.get("/api/inventory").status_code == 401

    login_response = client.post("/api/auth/login", json={
        "username": "brend", "password": PASSWORD, "remember": True,
    })
    assert login_response.status_code == 200
    with SessionLocal() as db:
        db.get(User, user_id).is_active = False
        db.commit()
    assert client.get("/api/inventory").status_code == 401


def test_hash_password_rejects_short_passwords() -> None:
    with pytest.raises(ValueError, match="at least 12"):
        hash_password("too short")


def test_only_one_admin_can_be_created() -> None:
    with SessionLocal() as db:
        create_user(db, "first-admin", PASSWORD)
        db.flush()
        with pytest.raises(ValueError, match="administrator already exists"):
            create_user(db, "second-admin", PASSWORD)
