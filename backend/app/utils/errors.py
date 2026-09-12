"""The shared error vocabulary (spec 6.5) and the error envelope (spec 6.3)."""

from __future__ import annotations

from flask import jsonify


class ErrorCode:
    VALIDATION_ERROR = ("VALIDATION_ERROR", 422)
    AUTHENTICATION_REQUIRED = ("AUTHENTICATION_REQUIRED", 401)
    TOKEN_EXPIRED = ("TOKEN_EXPIRED", 401)
    PERMISSION_DENIED = ("PERMISSION_DENIED", 403)
    TENANT_MISMATCH = ("TENANT_MISMATCH", 403)
    RESOURCE_NOT_FOUND = ("RESOURCE_NOT_FOUND", 404)
    DUPLICATE_RESOURCE = ("DUPLICATE_RESOURCE", 409)
    TERM_LOCKED = ("TERM_LOCKED", 423)
    INVALID_STATE = ("INVALID_STATE", 409)
    QUOTA_EXCEEDED = ("QUOTA_EXCEEDED", 429)
    SUBSCRIPTION_INACTIVE = ("SUBSCRIPTION_INACTIVE", 402)
    AI_UNAVAILABLE = ("AI_UNAVAILABLE", 503)
    RATE_LIMITED = ("RATE_LIMITED", 429)
    INTERNAL_ERROR = ("INTERNAL_ERROR", 500)
    BAD_REQUEST = ("VALIDATION_ERROR", 400)


class ApiError(Exception):
    """Raise this anywhere; the handler turns it into the standard envelope."""

    def __init__(
        self,
        code: tuple[str, int] = ErrorCode.INTERNAL_ERROR,
        message: str = "The request could not be processed.",
        details: dict | None = None,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.code = code[0]
        self.status_code = status_code or code[1]
        self.message = message
        self.details = details or {}


def validation_error(details: dict, message: str = "The request could not be processed."):
    return ApiError(ErrorCode.VALIDATION_ERROR, message, details)


def not_found(resource: str = "Resource"):
    """Always 404 across tenants -- a 403 would confirm the row exists elsewhere."""
    return ApiError(ErrorCode.RESOURCE_NOT_FOUND, f"{resource} not found.")


def permission_denied(message: str = "You do not have permission to perform this action."):
    return ApiError(ErrorCode.PERMISSION_DENIED, message)


def duplicate(message: str = "That record already exists."):
    return ApiError(ErrorCode.DUPLICATE_RESOURCE, message)


def invalid_state(message: str):
    return ApiError(ErrorCode.INVALID_STATE, message)


def term_locked(
    message: str = "Term results are approved and locked. Ask an administrator to unlock.",
):
    return ApiError(ErrorCode.TERM_LOCKED, message)


def error_response(error: ApiError, request_id: str):
    body = {
        "success": False,
        "error": {
            "code": error.code,
            "message": error.message,
        },
        "meta": {"request_id": request_id},
    }
    if error.details:
        body["error"]["details"] = error.details
    return jsonify(body), error.status_code
