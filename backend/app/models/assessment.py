"""M7 -- Assessment configuration and computed results.

Nothing in here encodes a curriculum. Components, weights, maxima, bands,
rounding, tie rules and aggregation are all rows and columns the school owns.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import orm

from .base import JSON, TenantModel

COMPONENT_SCOPES = ("term", "year")
ROUNDING_MODES = ("none", "half_up", "half_even")
MISSING_SCORE_RULES = ("treat_as_zero", "exclude_from_ranking")
ABSENT_RULES = ("treat_as_zero", "ignore_and_reweight", "block_computation", "exclude_from_ranking")
POSITION_BASES = ("total_score", "points")
POSITION_SCOPES = ("class", "section", "level", "year_group")
TIE_RULES = ("shared_position", "sequential")
AGGREGATE_METHODS = ("mean_of_totals", "sum_of_best_n_points", "weighted_mean")
WEIGHT_INTERPRETATIONS = ("percentage", "points")


class AssessmentComponent(TenantModel):
    """What a school records: "Class Test", "Project", "Exam", "Coursework"..."""

    __tablename__ = "assessment_components"

    name = sa.Column(sa.Text, nullable=False)
    code = sa.Column(sa.Text, nullable=False)
    weight = sa.Column(sa.Numeric(10, 4), nullable=False)
    max_score = sa.Column(sa.Numeric(10, 4), nullable=False)
    sequence = sa.Column(sa.Integer, nullable=False, default=0)
    applies_to = sa.Column(JSON, nullable=False, default=dict)  # all subjects, or a list
    scope = sa.Column(sa.Text, nullable=False, default="term")
    is_active = sa.Column(sa.Boolean, nullable=False, default=True)

    __table_args__ = (
        sa.UniqueConstraint("school_id", "code", name="uq_assessment_components_school_code"),
        sa.CheckConstraint("scope in ('term','year')", name="ck_components_scope"),
        sa.CheckConstraint("max_score > 0", name="ck_components_max_score"),
    )

    def applies_to_subject(self, subject_id: str | None) -> bool:
        rule = self.applies_to or {}
        if not rule or rule.get("all", True) and "subject_ids" not in rule:
            return True
        subject_ids = rule.get("subject_ids") or []
        return not subject_ids or str(subject_id) in [str(s) for s in subject_ids]

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "code": self.code,
            "weight": float(self.weight),
            "max_score": float(self.max_score),
            "sequence": self.sequence,
            "applies_to": self.applies_to or {},
            "scope": self.scope,
            "is_active": self.is_active,
        }


class GradeScale(TenantModel):
    __tablename__ = "grade_scales"

    name = sa.Column(sa.Text, nullable=False)
    applies_to = sa.Column(JSON, nullable=False, default=dict)  # levels/subjects governed
    is_default = sa.Column(sa.Boolean, nullable=False, default=False)

    bands = orm.relationship(
        "GradeBand",
        back_populates="grade_scale",
        order_by="GradeBand.sequence",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (sa.UniqueConstraint("school_id", "name", name="uq_grade_scales_school_name"),)

    def to_dict(self, include_bands: bool = True) -> dict:
        data = {
            "id": str(self.id),
            "name": self.name,
            "applies_to": self.applies_to or {},
            "is_default": self.is_default,
        }
        if include_bands:
            data["bands"] = [b.to_dict() for b in self.bands]
        return data


class GradeBand(TenantModel):
    """A score range mapped to a grade label, a remark and optional points.

    ``grade`` is free text on purpose: A1-F9, 9-1, A*-G and descriptive bands
    are all just rows.
    """

    __tablename__ = "grade_bands"

    grade_scale_id = sa.Column(
        sa.Uuid, sa.ForeignKey("grade_scales.id", ondelete="CASCADE"), nullable=False
    )
    min_score = sa.Column(sa.Numeric(10, 4), nullable=False)
    max_score = sa.Column(sa.Numeric(10, 4), nullable=False)
    grade = sa.Column(sa.Text, nullable=False)
    remark = sa.Column(sa.Text)
    points = sa.Column(sa.Numeric(10, 4))
    sequence = sa.Column(sa.Integer, nullable=False, default=0)

    grade_scale = orm.relationship("GradeScale", back_populates="bands")

    __table_args__ = (
        sa.CheckConstraint("min_score <= max_score", name="ck_grade_bands_range"),
        sa.Index("ix_grade_bands_scale", "school_id", "grade_scale_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "grade_scale_id": str(self.grade_scale_id),
            "min_score": float(self.min_score),
            "max_score": float(self.max_score),
            "grade": self.grade,
            "remark": self.remark,
            "points": float(self.points) if self.points is not None else None,
            "sequence": self.sequence,
        }


class AssessmentSettings(TenantModel):
    """The configuration surface the results engine must honour (spec M7)."""

    __tablename__ = "assessment_settings"

    weight_interpretation = sa.Column(sa.Text, nullable=False, default="percentage")
    rounding_mode = sa.Column(sa.Text, nullable=False, default="half_up")
    rounding_decimals = sa.Column(sa.Integer, nullable=False, default=0)
    missing_score_rule = sa.Column(sa.Text, nullable=False, default="treat_as_zero")
    absent_rule = sa.Column(sa.Text, nullable=False, default="treat_as_zero")
    position_basis = sa.Column(sa.Text, nullable=False, default="total_score")
    position_scope = sa.Column(sa.Text, nullable=False, default="class")
    tie_rule = sa.Column(sa.Text, nullable=False, default="shared_position")
    aggregate_method = sa.Column(sa.Text, nullable=False, default="mean_of_totals")
    best_n = sa.Column(sa.Integer)
    best_n_compulsory_subject_ids = sa.Column(JSON, nullable=False, default=list)
    pass_mark = sa.Column(sa.Numeric(10, 4), nullable=False, default=40)
    require_approval_before_publish = sa.Column(sa.Boolean, nullable=False, default=True)

    __table_args__ = (
        sa.UniqueConstraint("school_id", name="uq_assessment_settings_school"),
        sa.CheckConstraint(
            "rounding_mode in ('none','half_up','half_even')", name="ck_settings_rounding"
        ),
        sa.CheckConstraint(
            "aggregate_method in ('mean_of_totals','sum_of_best_n_points','weighted_mean')",
            name="ck_settings_aggregate",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "weight_interpretation": self.weight_interpretation,
            "rounding": {"mode": self.rounding_mode, "decimals": self.rounding_decimals},
            "missing_score": self.missing_score_rule,
            "absent_handling": self.absent_rule,
            "position_basis": self.position_basis,
            "position_scope": self.position_scope,
            "tie_rule": self.tie_rule,
            "aggregate_method": self.aggregate_method,
            "best_n": self.best_n,
            "best_n_compulsory_subject_ids": self.best_n_compulsory_subject_ids or [],
            "pass_mark": float(self.pass_mark),
            "require_approval_before_publish": self.require_approval_before_publish,
        }


class AssessmentScore(TenantModel):
    """The raw marks a teacher enters."""

    __tablename__ = "assessment_scores"

    student_id = sa.Column(
        sa.Uuid, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    subject_id = sa.Column(
        sa.Uuid, sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    term_id = sa.Column(sa.Uuid, sa.ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False)
    component_id = sa.Column(
        sa.Uuid, sa.ForeignKey("assessment_components.id", ondelete="RESTRICT"), nullable=False
    )
    raw_score = sa.Column(sa.Numeric(10, 4))  # null means not yet marked, which is not zero
    is_absent = sa.Column(sa.Boolean, nullable=False, default=False)
    entered_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))
    entered_at = sa.Column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.UniqueConstraint(
            "school_id",
            "student_id",
            "subject_id",
            "term_id",
            "component_id",
            name="uq_assessment_score_slot",
        ),
        sa.Index("ix_scores_school_class_term", "school_id", "class_id", "term_id"),
        sa.Index(
            "ix_scores_school_class_subject_term", "school_id", "class_id", "subject_id", "term_id"
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "student_id": str(self.student_id),
            "subject_id": str(self.subject_id),
            "class_id": str(self.class_id),
            "term_id": str(self.term_id),
            "component_id": str(self.component_id),
            "raw_score": float(self.raw_score) if self.raw_score is not None else None,
            "is_absent": self.is_absent,
            "entered_at": self.entered_at.isoformat() if self.entered_at else None,
        }


class Result(TenantModel):
    """The computed output, materialised.

    Positions need the whole class, and a report card must be reproducible years
    later even if configuration has since changed. So we compute on write.
    """

    __tablename__ = "results"

    student_id = sa.Column(
        sa.Uuid, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    subject_id = sa.Column(
        sa.Uuid, sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    term_id = sa.Column(sa.Uuid, sa.ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False)

    total_score = sa.Column(sa.Numeric(10, 4))
    grade = sa.Column(sa.Text)
    remark = sa.Column(sa.Text)
    points = sa.Column(sa.Numeric(10, 4))
    subject_position = sa.Column(sa.Integer)
    is_ranked = sa.Column(sa.Boolean, nullable=False, default=True)
    component_breakdown = sa.Column(JSON, nullable=False, default=dict)
    computed_at = sa.Column(sa.DateTime(timezone=True))

    is_approved = sa.Column(sa.Boolean, nullable=False, default=False)
    approved_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = sa.Column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.UniqueConstraint(
            "school_id", "student_id", "subject_id", "term_id", name="uq_results_slot"
        ),
        sa.Index("ix_results_school_student_term", "school_id", "student_id", "term_id"),
        sa.Index("ix_results_school_class_term", "school_id", "class_id", "term_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "student_id": str(self.student_id),
            "subject_id": str(self.subject_id),
            "class_id": str(self.class_id),
            "term_id": str(self.term_id),
            "total_score": float(self.total_score) if self.total_score is not None else None,
            "grade": self.grade,
            "remark": self.remark,
            "points": float(self.points) if self.points is not None else None,
            "subject_position": self.subject_position,
            "is_ranked": self.is_ranked,
            "component_breakdown": self.component_breakdown or {},
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
            "is_approved": self.is_approved,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
        }


class TermResult(TenantModel):
    """Per-student, per-term aggregate: the overall figure and class position."""

    __tablename__ = "term_results"

    student_id = sa.Column(
        sa.Uuid, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    term_id = sa.Column(sa.Uuid, sa.ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False)

    aggregate = sa.Column(sa.Numeric(10, 4))
    aggregate_method = sa.Column(sa.Text)
    subjects_counted = sa.Column(sa.Integer, nullable=False, default=0)
    overall_position = sa.Column(sa.Integer)
    class_size = sa.Column(sa.Integer, nullable=False, default=0)
    is_ranked = sa.Column(sa.Boolean, nullable=False, default=True)
    computed_at = sa.Column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.UniqueConstraint("school_id", "student_id", "term_id", name="uq_term_results_slot"),
        sa.Index("ix_term_results_school_class_term", "school_id", "class_id", "term_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "student_id": str(self.student_id),
            "class_id": str(self.class_id),
            "term_id": str(self.term_id),
            "aggregate": float(self.aggregate) if self.aggregate is not None else None,
            "aggregate_method": self.aggregate_method,
            "subjects_counted": self.subjects_counted,
            "overall_position": self.overall_position,
            "class_size": self.class_size,
            "is_ranked": self.is_ranked,
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
        }


class ResultRemark(TenantModel):
    """Teacher and head-teacher comments; AI drafts land here only once saved."""

    __tablename__ = "result_remarks"

    student_id = sa.Column(
        sa.Uuid, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    term_id = sa.Column(sa.Uuid, sa.ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False)
    author_role = sa.Column(sa.Text, nullable=False, default="teacher")  # teacher | head_teacher
    body = sa.Column(sa.Text, nullable=False)
    is_ai_assisted = sa.Column(sa.Boolean, nullable=False, default=False)
    written_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        sa.UniqueConstraint(
            "school_id", "student_id", "term_id", "author_role", name="uq_result_remarks_slot"
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "student_id": str(self.student_id),
            "term_id": str(self.term_id),
            "author_role": self.author_role,
            "body": self.body,
            "is_ai_assisted": self.is_ai_assisted,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
