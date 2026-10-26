"""Shared read-only invitations, independent of administrator accounts."""
import hmac
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.auth_service import NewSession, token_hash, utcnow
from app.config import settings
from app.models import GuestAccess, GuestSession


def guest_cookie_name() -> str:
    return "__Host-spellbinder_guest" if settings.session_cookie_secure else "spellbinder_guest"


def guest_cookie(cookies: dict[str, str]) -> str | None:
    return cookies.get("__Host-spellbinder_guest") or cookies.get("spellbinder_guest")


def rotate_invite(db: Session) -> str:
    token = secrets.token_urlsafe(32)
    access = db.get(GuestAccess, 1)
    if access is None:
        access = GuestAccess(id=1)
        db.add(access)
    access.invite_hash = token_hash(token)
    access.invite_token = token
    access.enabled = True
    access.created_at = utcnow()
    db.query(GuestSession).delete()
    return token


def redeem_invite(db: Session, token: str) -> NewSession | None:
    access = db.get(GuestAccess, 1)
    if not access or not access.enabled or not hmac.compare_digest(access.invite_hash, token_hash(token)):
        return None
    # Legacy invites only stored a digest. A valid redemption can recover the
    # original link without rotating it or invalidating any existing sessions.
    if access.invite_token is None:
        db.query(GuestAccess).filter(
            GuestAccess.id == 1, GuestAccess.enabled.is_(True),
            GuestAccess.invite_hash == token_hash(token), GuestAccess.invite_token.is_(None),
        ).update({"invite_token": token}, synchronize_session=False)
    session = NewSession(
        token=secrets.token_urlsafe(32), csrf_token=secrets.token_urlsafe(32),
        expires_at=utcnow() + timedelta(days=30),
    )
    # Keep the table bounded by removing expired guest sessions on redemption.
    db.query(GuestSession).filter(GuestSession.expires_at <= utcnow()).delete()
    db.add(GuestSession(
        token_hash=token_hash(session.token), invite_hash=access.invite_hash,
        csrf_token=session.csrf_token, expires_at=session.expires_at,
    ))
    return session


def find_guest_session(db: Session, token: str | None) -> GuestSession | None:
    if not token:
        return None
    return (
        db.query(GuestSession)
        .join(GuestAccess, GuestAccess.invite_hash == GuestSession.invite_hash)
        .filter(
            GuestAccess.id == 1, GuestAccess.enabled.is_(True),
            GuestSession.token_hash == token_hash(token), GuestSession.expires_at > utcnow(),
        )
        .first()
    )
