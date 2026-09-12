"""Authentication, tokens and authorisation.

Implemented once, centrally -- never repeated in a route handler.
"""

from __future__ import annotations

import functools
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask import current_app, g, request

from .permissions import FULL, READ, SCOPED, level_for
from .utils.errors import ApiError, ErrorCode, permission_denied

ACCESS_TOKEN = "access"
REFRESH_TOKEN = "refresh"

_default_hasher = PasswordHasher()
_test_hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
def _hasher() -> PasswordHasher:
    """Argon2id at production cost, deliberately cheap under the test suite."""
    try:
        if current_app.config.get("TESTING"):
            return _test_hasher
    except RuntimeError:  # no application context (CLI, workers)
        pass
    return _default_hasher


def hash_password(raw: str) -> str:
    return _hasher().hash(raw)


def verify_password(password_hash: str, raw: str) -> bool:
    try:
        return _hasher().verify(password_hash, raw)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher().check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


# --------------------------------------------------------------------------
# JWTs
# --------------------------------------------------------------------------
def _encode(payload: dict) -> str:
    return jwt.encode(
        payload,
        current_app.config["JWT_SECRET_KEY"],
        algorithm=current_app.config["JWT_ALGORITHM"],
    )


def issue_access_token(user, school_id, permissions: list[str], roles: list[str]) -> str:
    now = datetime.now(timezone.utc)
    return _encode(
        {
            "sub": str(user.id),
            "sid": str(school_id),
            "typ": ACCESS_TOKEN,
            "roles": roles,
            "perms": permissions,
            "iat": now,
            "exp": now + timedelta(minutes=current_app.config["JWT_ACCESS_TOKEN_MINUTES"]),
            "jti": uuid.uuid4().hex,
        }
    )


def issue_refresh_token(user, school_id, jti: str) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=current_app.config["JWT_REFRESH_TOKEN_DAYS"])
    token = _encode(
        {
            "sub": str(user.id),
            "sid": str(school_id),
            "typ": REFRESH_TOKEN,
            "iat": now,
            "exp": expires_at,
            "jti": jti,
        }
    )
    return token, expires_at


def issue_platform_token(platform_user) -> str:
    now = datetime.now(timezone.utc)
    return _encode(
        {
            "sub": str(platform_user.id),
            "typ": ACCESS_TOKEN,
            "platform": True,
            "roles": [platform_user.role],
            "perms": [],
            "iat": now,
            "exp": now + timedelta(minutes=current_app.config["JWT_ACCESS_TOKEN_MINUTES"]),
            "jti": uuid.uuid4().hex,
        }
    )


def decode_token(token: str, expected_type: str = ACCESS_TOKEN) -> dict:
    try:
        claims = jwt.decode(
            token,
            current_app.config["JWT_SECRET_KEY"],
            algorithms=[current_app.config["JWT_ALGORITHM"]],
        )
    except jwt.ExpiredSignatureError:
        raise ApiError(ErrorCode.TOKEN_EXPIRED, "Your session has expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise ApiError(ErrorCode.AUTHENTICATION_REQUIRED, "Invalid authentication token.")
    if claims.get("typ") != expected_type:
        raise ApiError(ErrorCode.AUTHENTICATION_REQUIRED, "Invalid authentication token.")
    return claims


def bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return None


# --------------------------------------------------------------------------
# Current request identity
# --------------------------------------------------------------------------
def current_user():
    return getattr(g, "current_user", None)


def current_claims() -> dict:
    return getattr(g, "token_claims", {}) or {}


def is_platform_request() -> bool:
    return bool(current_claims().get("platform"))


def current_permissions() -> set[str]:
    return set(current_claims().get("perms", []))


def current_roles() -> list[str]:
    return list(current_claims().get("roles", []))


def authenticate_request() -> None:
    """Populates ``g.current_user`` / ``g.token_claims``; raises if invalid."""
    from .models import PlatformUser, User
    from .services import token_store
    from .tenancy import unscoped

    token = bearer_token()
    if not token:
        raise ApiError(ErrorCode.AUTHENTICATION_REQUIRED, "Sign in to continue.")

    claims = decode_token(token, ACCESS_TOKEN)
    if token_store.is_revoked(claims.get("jti", "")):
        raise ApiError(ErrorCode.AUTHENTICATION_REQUIRED, "This session has been signed out.")

    g.token_claims = claims

    if claims.get("platform"):
        # Platform tier: our own staff, not bound to a tenant.
        with unscoped():
            user = PlatformUser.query.filter_by(id=uuid.UUID(claims["sub"])).first()
        if user is None or user.status != "active":
            raise ApiError(ErrorCode.AUTHENTICATION_REQUIRED, "Account is not active.")
        g.current_user = user
        g.is_platform_user = True
        return

    token_school_id = claims.get("sid")
    resolved = getattr(g, "school_id", None)
    if resolved is not None and str(resolved) != str(token_school_id):
        # Either a bug or an attack -- both get a security audit entry.
        from .services.audit_service import record_security_event

        record_security_event(
            "tenant_mismatch",
            detail={"token_school_id": token_school_id, "resolved_school_id": str(resolved)},
        )
        raise ApiError(ErrorCode.TENANT_MISMATCH, "This session does not belong to this school.")

    from .tenancy import set_current_school

    set_current_school(token_school_id)

    user = User.query.filter_by(id=uuid.UUID(claims["sub"])).first()
    if user is None or user.status != "active":
        raise ApiError(ErrorCode.AUTHENTICATION_REQUIRED, "Account is not active.")

    g.current_user = user
    g.is_platform_user = False


# --------------------------------------------------------------------------
# Authorisation
# --------------------------------------------------------------------------
def has_permission(permission: str) -> bool:
    if is_platform_request():
        roles = current_roles()
        level = None
        for role in roles:
            level = level_for(role, permission) or level
        return level is not None
    return permission in current_permissions()


def permission_level(permission: str) -> str | None:
    """The highest level the current user holds for a permission."""
    ranking = {READ: 1, SCOPED: 2, FULL: 3}
    best = None
    for role in current_roles():
        level = level_for(role, permission)
        if level and (best is None or ranking[level] > ranking[best]):
            best = level
    return best


def requires(*permissions: str, require_all: bool = True):
    """Route decorator: authenticate, then check the permission matrix."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if current_user() is None:
                authenticate_request()
            checks = [has_permission(p) for p in permissions]
            allowed = all(checks) if require_all else any(checks)
            if not allowed:
                raise permission_denied(f"This action requires: {', '.join(permissions)}.")
            return view(*args, **kwargs)

        wrapper._required_permissions = permissions  # for the OpenAPI generator
        return wrapper

    return decorator


def requires_auth(view):
    """Authenticated, but no specific permission needed."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            authenticate_request()
        return view(*args, **kwargs)

    return wrapper


def requires_platform(*roles: str):
    """Platform-tier endpoints: our own staff only."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if current_user() is None:
                authenticate_request()
            if not is_platform_request():
                raise permission_denied("Platform access required.")
            if roles and current_user().role not in roles:
                raise permission_denied("Platform access required.")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def is_scoped(permission: str) -> bool:
    """True when the caller holds the permission only over their own resources."""
    if is_platform_request():
        return False
    return permission_level(permission) == SCOPED
