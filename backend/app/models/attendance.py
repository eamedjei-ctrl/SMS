"""M6 -- Attendance."""

from __future__ import annotations

import sqlalchemy as sa

from .base import TenantModel


class AttendanceStatus(TenantModel):
    """Schools differ: present/absent/late/excused/sick are configuration, not code."""

    __tablename__ = "attendance_statuses"

    code = sa.Column(sa.Text, nullable=False)
    label = sa.Column(sa.Text, nullable=False)
    counts_as_present = sa.Column(sa.Boolean, nullable=False, default=True)
    triggers_notification = sa.Column(sa.Boolean, nullable=False, default=False)
    sequence = sa.Column(sa.Integer, nullable=False, default=0)
    is_default = sa.Column(sa.Boolean, nullable=False, default=False)

    __table_args__ = (
        sa.UniqueConstraint("school_id", "code", name="uq_attendance_statuses_school_code"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "code": self.code,
            "label": self.label,
            "counts_as_present": self.counts_as_present,
            "triggers_notification": self.triggers_notification,
            "sequence": self.sequence,
            "is_default": self.is_default,
        }


class AttendanceSettings(TenantModel):
    __tablename__ = "attendance_settings"

    mode = sa.Column(sa.Text, nullable=False, default="daily")  # daily | per_period
    backdate_window_days = sa.Column(sa.Integer, nullable=False, default=7)
    notify_guardians_on_absence = sa.Column(sa.Boolean, nullable=False, default=False)
    notification_delay_minutes = sa.Column(sa.Integer, nullable=False, default=60)

    __table_args__ = (sa.UniqueConstraint("school_id", name="uq_attendance_settings_school"),)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "backdate_window_days": self.backdate_window_days,
            "notify_guardians_on_absence": self.notify_guardians_on_absence,
            "notification_delay_minutes": self.notification_delay_minutes,
        }


class AttendanceRecord(TenantModel):
    __tablename__ = "attendance_records"

    student_id = sa.Column(
        sa.Uuid, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    term_id = sa.Column(sa.Uuid, sa.ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False)
    date = sa.Column(sa.Date, nullable=False)
    period_id = sa.Column(sa.Uuid)  # null for daily marking
    status_code = sa.Column(sa.Text, nullable=False)
    note = sa.Column(sa.Text)
    marked_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))
    marked_at = sa.Column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.UniqueConstraint(
            "school_id", "student_id", "date", "period_id", name="uq_attendance_slot"
        ),
        sa.Index("ix_attendance_school_class_date", "school_id", "class_id", "date"),
        sa.Index("ix_attendance_school_student_term", "school_id", "student_id", "term_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "student_id": str(self.student_id),
            "class_id": str(self.class_id),
            "term_id": str(self.term_id),
            "date": self.date.isoformat() if self.date else None,
            "period_id": str(self.period_id) if self.period_id else None,
            "status_code": self.status_code,
            "note": self.note,
            "marked_at": self.marked_at.isoformat() if self.marked_at else None,
        }
