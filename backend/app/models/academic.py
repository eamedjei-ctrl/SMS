"""M4 -- Academic structure: years, terms, classes, subjects, teaching assignments."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import orm

from .base import SoftDeletable, TenantModel


class AcademicYear(TenantModel, SoftDeletable):
    __tablename__ = "academic_years"

    name = sa.Column(sa.Text, nullable=False)  # "2026/2027" -- schools name these differently
    start_date = sa.Column(sa.Date)
    end_date = sa.Column(sa.Date)
    is_current = sa.Column(sa.Boolean, nullable=False, default=False)

    terms = orm.relationship(
        "Term", back_populates="academic_year", order_by="Term.sequence", lazy="selectin"
    )

    __table_args__ = (
        sa.UniqueConstraint("school_id", "name", name="uq_academic_years_school_name"),
        sa.Index("ix_academic_years_school_current", "school_id", "is_current"),
    )

    def to_dict(self, include_terms: bool = False) -> dict:
        data = {
            "id": str(self.id),
            "name": self.name,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "is_current": self.is_current,
        }
        if include_terms:
            data["terms"] = [t.to_dict() for t in self.terms]
        return data


class Term(TenantModel, SoftDeletable):
    __tablename__ = "terms"

    academic_year_id = sa.Column(
        sa.Uuid, sa.ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False
    )
    name = sa.Column(sa.Text, nullable=False)  # "Term 1", "Michaelmas", "Semester 1"
    sequence = sa.Column(sa.Integer, nullable=False, default=1)
    start_date = sa.Column(sa.Date)
    end_date = sa.Column(sa.Date)
    is_current = sa.Column(sa.Boolean, nullable=False, default=False)
    results_locked = sa.Column(sa.Boolean, nullable=False, default=False)
    locked_at = sa.Column(sa.DateTime(timezone=True))
    locked_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))

    academic_year = orm.relationship("AcademicYear", back_populates="terms")

    __table_args__ = (
        sa.UniqueConstraint(
            "school_id", "academic_year_id", "sequence", name="uq_terms_year_sequence"
        ),
        sa.Index("ix_terms_school_current", "school_id", "is_current"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "academic_year_id": str(self.academic_year_id),
            "name": self.name,
            "sequence": self.sequence,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "is_current": self.is_current,
            "results_locked": self.results_locked,
        }


class Subject(TenantModel, SoftDeletable):
    __tablename__ = "subjects"

    name = sa.Column(sa.Text, nullable=False)
    code = sa.Column(sa.Text, nullable=False)
    is_core = sa.Column(sa.Boolean, nullable=False, default=True)
    is_active = sa.Column(sa.Boolean, nullable=False, default=True)
    sequence = sa.Column(sa.Integer, nullable=False, default=0)

    __table_args__ = (sa.UniqueConstraint("school_id", "code", name="uq_subjects_school_code"),)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "code": self.code,
            "is_core": self.is_core,
            "is_active": self.is_active,
            "sequence": self.sequence,
        }


class SchoolClass(TenantModel, SoftDeletable):
    """A class/form/year group. Distinct from a student's membership of it."""

    __tablename__ = "classes"

    academic_year_id = sa.Column(
        sa.Uuid, sa.ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False
    )
    name = sa.Column(sa.Text, nullable=False)  # "Basic 3", "Year 7", "Form 2 Science"
    level = sa.Column(sa.Integer, nullable=False, default=1)  # promotion ordering
    section = sa.Column(sa.Text)
    class_teacher_id = sa.Column(sa.Uuid, sa.ForeignKey("staff.id", ondelete="SET NULL"))
    capacity = sa.Column(sa.Integer)
    curriculum = sa.Column(sa.Text)  # overrides school default for hybrid schools

    class_subjects = orm.relationship(
        "ClassSubject", back_populates="school_class", cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "school_id", "academic_year_id", "name", "section", name="uq_classes_year_name_section"
        ),
        sa.Index("ix_classes_school_year", "school_id", "academic_year_id"),
        sa.Index("ix_classes_school_level", "school_id", "level"),
    )

    @property
    def display_name(self) -> str:
        return f"{self.name} {self.section}".strip() if self.section else self.name

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "academic_year_id": str(self.academic_year_id),
            "name": self.name,
            "display_name": self.display_name,
            "level": self.level,
            "section": self.section,
            "class_teacher_id": str(self.class_teacher_id) if self.class_teacher_id else None,
            "capacity": self.capacity,
            "curriculum": self.curriculum,
        }


class ClassSubject(TenantModel):
    """A subject attached to a class."""

    __tablename__ = "class_subjects"

    class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    subject_id = sa.Column(
        sa.Uuid, sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    is_elective = sa.Column(sa.Boolean, nullable=False, default=False)
    grade_scale_id = sa.Column(
        sa.Uuid, sa.ForeignKey("grade_scales.id", ondelete="SET NULL")
    )  # per-subject scale override

    school_class = orm.relationship("SchoolClass", back_populates="class_subjects")
    subject = orm.relationship("Subject", lazy="joined")
    teachers = orm.relationship(
        "ClassSubjectTeacher", back_populates="class_subject", cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.UniqueConstraint("school_id", "class_id", "subject_id", name="uq_class_subject"),
        sa.Index("ix_class_subjects_school_class", "school_id", "class_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "class_id": str(self.class_id),
            "subject_id": str(self.subject_id),
            "subject_name": self.subject.name if self.subject else None,
            "subject_code": self.subject.code if self.subject else None,
            "is_elective": self.is_elective,
            "grade_scale_id": str(self.grade_scale_id) if self.grade_scale_id else None,
            "teacher_ids": [str(t.staff_id) for t in self.teachers],
        }


class ClassSubjectTeacher(TenantModel):
    """Who teaches what. The basis of every ``own scope only`` permission check."""

    __tablename__ = "class_subject_teachers"

    class_subject_id = sa.Column(
        sa.Uuid, sa.ForeignKey("class_subjects.id", ondelete="CASCADE"), nullable=False
    )
    staff_id = sa.Column(sa.Uuid, sa.ForeignKey("staff.id", ondelete="CASCADE"), nullable=False)
    is_primary = sa.Column(sa.Boolean, nullable=False, default=True)

    class_subject = orm.relationship("ClassSubject", back_populates="teachers")

    __table_args__ = (
        sa.UniqueConstraint(
            "school_id", "class_subject_id", "staff_id", name="uq_class_subject_teacher"
        ),
        sa.Index("ix_class_subject_teachers_staff", "school_id", "staff_id"),
    )
