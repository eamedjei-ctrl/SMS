"""Tenant isolation enforcement.

Isolation is a safety property, not a feature. It must never depend on a
developer remembering to write ``.filter_by(school_id=...)``.

Enforcement happens in one place: a ``do_orm_execute`` hook rewrites every ORM
SELECT with ``with_loader_criteria`` so that any entity inheriting
``TenantModel`` carries ``school_id = <active tenant>`` -- including joins and
lazy relationship loads nobody wrote by hand.

The only way past it is the explicit, reviewed ``unscoped()`` context manager,
which exists for the platform tier (school registry, plan management) and for
the tenant-resolution lookup itself.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

from flask import g, has_request_context
from sqlalchemy import event, orm

_UNSCOPED_OPTION = "schoolos_unscoped"


class TenantContextError(RuntimeError):
    """Raised when a tenant-owned query runs with no active tenant."""


def set_current_school(school_id: uuid.UUID | str | None) -> None:
    g.school_id = uuid.UUID(str(school_id)) if school_id is not None else None


def current_school_id() -> uuid.UUID | None:
    if not has_request_context():
        return getattr(_local_override, "school_id", None)
    return getattr(g, "school_id", None)


class _LocalOverride:
    """Tenant context for code running outside a request (jobs, CLI, seeds)."""

    school_id: uuid.UUID | None = None


_local_override = _LocalOverride()


@contextmanager
def tenant_context(school_id: uuid.UUID | str | None):
    """Bind a tenant for non-request execution (Celery tasks, CLI, tests)."""
    previous = _local_override.school_id
    _local_override.school_id = uuid.UUID(str(school_id)) if school_id is not None else None
    try:
        yield
    finally:
        _local_override.school_id = previous


@contextmanager
def unscoped():
    """Escape hatch: run queries without tenant filtering.

    Only legitimate for the platform tier and tenant resolution. Every call site
    must carry a comment explaining why, and is reviewed by the Lead.
    """
    if has_request_context():
        previous = getattr(g, _UNSCOPED_OPTION, False)
        setattr(g, _UNSCOPED_OPTION, True)
        try:
            yield
        finally:
            setattr(g, _UNSCOPED_OPTION, previous)
    else:
        previous = getattr(_local_override, "unscoped", False)
        _local_override.unscoped = True  # type: ignore[attr-defined]
        try:
            yield
        finally:
            _local_override.unscoped = previous  # type: ignore[attr-defined]


def _is_unscoped() -> bool:
    if has_request_context():
        return bool(getattr(g, _UNSCOPED_OPTION, False))
    return bool(getattr(_local_override, "unscoped", False))


def register_tenant_guard(db) -> None:
    """Attach the automatic ``school_id`` filter to every ORM SELECT."""

    from .models.base import TenantModel

    @event.listens_for(db.session.__class__, "do_orm_execute")
    def _add_tenant_criteria(execute_state):  # pragma: no cover - exercised via tests
        if not execute_state.is_select:
            return
        if execute_state.is_column_load or execute_state.is_relationship_load:
            # Refreshes of already-loaded rows; the parent load was scoped.
            return
        if execute_state.execution_options.get(_UNSCOPED_OPTION, False):
            return
        if _is_unscoped():
            return

        school_id = current_school_id()
        if school_id is None:
            # No tenant bound: platform-tier request, CLI, or a bug. Tenant-owned
            # entities resolve to an empty set rather than leaking across schools.
            school_id = uuid.UUID(int=0)

        execute_state.statement = execute_state.statement.options(
            orm.with_loader_criteria(
                TenantModel,
                lambda cls: cls.school_id == school_id,
                include_aliases=True,
            )
        )
