"""M8 -- Report cards."""

from __future__ import annotations

import sqlalchemy as sa

from .base import JSON, TenantModel


class ReportCardTemplate(TenantModel):
    """Layout, sections, signatures and footer are configuration, not code."""

    __tablename__ = "report_card_templates"

    name = sa.Column(sa.Text, nullable=False)
    template_key = sa.Column(sa.Text, nullable=False, default="standard")
    is_default = sa.Column(sa.Boolean, nullable=False, default=False)
    header_text = sa.Column(sa.Text)
    footer_text = sa.Column(sa.Text)
    show_position = sa.Column(sa.Boolean, nullable=False, default=True)
    show_class_average = sa.Column(sa.Boolean, nullable=False, default=True)
    show_attendance = sa.Column(sa.Boolean, nullable=False, default=True)
    show_teacher_remark = sa.Column(sa.Boolean, nullable=False, default=True)
    show_head_remark = sa.Column(sa.Boolean, nullable=False, default=True)
    show_grade_key = sa.Column(sa.Boolean, nullable=False, default=True)
    show_component_breakdown = sa.Column(sa.Boolean, nullable=False, default=True)
    signature_blocks = sa.Column(JSON, nullable=False, default=list)
    extra = sa.Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        sa.UniqueConstraint("school_id", "name", name="uq_report_card_templates_school_name"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "template_key": self.template_key,
            "is_default": self.is_default,
            "header_text": self.header_text,
            "footer_text": self.footer_text,
            "show_position": self.show_position,
            "show_class_average": self.show_class_average,
            "show_attendance": self.show_attendance,
            "show_teacher_remark": self.show_teacher_remark,
            "show_head_remark": self.show_head_remark,
            "show_grade_key": self.show_grade_key,
            "show_component_breakdown": self.show_component_breakdown,
            "signature_blocks": self.signature_blocks or [],
            "extra": self.extra or {},
        }


class GeneratedReportCard(TenantModel):
    """One produced card. ``payload`` is the frozen data the PDF was built from."""

    __tablename__ = "generated_report_cards"

    student_id = sa.Column(
        sa.Uuid, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    term_id = sa.Column(sa.Uuid, sa.ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False)
    template_id = sa.Column(sa.Uuid, sa.ForeignKey("report_card_templates.id", ondelete="SET NULL"))
    payload = sa.Column(JSON, nullable=False, default=dict)
    file_path = sa.Column(sa.Text)
    file_size = sa.Column(sa.Integer)
    version = sa.Column(sa.Integer, nullable=False, default=1)
    generated_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        sa.UniqueConstraint(
            "school_id", "student_id", "term_id", name="uq_generated_report_cards_slot"
        ),
        sa.Index("ix_generated_cards_school_class_term", "school_id", "class_id", "term_id"),
    )

    def to_dict(self, include_payload: bool = False) -> dict:
        data = {
            "id": str(self.id),
            "student_id": str(self.student_id),
            "class_id": str(self.class_id),
            "term_id": str(self.term_id),
            "template_id": str(self.template_id) if self.template_id else None,
            "version": self.version,
            "file_size": self.file_size,
            "has_file": bool(self.file_path),
            "generated_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_payload:
            data["payload"] = self.payload
        return data


class ReportCardJob(TenantModel):
    """Batch generation runs asynchronously and reports progress (spec 6.7)."""

    __tablename__ = "report_card_jobs"

    class_id = sa.Column(sa.Uuid, sa.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    term_id = sa.Column(sa.Uuid, sa.ForeignKey("terms.id", ondelete="RESTRICT"), nullable=False)
    status = sa.Column(sa.Text, nullable=False, default="queued")
    total = sa.Column(sa.Integer, nullable=False, default=0)
    completed = sa.Column(sa.Integer, nullable=False, default=0)
    failed = sa.Column(sa.Integer, nullable=False, default=0)
    failure_reason = sa.Column(sa.Text)
    result = sa.Column(JSON, nullable=False, default=dict)
    requested_by = sa.Column(sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"))
    finished_at = sa.Column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.CheckConstraint(
            "status in ('queued','processing','completed','failed','partial')",
            name="ck_report_card_jobs_status",
        ),
    )

    @property
    def progress(self) -> int:
        if not self.total:
            return 0
        return int(round((self.completed + self.failed) / self.total * 100))

    def to_dict(self) -> dict:
        return {
            "job_id": str(self.id),
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "failure_reason": self.failure_reason,
            "result": self.result or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
