"""The response envelope every endpoint returns (spec 6.3)."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import g, jsonify, request

from .errors import ApiError, ErrorCode


def _meta(extra: dict | None = None) -> dict:
    meta = {
        "request_id": getattr(g, "request_id", "req_unknown"),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status_code: int = 200, meta: dict | None = None):
    return jsonify({"success": True, "data": data, "meta": _meta(meta)}), status_code


def created(data, meta: dict | None = None):
    return ok(data, 201, meta)


def accepted(data, meta: dict | None = None):
    """202 -- a background job started; the client polls the job id."""
    return ok(data, 202, meta)


def no_content():
    return "", 204


def paginated(items: list, page: int, per_page: int, total: int, meta: dict | None = None):
    total_pages = (total + per_page - 1) // per_page if per_page else 0
    pagination = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }
    return ok(items, meta={**(meta or {}), "pagination": pagination})


def pagination_args(default_per_page: int = 25, max_per_page: int = 100) -> tuple[int, int]:
    """Reads ``page``/``per_page``; requests above the maximum are clamped."""
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get("per_page", default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    per_page = max(1, min(per_page, max_per_page))
    return page, per_page


def apply_pagination(query, page: int, per_page: int) -> tuple[list, int]:
    total = query.order_by(None).count()
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return items, total


def body() -> dict:
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError(ErrorCode.BAD_REQUEST, "Expected a JSON object body.")
    return payload


def body_list() -> list:
    payload = request.get_json(silent=True)
    if not isinstance(payload, list):
        raise ApiError(ErrorCode.BAD_REQUEST, "Expected a JSON array body.")
    return payload
