"""M2 -- authentication endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, g

from ..extensions import db
from ..models import RefreshSession, School
from ..security import current_user, requires_auth
from ..services import auth_service
from ..services.audit_service import record
from ..tenancy import current_school_id, set_current_school, unscoped
from ..utils.errors import ApiError, ErrorCode, not_found
from ..utils.responses import body, ok
from ..utils.validation import Validator

bp = Blueprint("auth", __name__)


def _require_tenant() -> None:
    """Login needs a school context: subdomain header, host, or explicit field."""
    if current_school_id() is None:
        raise ApiError(
            ErrorCode.RESOURCE_NOT_FOUND,
            "No school was identified for this request. Provide the school subdomain.",
        )


@bp.post("/auth/login")
def login():
    payload = body()
    validator = Validator(payload)
    identifier = validator.string("identifier", required=True)
    password = validator.string("password", required=True)
    subdomain = validator.string("subdomain", lower=True)
    validator.raise_if_invalid()

    if subdomain and current_school_id() is None:
        with unscoped():  # platform tier: resolving which tenant to sign in to
            school = School.query.filter_by(subdomain=subdomain).first()
        if school is None:
            raise ApiError(ErrorCode.RESOURCE_NOT_FOUND, "Unknown school.")
        if school.status in {"suspended", "archived"}:
            raise ApiError(
                ErrorCode.SUBSCRIPTION_INACTIVE, "This school's subscription is inactive."
            )
        set_current_school(school.id)

    _require_tenant()

    user = auth_service.authenticate(identifier, password)
    session = auth_service.issue_session(user)
    record("login", "user", user.id)
    db.session.commit()
    return ok(session)


@bp.post("/auth/refresh")
def refresh():
    payload = body()
    validator = Validator(payload)
    token = validator.string("refresh_token", required=True)
    validator.raise_if_invalid()

    if current_school_id() is None:
        # The refresh token carries its own tenant claim; trust it, then verify.
        from ..security import REFRESH_TOKEN, decode_token

        claims = decode_token(token, REFRESH_TOKEN)
        set_current_school(claims.get("sid"))

    session = auth_service.refresh_session(token)
    db.session.commit()
    return ok(session)


@bp.post("/auth/logout")
@requires_auth
def logout():
    payload = body()
    auth_service.revoke_session(current_user(), payload.get("refresh_token"))
    record("logout", "user", current_user().id)
    db.session.commit()
    return ok({"signed_out": True})


@bp.get("/auth/me")
@requires_auth
def me():
    user = current_user()
    if getattr(g, "is_platform_user", False):
        return ok({"user": user.to_dict(), "platform": True, "permissions": []})

    with unscoped():  # platform tier: school branding for the app shell
        school = School.query.filter_by(id=current_school_id()).first()

    return ok(
        {
            "user": user.to_dict(),
            "permissions": sorted(user.permission_codes),
            "roles": user.role_keys,
            "school": school.to_dict() if school else None,
        }
    )


@bp.post("/auth/password/forgot")
def forgot_password():
    payload = body()
    validator = Validator(payload)
    identifier = validator.string("identifier", required=True)
    subdomain = validator.string("subdomain", lower=True)
    validator.raise_if_invalid()

    if subdomain and current_school_id() is None:
        with unscoped():  # platform tier: resolving the tenant for the reset
            school = School.query.filter_by(subdomain=subdomain).first()
        if school:
            set_current_school(school.id)

    response = {
        "message": "If that account exists, a reset link is on its way.",
    }

    if current_school_id() is not None:
        user, raw_token = auth_service.start_password_reset(identifier)
        db.session.commit()
        # Delivery belongs to M11. Outside production the token is returned so
        # the flow is testable end to end without a mail provider.
        if raw_token and current_app.config["ENV_NAME"] != "production":
            response["reset_token"] = raw_token

    return ok(response)


@bp.post("/auth/password/reset")
def reset_password():
    payload = body()
    validator = Validator(payload)
    token = validator.string("token", required=True)
    new_password = validator.string("new_password", required=True)
    validator.raise_if_invalid()

    if current_school_id() is None:
        raise ApiError(
            ErrorCode.RESOURCE_NOT_FOUND,
            "No school was identified for this request. Provide the school subdomain.",
        )

    user = auth_service.complete_password_reset(token, new_password)
    record("update", "user", user.id, new_values={"password": "reset"})
    db.session.commit()
    return ok({"message": "Your password has been reset. Please sign in."})


@bp.post("/auth/password/change")
@requires_auth
def change_password():
    payload = body()
    validator = Validator(payload)
    current_password = validator.string("current_password", required=True)
    new_password = validator.string("new_password", required=True)
    validator.raise_if_invalid()

    user = current_user()
    auth_service.change_password(user, current_password, new_password)
    record("update", "user", user.id, new_values={"password": "changed"})
    db.session.commit()
    return ok({"message": "Password updated. Please sign in again."})


@bp.get("/auth/sessions")
@requires_auth
def list_sessions():
    sessions = (
        RefreshSession.query.filter_by(user_id=current_user().id, revoked_at=None)
        .order_by(RefreshSession.created_at.desc())
        .all()
    )
    return ok([s.to_dict() for s in sessions])


@bp.delete("/auth/sessions/<uuid:session_id>")
@requires_auth
def revoke_one_session(session_id):
    session = RefreshSession.query.filter_by(id=session_id, user_id=current_user().id).first()
    if session is None:
        raise not_found("Session")
    session.revoked_at = db.func.now()
    db.session.commit()
    return ok({"revoked": True})


@bp.delete("/auth/sessions")
@requires_auth
def revoke_all_sessions():
    count = auth_service.revoke_all_sessions(current_user())
    db.session.commit()
    return ok({"revoked": count})
