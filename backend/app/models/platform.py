"""The platform tier: tables that are not tenant-owned (spec 3.3)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import orm

from .base import JSON, PlatformModel, TenantModel

SCHOOL_STATUSES = ("trial", "active", "suspended", "archived")
CURRICULUM_MODES = ("ges", "cambridge", "hybrid")


class School(PlatformModel):
    """The tenant registry."""

    __tablename__ = "schools"

    name = sa.Column(sa.Text, nullable=False)
    subdomain = sa.Column(sa.Text, nullable=False, unique=True, index=True)
    curriculum_mode = sa.Column(sa.Text, nullable=False, default="ges")
    country = sa.Column(sa.Text, nullable=False, default="GH")
    timezone = sa.Column(sa.Text, nullable=False, default="Africa/Accra")
    currency = sa.Column(sa.Text, nullable=False, default="GHS")
    logo_url = sa.Column(sa.Text)
    address = sa.Column(sa.Text)
    phone = sa.Column(sa.Text)
    email = sa.Column(sa.Text)
    status = sa.Column(sa.Text, nullable=False, default="trial", index=True)
    onboarding_completed_at = sa.Column(sa.DateTime(timezone=True))
    settings = sa.Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        sa.CheckConstraint(
            "status in ('trial','active','suspended','archived')", name="ck_schools_status"
        ),
        sa.CheckConstraint(
            "curriculum_mode in ('ges','cambridge','hybrid')", name="ck_schools_curriculum_mode"
        ),
    )

    @property
    def is_onboarded(self) -> bool:
        return self.onboarding_completed_at is not None

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "subdomain": self.subdomain,
            "curriculum_mode": self.curriculum_mode,
            "country": self.country,
            "timezone": self.timezone,
            "currency": self.currency,
            "logo_url": self.logo_url,
            "address": self.address,
            "phone": self.phone,
            "email": self.email,
            "status": self.status,
            "onboarding_completed_at": (
                self.onboarding_completed_at.isoformat() if self.onboarding_completed_at else None
            ),
            "settings": self.settings or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CurriculumTemplate(PlatformModel):
    """Shared seed configuration applied during onboarding (Appendix A)."""

    __tablename__ = "curriculum_templates"

    template_key = sa.Column(sa.Text, nullable=False, unique=True)
    name = sa.Column(sa.Text, nullable=False)
    curriculum = sa.Column(sa.Text, nullable=False)
    country = sa.Column(sa.Text, nullable=False, default="GH")
    version = sa.Column(sa.Integer, nullable=False, default=1)
    is_active = sa.Column(sa.Boolean, nullable=False, default=True)
    payload = sa.Column(JSON, nullable=False)

    def to_dict(self, include_payload: bool = False) -> dict:
        data = {
            "id": str(self.id),
            "template_key": self.template_key,
            "name": self.name,
            "curriculum": self.curriculum,
            "country": self.country,
            "version": self.version,
        }
        if include_payload:
            data["payload"] = self.payload
        return data


class PlatformUser(PlatformModel):
    """Our own staff. Reaches every school; never carries ``school_id``."""

    __tablename__ = "platform_users"

    email = sa.Column(sa.Text, nullable=False, unique=True, index=True)
    full_name = sa.Column(sa.Text, nullable=False)
    password_hash = sa.Column(sa.Text, nullable=False)
    role = sa.Column(sa.Text, nullable=False, default="platform_support")
    status = sa.Column(sa.Text, nullable=False, default="active")
    last_login_at = sa.Column(sa.DateTime(timezone=True))
    mfa_enabled = sa.Column(sa.Boolean, nullable=False, default=False)
    mfa_secret = sa.Column(sa.Text)

    __table_args__ = (
        sa.CheckConstraint(
            "role in ('platform_admin','platform_support')", name="ck_platform_users_role"
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "status": self.status,
        }


class OnboardingProgress(TenantModel):
    """Resumable wizard state -- an admin will not finish in one sitting."""

    __tablename__ = "onboarding_progress"

    current_step = sa.Column(sa.Integer, nullable=False, default=1)
    completed_steps = sa.Column(JSON, nullable=False, default=list)
    step_data = sa.Column(JSON, nullable=False, default=dict)
    template_key = sa.Column(sa.Text)
    template_applied_at = sa.Column(sa.DateTime(timezone=True))

    school = orm.relationship("School", lazy="joined")

    __table_args__ = (sa.UniqueConstraint("school_id", name="uq_onboarding_progress_school"),)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "school_id": str(self.school_id),
            "current_step": self.current_step,
            "completed_steps": self.completed_steps or [],
            "step_data": self.step_data or {},
            "template_key": self.template_key,
            "template_applied_at": (
                self.template_applied_at.isoformat() if self.template_applied_at else None
            ),
        }
