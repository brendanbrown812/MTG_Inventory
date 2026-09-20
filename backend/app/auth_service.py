from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import AuthSession, User


USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
PASSWORD_MIN_LENGTH = 12
_hasher = PasswordHasher(
    time_cost=2, memory_cost=19_456, parallelism=1, hash_len=32, salt_len=16
)
_dummy_hash = _hasher.hash("spellbinder-dummy-password")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not USERNAME_RE.fullmatch(normalized):
        raise ValueError(
            "Username must be 3-64 characters using letters, numbers, dot, dash, or underscore."
        )
    return normalized


def validate_password(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if len(password) > 1024:
        raise ValueError("Password is too long.")


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    candidate = password_hash or _dummy_hash
    try:
        return _hasher.verify(candidate, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_user(db: Session, username: str, password: str, *, role: str = "admin") -> User:
    normalized = normalize_username(username)
    if role != "admin":
        raise ValueError("Only the admin role is available in this release.")
    if db.query(User).filter(User.username == normalized).first():
        raise ValueError("That username already exists.")
    if db.query(User).filter(User.role == "admin").first():
        raise ValueError("An administrator already exists.")
    user = User(username=normalized, password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    return user


def set_password(db: Session, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.password_changed_at = utcnow()
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NewSession:
    token: str
    csrf_token: str
    expires_at: datetime


def create_session(db: Session, user: User, *, remember: bool) -> NewSession:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    duration = (
        timedelta(days=settings.remembered_session_days)
        if remember
        else timedelta(hours=settings.session_hours)
    )
    expires = utcnow() + duration
    db.add(AuthSession(
        token_hash=token_hash(token), user_id=user.id, csrf_token=csrf, expires_at=expires
    ))
    return NewSession(token=token, csrf_token=csrf, expires_at=expires)


def find_session(db: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    session = (
        db.query(AuthSession)
        .options(joinedload(AuthSession.user))
        .filter(AuthSession.token_hash == token_hash(token))
        .first()
    )
    if session is None:
        return None
    if session.expires_at <= utcnow() or not session.user.is_active:
        db.delete(session)
        db.commit()
        return None
    return session


def csrf_is_valid(session: AuthSession, provided: str | None) -> bool:
    return bool(provided) and hmac.compare_digest(session.csrf_token, provided)


def cookie_name() -> str:
    return "__Host-spellbinder_session" if settings.session_cookie_secure else "spellbinder_session"


def session_cookie(request_cookies: dict[str, str]) -> str | None:
    return request_cookies.get("__Host-spellbinder_session") or request_cookies.get(
        "spellbinder_session"
    )
