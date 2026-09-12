"""Health, version and the OpenAPI specification."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from ..extensions import db
from ..utils.responses import ok

bp = Blueprint("meta", __name__)


@bp.get("/health")
def health():
    checks = {"api": "ok", "database": "unknown"}
    try:
        db.session.execute(db.text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    status = 200 if checks["database"] == "ok" else 503
    return ok({"service": "schoolos-api", "version": "1.0", "checks": checks}, status)


@bp.get("/openapi.json")
def openapi():
    from ..openapi import build_spec

    return jsonify(build_spec(current_app))


@bp.get("/docs")
def docs():
    """Swagger UI, served outside production only (spec 6.8)."""
    if current_app.config["ENV_NAME"] == "production":
        return ok({"message": "Documentation is disabled in production."}, 404)
    return (
        """<!doctype html>
<html><head><meta charset="utf-8"><title>SchoolOS API</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head><body><div id="ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url:'/api/v1/openapi.json',dom_id:'#ui'});</script>
</body></html>""",
        200,
        {"Content-Type": "text/html"},
    )
