"""M2 -- login, sessions, lockout and password lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app, g, request

from ..extensions import db
from ..models import LoginAttempt, PasswordReset, RefreshSession, User
from ..security import (
    REFRESH_TOKEN,
    decode_token,
    generate_token,
    hash_password,
    hash_token,
    issue_access_token,
    issue_refresh_token,
    needs_rehash,
    verify_password,
)
from ..services import token_store
from ..utils.errors import ApiError, ErrorCode, validation_error

COMMON_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "12345678",
    "qwerty123",
    "letmein1",
    "changeme",
    "admin123",
    "welcome1",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def validate_password_policy(password: str, field: str = "password") -> None:
    minimum = current_app.config["PASSWORD_MIN_LENGTH"]
    errors: list[str] = []
    if len(password or "") < minimum:
        errors.append(f"Must be at least {minimum} characters.")
    if password and password.lower() in COMMON_PASSWORDS:
        errors.append("That password is too common. Choose another.")
    if password and password.isdigit():
        errors.append("Use letters as well as numbers.")
    if errors:
        raise validation_error({field: errors})


def _record_attempt(identifier: str, user: User | None, succeeded: bool) -> None:
    from ..tenancy import current_school_id

    school_id = current_school_id()
    if school_id is None:
        return
    db.session.add(
        LoginAttempt(
            school_id=school_id,
            identifier=identifier,
            user_id=user.id if user else None,
            succeeded=succeeded,
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
            user_agent=request.headers.get("User-Agent"),
        )
    )


def find_user(identifier: str) -> User | None:
    """Login accepts email or phone; both are unique within a school."""
    value = (identifier or "").strip().lower()
    if not value:
        return None
    user = User.query.filter(db.func.lower(User.email) == value).first()
    if user is None:
        user = User.query.filter(User.phone == identifier.strip()).first()
    return user


def authenticate(identifier: str, password: str) -> User:
    """Verify credentials. Identical response for unknown and wrong-password."""
    invalid = ApiError(
        ErrorCode.AUTHENTICATION_REQUIRED, "Those credentials did not match our records."
    )
    user = find_user(identifier)

    if user is None:
        _record_attempt(identifier, None, False)
        db.session.commit()
        raise invalid

    locked_until = _as_aware(user.locked_until)
    if locked_until and locked_until > _now():
        minutes = max(1, int((locked_until - _now()).total_seconds() // 60))
        raise ApiError(
            ErrorCode.PERMISSION_DENIED,
            f"This account is locked. Try again in {minutes} minute(s) or reset your password.",
        )

    if user.status == "suspended":
        _record_attempt(identifier, user, False)
        db.session.commit()
        raise ApiError(ErrorCode.PERMISSION_DENIED, "This account has been suspended.")

    if not verify_password(user.password_hash, password):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        max_attempts = current_app.config["LOGIN_MAX_ATTEMPTS"]
        if user.failed_login_count >= max_attempts:
            user.locked_until = _now() + timedelta(
                minutes=current_app.config["LOGIN_LOCKOUT_MINUTES"]
            )
        _record_attempt(identifier, user, False)
        db.session.commit()
        # The lock takes effect from the next attempt, so the response to this
        # one stays indistinguishable from any other wrong password.
        raise invalid

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = _now()
    _record_attempt(identifier, user, True)
    return user


def issue_session(user: User) -> dict:
    """Create a refresh session and return the token pair the client stores."""
    jti = uuid.uuid4().hex
    refresh_token, expires_at = issue_refresh_token(user, user.school_id, jti)

    db.session.add(
        RefreshSession(
            school_id=user.school_id,
            user_id=user.id,
            jti=jti,
            expires_at=expires_at,
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
            user_agent=request.headers.get("User-Agent"),
        )
    )

    permissions = sorted(user.permission_codes)
    access_token = issue_access_token(user, user.school_id, permissions, user.role_keys)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": current_app.config["JWT_ACCESS_TOKEN_MINUTES"] * 60,
        "user": user.to_dict(),
        "permissions": permissions,
        "must_change_password": user.must_change_password,
    }


def refresh_session(refresh_token: str) -> dict:
    """Rotate on use: the presented token is revoked and a new pair issued."""
    claims = decode_token(refresh_token, REFRESH_TOKEN)
    session = RefreshSession.query.filter_by(jti=claims.get("jti")).first()

    if session is None or session.revoked_at is not None:
        raise ApiError(ErrorCode.AUTHENTICATION_REQUIRED, "This session is no longer valid.")
    expires_at = _as_aware(session.expires_at)
    if expires_at and expires_at < _now():
        raise ApiError(ErrorCode.TOKEN_EXPIRED, "Your session has expired. Please sign in again.")

    user = User.query.filter_by(id=session.user_id).first()
    if user is None or user.status != "active":
        raise ApiError(ErrorCode.AUTHENTICATION_REQUIRED, "Account is not active.")

    session.revoked_at = _now()
    return issue_session(user)


def revoke_session(user: User, refresh_token: str | None = None) -> None:
    """Sign out: revoke the refresh session and blacklist the access token."""
    if refresh_token:
        try:
            claims = decode_token(refresh_token, REFRESH_TOKEN)
            session = RefreshSession.query.filter_by(jti=claims.get("jti")).first()
            if session is not None:
                session.revoked_at = _now()
        except ApiError:
            pass
    else:
        for session in RefreshSession.query.filter_by(user_id=user.id, revoked_at=None).all():
            session.revoked_at = _now()

    token_store.revoke_access_token(getattr(g, "token_claims", {}) or {})


def revoke_all_sessions(user: User) -> int:
    count = 0
    for session in RefreshSession.query.filter_by(user_id=user.id, revoked_at=None).all():
        session.revoked_at = _now()
        count += 1
    return count


def start_password_reset(identifier: str, channel: str = "email") -> tuple[User | None, str | None]:
    """Create a single-use, 1-hour reset token.

    The caller must respond identically whether or not the account exists --
    enumeration is a real attack on a school platform.
    """
    user = find_user(identifier)
    if user is None or user.status == "suspended":
        return None, None

    raw_token = generate_token()
    db.session.add(
        PasswordReset(
            school_id=user.school_id,
            user_id=user.id,
            token_hash=hash_token(raw_token),
            channel=channel,
            expires_at=_now() + timedelta(hours=1),
        )
    )
    return user, raw_token


def complete_password_reset(raw_token: str, new_password: str) -> User:
    validate_password_policy(new_password, field="new_password")
    record = PasswordReset.query.filter_by(token_hash=hash_token(raw_token)).first()

    invalid = ApiError(
        ErrorCode.VALIDATION_ERROR, "This reset link is invalid or has already been used."
    )
    if record is None or record.used_at is not None:
        raise invalid
    expires_at = _as_aware(record.expires_at)
    if expires_at and expires_at < _now():
        raise ApiError(ErrorCode.VALIDATION_ERROR, "This reset link has expired.")

    user = User.query.filter_by(id=record.user_id).first()
    if user is None:
        raise invalid

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None
    record.used_at = _now()
    revoke_all_sessions(user)
    return user


def change_password(user: User, current_password: str, new_password: str) -> None:
    if not verify_password(user.password_hash, current_password):
        raise validation_error({"current_password": ["That password is incorrect."]})
    validate_password_policy(new_password, field="new_password")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    revoke_all_sessions(user)
