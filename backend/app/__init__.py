"""SchoolOS API -- application factory.

Request lifecycle (spec 3.4): tenant resolution -> authentication ->
tenant/token match -> permission check -> validation -> service -> scoped
repository -> audit -> envelope.

The first three steps live here so no route has to remember them.
"""

from __future__ import annotations

import logging
import uuid

from flask import Flask, g, request
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from .config import get_config
from .extensions import cors, db, migrate
from .tenancy import register_tenant_guard, set_current_school, unscoped
from .utils.errors import ApiError, ErrorCode, error_response

# Endpoints reachable without a resolved tenant.
TENANT_EXEMPT_ENDPOINTS = {
    "meta.health",
    "meta.openapi",
    "meta.docs",
    "platform_auth.login",
    "platform.create_school",
    "platform.list_schools",
    "platform.get_school",
    "platform.update_school_status",
    "platform.check_subdomain",
}


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    logging.basicConfig(level=app.config["LOG_LEVEL"])

    db.init_app(app)
    migrate.init_app(app, db)
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=False,
        expose_headers=["X-Request-Id"],
    )

    from . import models  # noqa: F401  -- register mappers before the guard

    register_tenant_guard(db)

    _register_request_hooks(app)
    _register_error_handlers(app)
    _register_blueprints(app)
    _register_cli(app)

    return app


def _register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _assign_request_id():
        g.request_id = f"req_{uuid.uuid4().hex[:12]}"
        g.school_id = None
        g.current_user = None
        g.token_claims = {}
        g.is_platform_user = False

    @app.before_request
    def _resolve_tenant():
        """Resolve the school from subdomain or explicit header, before auth."""
        if request.method == "OPTIONS":
            return None
        if request.endpoint in TENANT_EXEMPT_ENDPOINTS or request.endpoint is None:
            return None

        subdomain = _requested_subdomain(app)
        if not subdomain:
            # No subdomain: the tenant comes from the authenticated token instead.
            return None

        from .models import School

        with unscoped():  # platform tier: the school registry is not tenant-owned
            school = School.query.filter_by(subdomain=subdomain).first()

        if school is None:
            raise ApiError(ErrorCode.RESOURCE_NOT_FOUND, "Unknown school.")
        if school.status == "suspended":
            raise ApiError(
                ErrorCode.SUBSCRIPTION_INACTIVE,
                "This school's subscription is inactive. Contact support.",
            )
        if school.status == "archived":
            raise ApiError(ErrorCode.RESOURCE_NOT_FOUND, "Unknown school.")

        set_current_school(school.id)
        g.school = school
        return None

    @app.after_request
    def _attach_request_id(response):
        response.headers["X-Request-Id"] = getattr(g, "request_id", "")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.teardown_request
    def _rollback_on_error(exc):
        if exc is not None:
            db.session.rollback()


def _requested_subdomain(app: Flask) -> str | None:
    """Header first (the SPA may be served from another origin), then Host."""
    explicit = request.headers.get("X-School-Subdomain")
    if explicit:
        return explicit.strip().lower()

    host = (request.host or "").split(":")[0].lower()
    base_domain = app.config["APP_BASE_DOMAIN"].lower()
    if host.endswith(f".{base_domain}"):
        candidate = host[: -(len(base_domain) + 1)]
        if candidate and candidate not in {"www", "api"}:
            return candidate
    return None


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(error: ApiError):
        if error.status_code >= 500:
            app.logger.exception("api error: %s", error.message)
        return error_response(error, getattr(g, "request_id", "req_unknown"))

    @app.errorhandler(IntegrityError)
    def _handle_integrity_error(error: IntegrityError):
        db.session.rollback()
        app.logger.warning("integrity error: %s", error)
        return error_response(
            ApiError(
                ErrorCode.DUPLICATE_RESOURCE,
                "That record conflicts with one that already exists.",
            ),
            getattr(g, "request_id", "req_unknown"),
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(error: HTTPException):
        mapping = {
            400: ErrorCode.BAD_REQUEST,
            401: ErrorCode.AUTHENTICATION_REQUIRED,
            403: ErrorCode.PERMISSION_DENIED,
            404: ErrorCode.RESOURCE_NOT_FOUND,
            405: ErrorCode.INVALID_STATE,
            429: ErrorCode.RATE_LIMITED,
        }
        code = mapping.get(error.code, ErrorCode.INTERNAL_ERROR)
        return error_response(
            ApiError(code, error.description or "Request failed.", status_code=error.code),
            getattr(g, "request_id", "req_unknown"),
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(error: Exception):
        db.session.rollback()
        app.logger.exception("unhandled error")
        return error_response(
            ApiError(ErrorCode.INTERNAL_ERROR, "Something went wrong on our side."),
            getattr(g, "request_id", "req_unknown"),
        )


def _register_blueprints(app: Flask) -> None:
    from .api import register_blueprints

    register_blueprints(app)


def _register_cli(app: Flask) -> None:
    from .cli import register_cli

    register_cli(app)
