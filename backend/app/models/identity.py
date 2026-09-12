"""M2 -- Identity, authentication and access control."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import orm

from .base import PlatformModel, TenantModel, Timestamped, UUIDPrimaryKey
from ..extensions import db

USER_STATUSES = ("invited", "active", "suspended")

# The seven system roles ship with every school and cannot be deleted.
SYSTEM_ROLES = {
    "school_admin": "School Admin",
    "head_teacher": "Head Teacher",
    "teacher": "Teacher",
    "student": "Student",
    "guardian": "Guardian",
}


class Permission(PlatformModel):
    """Shared vocabulary of ``resource.action`` strings (Appendix B)."""

    __tablename__ = "permissions"

    code = sa.Column(sa.Text, nullable=False, unique=True, index=True)
    description = sa.Column(sa.Text)
    module = sa.Column(sa.Text)


class Role(TenantModel):
    __tablename__ = "roles"

    key = sa.Column(sa.Text, nullable=False)
    name = sa.Column(sa.Text, nullable=False)
    description = sa.Column(sa.Text)
    is_system = sa.Column(sa.Boolean, nullable=False, default=False)

    permissions = orm.relationship(
        "Permission",
        secondary="role_permissions",
        lazy="selectin",
    )

    __table_args__ = (sa.UniqueConstraint("school_id", "key", name="uq_roles_school_key"),)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "is_system": self.is_system,
            "permissions": sorted(p.code for p in self.permissions),
        }


class RolePermission(UUIDPrimaryKey, Timestamped, db.Model):
    __tablename__ = "role_permissions"

    role_id = sa.Column(sa.Uuid, sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission_id = sa.Column(
        sa.Uuid, sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions"),)


class User(TenantModel):
    """One account, one school. Cross-school identity is deliberately out of scope."""

    __tablename__ = "users"

    email = sa.Column(sa.Text)
    phone = sa.Column(sa.Text)
    password_hash = sa.Column(sa.Text, nullable=False)
    full_name = sa.Column(sa.Text, nullable=False)
    status = sa.Column(sa.Text, nullable=False, default="active")
    must_change_password = sa.Column(sa.Boolean, nullable=False, default=False)
    last_login_at = sa.Column(sa.DateTime(timezone=True))
    mfa_enabled = sa.Column(sa.Boolean, nullable=False, default=False)
    mfa_secret = sa.Column(sa.Text)
    locked_until = sa.Column(sa.DateTime(timezone=True))
    failed_login_count = sa.Column(sa.Integer, nullable=False, default=0)

    roles = orm.relationship("Role", secondary="user_roles", lazy="selectin")

    __table_args__ = (
        sa.UniqueConstraint("school_id", "email", name="uq_users_school_email"),
        sa.UniqueConstraint("school_id", "phone", name="uq_users_school_phone"),
        sa.CheckConstraint("status in ('invited','active','suspended')", name="ck_users_status"),
        sa.Index("ix_users_school_status", "school_id", "status"),
    )

    @property
    def role_keys(self) -> list[str]:
        return sorted(role.key for role in self.roles)

    @property
    def permission_codes(self) -> set[str]:
        return {p.code for role in self.roles for p in role.permissions}

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "email": self.email,
            "phone": self.phone,
            "full_name": self.full_name,
            "status": self.status,
            "must_change_password": self.must_change_password,
            "mfa_enabled": self.mfa_enabled,
            "roles": self.role_keys,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class UserRole(UUIDPrimaryKey, Timestamped, db.Model):
    __tablename__ = "user_roles"

    user_id = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id = sa.Column(sa.Uuid, sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles"),)


class PasswordReset(TenantModel):
    __tablename__ = "password_resets"

    user_id = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = sa.Column(sa.Text, nullable=False, index=True)
    channel = sa.Column(sa.Text, nullable=False, default="email")
    expires_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    used_at = sa.Column(sa.DateTime(timezone=True))


class LoginAttempt(TenantModel):
    __tablename__ = "login_attempts"

    identifier = sa.Column(sa.Text, nullable=False, index=True)
    user_id = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))
    succeeded = sa.Column(sa.Boolean, nullable=False, default=False)
    ip_address = sa.Column(sa.Text)
    user_agent = sa.Column(sa.Text)


class RefreshSession(TenantModel):
    """A live refresh token. Rotated on use; revoked on logout."""

    __tablename__ = "refresh_sessions"

    user_id = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    jti = sa.Column(sa.Text, nullable=False, unique=True, index=True)
    expires_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    revoked_at = sa.Column(sa.DateTime(timezone=True))
    ip_address = sa.Column(sa.Text)
    user_agent = sa.Column(sa.Text)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }
