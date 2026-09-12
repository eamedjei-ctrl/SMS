"""M3 -- People: students, guardians and staff."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import orm

from .base import Authored, JSON, SoftDeletable, TenantModel

STUDENT_STATUSES = ("active", "graduated", "transferred", "withdrawn")
STAFF_STATUSES = ("active", "suspended", "left")


class Student(TenantModel, SoftDeletable, Authored):
    __tablename__ = "students"

    user_id = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))
    student_code = sa.Column(sa.Text, nullable=False)
    first_name = sa.Column(sa.Text, nullable=False)
    middle_name = sa.Column(sa.Text)
    last_name = sa.Column(sa.Text, nullable=False)
    date_of_birth = sa.Column(sa.Date)
    gender = sa.Column(sa.Text)
    admission_date = sa.Column(sa.Date)
    status = sa.Column(sa.Text, nullable=False, default="active", index=True)
    photo_url = sa.Column(sa.Text)
    medical_notes = sa.Column(sa.Text)  # restricted: students.medical.view
    custom_fields = sa.Column(JSON, nullable=False, default=dict)

    guardian_links = orm.relationship(
        "StudentGuardian", back_populates="student", cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.UniqueConstraint("school_id", "student_code", name="uq_students_school_code"),
        sa.CheckConstraint(
            "status in ('active','graduated','transferred','withdrawn')",
            name="ck_students_status",
        ),
        sa.Index("ix_students_school_last_name", "school_id", "last_name"),
        sa.Index("ix_students_school_status", "school_id", "status"),
    )

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p)

    def to_dict(self, include_medical: bool = False) -> dict:
        data = {
            "id": str(self.id),
            "student_code": self.student_code,
            "first_name": self.first_name,
            "middle_name": self.middle_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "gender": self.gender,
            "admission_date": self.admission_date.isoformat() if self.admission_date else None,
            "status": self.status,
            "photo_url": self.photo_url,
            "custom_fields": self.custom_fields or {},
            "user_id": str(self.user_id) if self.user_id else None,
        }
        if include_medical:
            data["medical_notes"] = self.medical_notes
        return data


class Guardian(TenantModel, SoftDeletable, Authored):
    __tablename__ = "guardians"

    user_id = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))
    first_name = sa.Column(sa.Text, nullable=False)
    last_name = sa.Column(sa.Text, nullable=False)
    email = sa.Column(sa.Text)
    phone = sa.Column(sa.Text, index=True)
    occupation = sa.Column(sa.Text)
    address = sa.Column(sa.Text)

    student_links = orm.relationship(
        "StudentGuardian", back_populates="guardian", cascade="all, delete-orphan"
    )

    __table_args__ = (sa.Index("ix_guardians_school_phone", "school_id", "phone"),)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "occupation": self.occupation,
            "address": self.address,
            "user_id": str(self.user_id) if self.user_id else None,
        }


class StudentGuardian(TenantModel):
    """Split families are normal: many guardians per student, many students per guardian."""

    __tablename__ = "student_guardians"

    student_id = sa.Column(
        sa.Uuid, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    guardian_id = sa.Column(
        sa.Uuid, sa.ForeignKey("guardians.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type = sa.Column(sa.Text, nullable=False, default="guardian")
    is_primary_contact = sa.Column(sa.Boolean, nullable=False, default=False)
    can_pick_up = sa.Column(sa.Boolean, nullable=False, default=True)

    student = orm.relationship("Student", back_populates="guardian_links")
    guardian = orm.relationship("Guardian", back_populates="student_links")

    __table_args__ = (
        sa.UniqueConstraint("school_id", "student_id", "guardian_id", name="uq_student_guardian"),
        sa.Index("ix_student_guardians_guardian", "school_id", "guardian_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "student_id": str(self.student_id),
            "guardian_id": str(self.guardian_id),
            "relationship_type": self.relationship_type,
            "is_primary_contact": self.is_primary_contact,
            "can_pick_up": self.can_pick_up,
        }


class Staff(TenantModel, SoftDeletable, Authored):
    __tablename__ = "staff"

    user_id = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))
    staff_code = sa.Column(sa.Text, nullable=False)
    first_name = sa.Column(sa.Text, nullable=False)
    last_name = sa.Column(sa.Text, nullable=False)
    email = sa.Column(sa.Text)
    phone = sa.Column(sa.Text)
    department = sa.Column(sa.Text)
    qualification = sa.Column(sa.Text)
    hired_on = sa.Column(sa.Date)
    status = sa.Column(sa.Text, nullable=False, default="active")

    __table_args__ = (
        sa.UniqueConstraint("school_id", "staff_code", name="uq_staff_school_code"),
        sa.CheckConstraint("status in ('active','suspended','left')", name="ck_staff_status"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "staff_code": self.staff_code,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "department": self.department,
            "qualification": self.qualification,
            "hired_on": self.hired_on.isoformat() if self.hired_on else None,
            "status": self.status,
            "user_id": str(self.user_id) if self.user_id else None,
        }


class ImportJob(TenantModel):
    """Bulk import with a dry-run validation pass before anything is written."""

    __tablename__ = "import_jobs"

    entity_type = sa.Column(sa.Text, nullable=False)
    status = sa.Column(sa.Text, nullable=False, default="validated")
    total_rows = sa.Column(sa.Integer, nullable=False, default=0)
    valid_rows = sa.Column(sa.Integer, nullable=False, default=0)
    error_rows = sa.Column(sa.Integer, nullable=False, default=0)
    errors = sa.Column(JSON, nullable=False, default=list)
    payload = sa.Column(JSON, nullable=False, default=list)
    committed_at = sa.Column(sa.DateTime(timezone=True))
    created_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))

    def to_dict(self, include_payload: bool = False) -> dict:
        data = {
            "id": str(self.id),
            "entity_type": self.entity_type,
            "status": self.status,
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "error_rows": self.error_rows,
            "errors": self.errors or [],
            "committed_at": self.committed_at.isoformat() if self.committed_at else None,
        }
        if include_payload:
            data["payload"] = self.payload
        return data
