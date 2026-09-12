"""M5 -- Enrollment and promotion."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import orm

from .base import JSON, TenantModel

ENROLLMENT_STATUSES = ("active", "promoted", "repeated", "transferred", "withdrawn")


class Enrollment(TenantModel):
    """A student's membership of a class for an academic year."""

    __tablename__ = "enrollments"

    student_id = sa.Column(
        sa.Uuid, sa.ForeignKey("students.id", ondelete="RESTRICT"), nullable=False
    )
    class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    academic_year_id = sa.Column(
        sa.Uuid, sa.ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False
    )
    enrolled_on = sa.Column(sa.Date, nullable=False)
    ended_on = sa.Column(sa.Date)
    status = sa.Column(sa.Text, nullable=False, default="active", index=True)
    reason = sa.Column(sa.Text)

    student = orm.relationship("Student", lazy="joined")
    school_class = orm.relationship("SchoolClass", lazy="joined")

    __table_args__ = (
        sa.CheckConstraint(
            "status in ('active','promoted','repeated','transferred','withdrawn')",
            name="ck_enrollments_status",
        ),
        # One active enrollment per student per year.
        sa.Index(
            "uq_enrollments_active_student_year",
            "school_id",
            "student_id",
            "academic_year_id",
            unique=True,
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        ),
        sa.Index("ix_enrollments_school_class", "school_id", "class_id", "status"),
    )

    def to_dict(self, include_student: bool = False) -> dict:
        data = {
            "id": str(self.id),
            "student_id": str(self.student_id),
            "class_id": str(self.class_id),
            "academic_year_id": str(self.academic_year_id),
            "enrolled_on": self.enrolled_on.isoformat() if self.enrolled_on else None,
            "ended_on": self.ended_on.isoformat() if self.ended_on else None,
            "status": self.status,
            "reason": self.reason,
        }
        if include_student and self.student:
            data["student"] = self.student.to_dict()
        return data


class EnrollmentHistory(TenantModel):
    """Append-only trail of moves so a student's path is reconstructable."""

    __tablename__ = "enrollment_history"

    student_id = sa.Column(
        sa.Uuid, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    from_class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="SET NULL"))
    to_class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="SET NULL"))
    action = sa.Column(sa.Text, nullable=False)  # enrolled | transferred | promoted | repeated
    effective_date = sa.Column(sa.Date, nullable=False)
    reason = sa.Column(sa.Text)
    performed_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (sa.Index("ix_enrollment_history_student", "school_id", "student_id"),)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "student_id": str(self.student_id),
            "from_class_id": str(self.from_class_id) if self.from_class_id else None,
            "to_class_id": str(self.to_class_id) if self.to_class_id else None,
            "action": self.action,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PromotionBatch(TenantModel):
    """One year-end promotion run: source class, destination, held-back exceptions."""

    __tablename__ = "promotion_batches"

    source_class_id = sa.Column(
        sa.Uuid, sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False
    )
    target_class_id = sa.Column(
        sa.Uuid, sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False
    )
    promoted_count = sa.Column(sa.Integer, nullable=False, default=0)
    retained_count = sa.Column(sa.Integer, nullable=False, default=0)
    retained_student_ids = sa.Column(JSON, nullable=False, default=list)
    criteria = sa.Column(JSON, nullable=False, default=dict)
    executed_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "source_class_id": str(self.source_class_id),
            "target_class_id": str(self.target_class_id),
            "promoted_count": self.promoted_count,
            "retained_count": self.retained_count,
            "retained_student_ids": self.retained_student_ids or [],
            "criteria": self.criteria or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
