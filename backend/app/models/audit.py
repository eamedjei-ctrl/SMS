"""M15 -- Audit trail. Append-only: never updated, never deleted."""

from __future__ import annotations

import sqlalchemy as sa

from .base import JSON, TenantModel

AUDIT_ACTIONS = (
    "create",
    "update",
    "delete",
    "approve",
    "unlock",
    "login",
    "login_failed",
    "logout",
    "export",
    "security",
)


class AuditLog(TenantModel):
    __tablename__ = "audit_logs"

    user_id = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))
    actor_label = sa.Column(sa.Text)
    action = sa.Column(sa.Text, nullable=False)
    entity_type = sa.Column(sa.Text, nullable=False)
    entity_id = sa.Column(sa.Text)
    old_values = sa.Column(JSON)
    new_values = sa.Column(JSON)
    reason = sa.Column(sa.Text)
    ip_address = sa.Column(sa.Text)
    user_agent = sa.Column(sa.Text)
    request_id = sa.Column(sa.Text)

    __table_args__ = (
        sa.Index("ix_audit_logs_school_created", "school_id", "created_at"),
        sa.Index("ix_audit_logs_school_entity", "school_id", "entity_type", "entity_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "actor_label": self.actor_label,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "old_values": self.old_values,
            "new_values": self.new_values,
            "reason": self.reason,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
