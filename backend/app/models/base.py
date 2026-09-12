from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from ..extensions import db

# JSONB on PostgreSQL (indexable, typed, the production target); plain JSON
# elsewhere so the test suite can run on SQLite.
JSON = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class UUIDPrimaryKey:
    id = sa.Column(sa.Uuid, primary_key=True, default=new_uuid)


class Timestamped:
    created_at = sa.Column(sa.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = sa.Column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SoftDeletable:
    deleted_at = sa.Column(sa.DateTime(timezone=True), nullable=True, index=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = utcnow()


class Authored:
    """``created_by`` / ``updated_by`` referencing ``users.id``."""

    @orm.declared_attr
    def created_by(cls):
        return sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    @orm.declared_attr
    def updated_by(cls):
        return sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class PlatformModel(UUIDPrimaryKey, Timestamped, db.Model):
    """A table that is NOT tenant-owned and must never carry ``school_id``.

    The school registry, SaaS billing, platform staff, shared curriculum
    templates and system settings live here (spec 3.3, "the platform tier").
    """

    __abstract__ = True


class TenantModel(UUIDPrimaryKey, Timestamped, db.Model):
    """Every tenant-owned row carries ``school_id``.

    Queries against subclasses are filtered automatically by the tenant guard
    registered in ``app.tenancy``; see that module for the escape hatch.
    """

    __abstract__ = True

    @orm.declared_attr
    def school_id(cls):
        return sa.Column(
            sa.Uuid,
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )


def serialize_money(value) -> str | None:
    """Money crosses the API as a string decimal, never a float (spec 6.1)."""
    if value is None:
        return None
    return f"{value:.2f}"
