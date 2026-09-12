"""Every mutation of academic or financial data writes an audit entry."""

from __future__ import annotations

from flask import g, has_request_context, request

from ..extensions import db
from ..models import AuditLog
from ..tenancy import current_school_id


def _actor():
    user = getattr(g, "current_user", None) if has_request_context() else None
    if user is None:
        return None, "system"
    return getattr(user, "id", None), getattr(user, "full_name", "unknown")


def _request_meta() -> dict:
    if not has_request_context():
        return {"ip_address": None, "user_agent": None, "request_id": None}
    return {
        "ip_address": request.headers.get("X-Forwarded-For", request.remote_addr),
        "user_agent": request.headers.get("User-Agent"),
        "request_id": getattr(g, "request_id", None),
    }


def record(
    action: str,
    entity_type: str,
    entity_id=None,
    old_values: dict | None = None,
    new_values: dict | None = None,
    reason: str | None = None,
    school_id=None,
    commit: bool = False,
) -> AuditLog | None:
    """Append an audit entry. Never raises into the caller's transaction path."""
    resolved_school = school_id or current_school_id()
    if resolved_school is None:
        return None

    actor_id, actor_label = _actor()
    meta = _request_meta()

    # Platform staff ids live in a different table; keep the label, drop the FK.
    if has_request_context() and getattr(g, "is_platform_user", False):
        actor_id = None
        actor_label = f"platform:{actor_label}"

    entry = AuditLog(
        school_id=resolved_school,
        user_id=actor_id,
        actor_label=actor_label,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_values=old_values,
        new_values=new_values,
        reason=reason,
        **meta,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def record_security_event(event: str, detail: dict | None = None, school_id=None) -> None:
    """Security events are written on their own transaction so they survive a rollback."""
    try:
        record(
            "security",
            entity_type="security_event",
            entity_id=event,
            new_values=detail or {},
            school_id=school_id,
            commit=True,
        )
    except Exception:
        db.session.rollback()


def diff(before: dict, after: dict) -> tuple[dict, dict]:
    """Only the fields that actually changed, so the log stays readable."""
    old_values, new_values = {}, {}
    for key, new in after.items():
        previous = before.get(key)
        if previous != new:
            old_values[key] = previous
            new_values[key] = new
    return old_values, new_values
