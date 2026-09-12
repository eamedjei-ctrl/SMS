"""M8 -- report card templates, generation and download."""

from __future__ import annotations

import os

from flask import Blueprint, Response

from ..extensions import db
from ..models import GeneratedReportCard, ReportCardJob, ReportCardTemplate, Term
from ..security import current_user, requires
from ..services import report_card_service
from ..services.audit_service import diff, record
from ..services.scope_service import assert_can_access_class, assert_can_access_student
from ..tenancy import current_school_id
from ..utils.errors import invalid_state, not_found
from ..utils.responses import accepted, body, created, ok
from ..utils.validation import Validator, arg_uuid

bp = Blueprint("reportcards", __name__)


def _term_or_current(term_id=None) -> Term:
    term = (
        Term.query.filter_by(id=term_id).first()
        if term_id
        else Term.query.filter_by(is_current=True).first()
    )
    if term is None:
        raise not_found("Term")
    return term


# ==========================================================================
# Templates
# ==========================================================================
@bp.get("/report-cards/templates")
@requires("reportcards.download")
def list_templates():
    templates = ReportCardTemplate.query.order_by(ReportCardTemplate.name).all()
    return ok([t.to_dict() for t in templates])


@bp.post("/report-cards/templates")
@requires("reportcards.configure")
def create_template():
    payload = body()
    validator = Validator(payload)
    name = validator.string("name", required=True, max_length=120)
    template_key = validator.string("template_key", default="standard", max_length=60)
    is_default = validator.boolean("is_default", default=False)
    validator.string("header_text", max_length=500)
    validator.string("footer_text", max_length=500)
    for flag in (
        "show_position",
        "show_class_average",
        "show_attendance",
        "show_teacher_remark",
        "show_head_remark",
        "show_grade_key",
        "show_component_breakdown",
    ):
        validator.boolean(flag, default=True)
    validator.sequence("signature_blocks", default=[])
    data = validator.raise_if_invalid()

    if is_default:
        for template in ReportCardTemplate.query.filter_by(is_default=True).all():
            template.is_default = False

    template = ReportCardTemplate(
        school_id=current_school_id(),
        name=name,
        template_key=template_key,
        is_default=is_default or ReportCardTemplate.query.first() is None,
        header_text=data.get("header_text"),
        footer_text=data.get("footer_text"),
        show_position=data["show_position"],
        show_class_average=data["show_class_average"],
        show_attendance=data["show_attendance"],
        show_teacher_remark=data["show_teacher_remark"],
        show_head_remark=data["show_head_remark"],
        show_grade_key=data["show_grade_key"],
        show_component_breakdown=data["show_component_breakdown"],
        signature_blocks=[str(s) for s in (data.get("signature_blocks") or [])],
    )
    db.session.add(template)
    db.session.flush()
    record("create", "report_card_template", template.id, new_values=template.to_dict())
    db.session.commit()
    return created(template.to_dict())


@bp.patch("/report-cards/templates/<uuid:template_id>")
@requires("reportcards.configure")
def update_template(template_id):
    template = ReportCardTemplate.query.filter_by(id=template_id).first()
    if template is None:
        raise not_found("Report card template")
    before = template.to_dict()

    payload = body()
    validator = Validator(payload)
    for field in ("name", "template_key", "header_text", "footer_text"):
        if field in payload:
            validator.string(field, max_length=500)
    for flag in (
        "show_position",
        "show_class_average",
        "show_attendance",
        "show_teacher_remark",
        "show_head_remark",
        "show_grade_key",
        "show_component_breakdown",
        "is_default",
    ):
        if flag in payload:
            validator.boolean(flag)
    if "signature_blocks" in payload:
        validator.sequence("signature_blocks")
    data = validator.raise_if_invalid()

    if data.get("is_default"):
        for other in ReportCardTemplate.query.filter_by(is_default=True).all():
            other.is_default = False

    for field, value in data.items():
        if field in payload:
            if field == "signature_blocks":
                value = [str(v) for v in (value or [])]
            setattr(template, field, value)
    db.session.flush()

    old_values, new_values = diff(before, template.to_dict())
    record(
        "update",
        "report_card_template",
        template.id,
        old_values=old_values,
        new_values=new_values,
    )
    db.session.commit()
    return ok(template.to_dict())


# ==========================================================================
# Preview and generation
# ==========================================================================
@bp.get("/report-cards/preview")
@requires("reportcards.generate")
def preview():
    """The assembled data, before anyone commits to a batch of PDFs."""
    student_id = arg_uuid("student_id")
    if not student_id:
        raise invalid_state("student_id is required.")
    student = assert_can_access_student(student_id, "reportcards.generate")
    term = _term_or_current(arg_uuid("term_id"))

    template = None
    template_id = arg_uuid("template_id")
    if template_id:
        template = ReportCardTemplate.query.filter_by(id=template_id).first()

    payload = report_card_service.build_payload(student.id, term.id, template)
    return ok(payload)


@bp.post("/report-cards/generate")
@requires("reportcards.generate")
def generate():
    """One student, or a whole class as a job (spec 6.7)."""
    payload = body()
    validator = Validator(payload)
    student_id = validator.uuid("student_id")
    class_id = validator.uuid("class_id")
    term_id = validator.uuid("term_id")
    validator.raise_if_invalid()

    if not student_id and not class_id:
        raise invalid_state("Provide either student_id or class_id.")

    term = _term_or_current(term_id)

    if student_id:
        assert_can_access_student(student_id, "reportcards.generate")
        card = report_card_service.generate_for_student(
            student_id, term.id, user_id=current_user().id
        )
        record("create", "report_card", card.id, new_values={"term_id": str(term.id)})
        db.session.commit()
        return created(card.to_dict())

    assert_can_access_class(class_id, "reportcards.generate")
    job = report_card_service.generate_for_class(class_id, term.id, user_id=current_user().id)
    record(
        "create",
        "report_card_job",
        job.id,
        new_values={"class_id": str(class_id), "total": job.total, "status": job.status},
    )
    db.session.commit()
    return accepted(job.to_dict())


@bp.get("/jobs/<uuid:job_id>")
@requires("reportcards.generate")
def job_status(job_id):
    job = ReportCardJob.query.filter_by(id=job_id).first()
    if job is None:
        raise not_found("Job")
    return ok(job.to_dict())


# ==========================================================================
# Retrieval
# ==========================================================================
@bp.get("/report-cards")
@requires("reportcards.download")
def list_cards():
    query = GeneratedReportCard.query
    class_id = arg_uuid("class_id")
    student_id = arg_uuid("student_id")
    term_id = arg_uuid("term_id")
    if class_id:
        assert_can_access_class(class_id, "reportcards.download")
        query = query.filter(GeneratedReportCard.class_id == class_id)
    if student_id:
        assert_can_access_student(student_id, "reportcards.download")
        query = query.filter(GeneratedReportCard.student_id == student_id)
    if term_id:
        query = query.filter(GeneratedReportCard.term_id == term_id)

    cards = query.order_by(GeneratedReportCard.created_at.desc()).limit(200).all()
    return ok([card.to_dict() for card in cards])


@bp.get("/report-cards/<uuid:card_id>")
@requires("reportcards.download")
def get_card(card_id):
    card = GeneratedReportCard.query.filter_by(id=card_id).first()
    if card is None:
        raise not_found("Report card")
    assert_can_access_student(card.student_id, "reportcards.download")
    return ok(card.to_dict(include_payload=True))


@bp.get("/report-cards/<uuid:card_id>/download")
@requires("reportcards.download")
def download_card(card_id):
    """Serve the PDF through an authorised endpoint, never from the web root."""
    card = GeneratedReportCard.query.filter_by(id=card_id).first()
    if card is None:
        raise not_found("Report card")
    assert_can_access_student(card.student_id, "reportcards.download")

    pdf_bytes = None
    if card.file_path and os.path.exists(card.file_path):
        with open(card.file_path, "rb") as handle:
            pdf_bytes = handle.read()
    elif card.payload:
        # Storage is unavailable or was cleared: rebuild from the frozen payload.
        pdf_bytes = report_card_service.render_pdf(card.payload)

    if pdf_bytes is None:
        raise not_found("Report card file")

    record("export", "report_card", card.id)
    db.session.commit()

    filename = f"report-card-{card.student_id}-{card.term_id}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
