"""OpenAPI specification.

Generated from the live URL map, so an endpoint that exists is documented and an
endpoint that is documented exists. Permissions come from the ``@requires``
decorator, which is the same source the runtime check uses -- the matrix and the
documentation cannot drift apart.
"""

from __future__ import annotations

from flask import Flask

ENVELOPE_SCHEMAS = {
    "SuccessEnvelope": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "example": True},
            "data": {},
            "meta": {"$ref": "#/components/schemas/Meta"},
        },
        "required": ["success", "data", "meta"],
    },
    "Meta": {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "example": "req_a91f2c3d4e5f"},
            "timestamp": {"type": "string", "format": "date-time"},
            "pagination": {"$ref": "#/components/schemas/Pagination"},
        },
    },
    "Pagination": {
        "type": "object",
        "properties": {
            "page": {"type": "integer", "example": 1},
            "per_page": {"type": "integer", "example": 25},
            "total": {"type": "integer", "example": 487},
            "total_pages": {"type": "integer", "example": 20},
            "has_next": {"type": "boolean"},
            "has_prev": {"type": "boolean"},
        },
    },
    "ErrorEnvelope": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "example": False},
            "error": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "enum": [
                            "VALIDATION_ERROR",
                            "AUTHENTICATION_REQUIRED",
                            "TOKEN_EXPIRED",
                            "PERMISSION_DENIED",
                            "TENANT_MISMATCH",
                            "RESOURCE_NOT_FOUND",
                            "DUPLICATE_RESOURCE",
                            "TERM_LOCKED",
                            "INVALID_STATE",
                            "QUOTA_EXCEEDED",
                            "SUBSCRIPTION_INACTIVE",
                            "AI_UNAVAILABLE",
                            "RATE_LIMITED",
                            "INTERNAL_ERROR",
                        ],
                    },
                    "message": {"type": "string"},
                    "details": {"type": "object", "additionalProperties": {"type": "array"}},
                },
            },
            "meta": {"$ref": "#/components/schemas/Meta"},
        },
    },
}

STANDARD_ERRORS = {
    "401": {
        "description": "Missing, invalid or expired token",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
    },
    "403": {
        "description": "Authenticated but not permitted, or tenant mismatch",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
    },
    "404": {
        "description": "Not found, or not found within this tenant",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
    },
    "422": {
        "description": "Validation failed",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
    },
}

MODULE_TAGS = {
    "meta": "Meta",
    "platform_auth": "Platform",
    "platform": "Platform",
    "auth": "M2 Identity",
    "onboarding": "M1 Onboarding",
    "users": "M2 Administration",
    "people": "M3 People",
    "academic": "M4 Academic structure",
    "enrollment": "M5 Enrollment",
    "attendance": "M6 Attendance",
    "assessment": "M7 Assessment config",
    "results": "M7 Results engine",
    "reportcards": "M8 Report cards",
}


def build_spec(app: Flask) -> dict:
    paths: dict = {}

    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
        if rule.endpoint == "static" or not str(rule).startswith("/api/"):
            continue

        view = app.view_functions[rule.endpoint]
        blueprint = rule.endpoint.split(".")[0]
        path = _to_openapi_path(str(rule))
        entry = paths.setdefault(path, {})

        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            required = list(getattr(view, "_required_permissions", ()) or ())
            summary = (view.__doc__ or "").strip().split("\n")[0] or rule.endpoint

            operation: dict = {
                "tags": [MODULE_TAGS.get(blueprint, blueprint)],
                "summary": summary,
                "operationId": f"{method.lower()}_{rule.endpoint.replace('.', '_')}",
                "parameters": _path_parameters(rule),
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/SuccessEnvelope"}
                            }
                        },
                    },
                    **STANDARD_ERRORS,
                },
            }

            if required:
                operation["description"] = f"Requires permission: `{'`, `'.join(required)}`"
                operation["security"] = [{"bearerAuth": []}]
            elif blueprint not in {"meta"}:
                operation["security"] = [{"bearerAuth": []}]

            if method in {"POST", "PUT", "PATCH"}:
                operation["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }

            entry[method.lower()] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "SchoolOS API",
            "version": "1.0",
            "description": (
                "Multi-tenant school management platform. Every tenant-owned "
                "request is scoped by `school_id`, resolved from the subdomain "
                "or the `X-School-Subdomain` header and verified against the "
                "token's tenant claim."
            ),
        },
        "servers": [
            {
                "url": "https://{subdomain}.{domain}/api/v1",
                "variables": {
                    "subdomain": {"default": "demo"},
                    "domain": {"default": app.config["APP_BASE_DOMAIN"]},
                },
            }
        ],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            },
            "schemas": ENVELOPE_SCHEMAS,
            "parameters": {
                "SchoolSubdomain": {
                    "name": "X-School-Subdomain",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Tenant selector when the API is not reached via subdomain.",
                }
            },
        },
        "paths": paths,
    }


def _to_openapi_path(rule: str) -> str:
    """Flask's ``<uuid:id>`` becomes OpenAPI's ``{id}``."""
    parts = []
    for segment in rule.split("/"):
        if segment.startswith("<") and segment.endswith(">"):
            name = segment[1:-1].split(":")[-1]
            parts.append(f"{{{name}}}")
        else:
            parts.append(segment)
    return "/".join(parts)


def _path_parameters(rule) -> list[dict]:
    parameters = [{"$ref": "#/components/parameters/SchoolSubdomain"}]
    for argument in rule.arguments:
        parameters.append(
            {
                "name": argument,
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        )
    return parameters
