"""M8 -- Report cards.

The card is the artefact parents judge the school by, so the data is frozen at
generation time into ``payload``: a card reprinted in two years shows what it
showed the day it was issued, even if configuration has since changed.
"""

from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import current_app

from ..extensions import db
from ..models import (
    AttendanceRecord,
    AttendanceStatus,
    ClassSubject,
    Enrollment,
    GeneratedReportCard,
    GradeScale,
    ReportCardJob,
    ReportCardTemplate,
    Result,
    ResultRemark,
    School,
    SchoolClass,
    Staff,
    Student,
    Term,
    TermResult,
)
from ..tenancy import current_school_id, unscoped
from ..utils.errors import invalid_state, not_found


def default_template() -> ReportCardTemplate | None:
    return (
        ReportCardTemplate.query.filter_by(is_default=True).first()
        or ReportCardTemplate.query.first()
    )


def _attendance_summary(student_id, term_id) -> dict:
    statuses = {s.code: s for s in AttendanceStatus.query.all()}
    records = AttendanceRecord.query.filter_by(student_id=student_id, term_id=term_id).all()
    present = sum(
        1
        for r in records
        if r.status_code in statuses and statuses[r.status_code].counts_as_present
    )
    total = len(records)
    return {
        "days_marked": total,
        "days_present": present,
        "days_absent": total - present,
        "rate": round(present / total * 100, 1) if total else None,
    }


def build_payload(student_id, term_id, template: ReportCardTemplate | None = None) -> dict:
    """Assemble everything the card shows, resolved to plain values."""
    template = template or default_template()

    student = Student.query.filter_by(id=student_id).first()
    if student is None:
        raise not_found("Student")
    term = Term.query.filter_by(id=term_id).first()
    if term is None:
        raise not_found("Term")

    enrollment = Enrollment.query.filter_by(student_id=student.id, status="active").first()
    if enrollment is None:
        raise invalid_state("This student is not enrolled in a class.")
    school_class = SchoolClass.query.filter_by(id=enrollment.class_id).first()

    with unscoped():  # platform tier: the school registry is not tenant-owned
        school = School.query.filter_by(id=current_school_id()).first()

    results = Result.query.filter_by(student_id=student.id, term_id=term.id).all()
    subject_names = {
        cs.subject_id: (cs.subject.name if cs.subject else None)
        for cs in ClassSubject.query.filter_by(class_id=school_class.id).all()
    }

    # Class averages per subject, so a parent can place the child in context.
    class_averages: dict[str, float] = {}
    if template is None or template.show_class_average:
        peer_rows = Result.query.filter_by(class_id=school_class.id, term_id=term.id).all()
        buckets: dict[str, list[Decimal]] = {}
        for row in peer_rows:
            if row.total_score is not None:
                buckets.setdefault(str(row.subject_id), []).append(row.total_score)
        class_averages = {
            subject_id: round(float(sum(values) / len(values)), 2)
            for subject_id, values in buckets.items()
            if values
        }

    term_result = TermResult.query.filter_by(student_id=student.id, term_id=term.id).first()
    remarks = {
        remark.author_role: remark.body
        for remark in ResultRemark.query.filter_by(student_id=student.id, term_id=term.id).all()
    }

    grade_key = []
    if template is None or template.show_grade_key:
        scale = GradeScale.query.filter_by(is_default=True).first() or GradeScale.query.first()
        if scale:
            grade_key = [
                {
                    "grade": band.grade,
                    "min_score": float(band.min_score),
                    "max_score": float(band.max_score),
                    "remark": band.remark,
                }
                for band in scale.bands
            ]

    class_teacher = None
    if school_class and school_class.class_teacher_id:
        staff = Staff.query.filter_by(id=school_class.class_teacher_id).first()
        class_teacher = staff.full_name if staff else None

    subjects = []
    for row in sorted(results, key=lambda r: subject_names.get(r.subject_id) or ""):
        subjects.append(
            {
                "subject_id": str(row.subject_id),
                "subject": subject_names.get(row.subject_id) or "-",
                "total_score": float(row.total_score) if row.total_score is not None else None,
                "grade": row.grade,
                "remark": row.remark,
                "points": float(row.points) if row.points is not None else None,
                "position": row.subject_position,
                "class_average": class_averages.get(str(row.subject_id)),
                "components": row.component_breakdown or {},
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "school": {
            "name": school.name if school else "",
            "address": school.address if school else None,
            "phone": school.phone if school else None,
            "email": school.email if school else None,
            "logo_url": school.logo_url if school else None,
        },
        "student": {
            "id": str(student.id),
            "name": student.full_name,
            "student_code": student.student_code,
            "gender": student.gender,
        },
        "class": {
            "id": str(school_class.id) if school_class else None,
            "name": school_class.display_name if school_class else None,
            "teacher": class_teacher,
            "size": term_result.class_size if term_result else None,
        },
        "term": {"id": str(term.id), "name": term.name, "sequence": term.sequence},
        "subjects": subjects,
        "summary": {
            "aggregate": (
                float(term_result.aggregate)
                if term_result and term_result.aggregate is not None
                else None
            ),
            "aggregate_method": term_result.aggregate_method if term_result else None,
            "subjects_counted": term_result.subjects_counted if term_result else 0,
            "overall_position": term_result.overall_position if term_result else None,
        },
        "attendance": _attendance_summary(student.id, term.id),
        "remarks": {
            "teacher": remarks.get("teacher"),
            "head_teacher": remarks.get("head_teacher"),
        },
        "grade_key": grade_key,
        "template": template.to_dict() if template else None,
    }


# --------------------------------------------------------------------------
# PDF rendering
# --------------------------------------------------------------------------
def render_pdf(payload: dict) -> bytes:
    """Server-side A4 PDF. Layout comes from the template configuration."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    template = payload.get("template") or {}
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CardTitle", parent=styles["Title"], fontSize=16, spaceAfter=2 * mm
    )
    small = ParagraphStyle("CardSmall", parent=styles["Normal"], fontSize=8.5, leading=11)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{payload['student']['name']} - {payload['term']['name']}",
    )

    story: list = []
    school = payload.get("school", {})
    story.append(Paragraph(school.get("name", ""), title_style))
    if template.get("header_text"):
        story.append(Paragraph(template["header_text"], small))
    if school.get("address"):
        story.append(Paragraph(school["address"], small))
    story.append(Spacer(1, 4 * mm))

    student = payload["student"]
    meta_rows = [
        ["Student", student["name"], "Student ID", student["student_code"]],
        [
            "Class",
            payload["class"].get("name") or "-",
            "Term",
            payload["term"]["name"],
        ],
    ]
    summary = payload.get("summary", {})
    if template.get("show_position", True):
        meta_rows.append(
            [
                "Position",
                _position_label(summary.get("overall_position"), payload["class"].get("size")),
                "Aggregate",
                _fmt(summary.get("aggregate")),
            ]
        )
    if template.get("show_attendance", True):
        attendance = payload.get("attendance", {})
        meta_rows.append(
            [
                "Attendance",
                f"{attendance.get('days_present', 0)}/{attendance.get('days_marked', 0)} days",
                "Rate",
                f"{attendance.get('rate')}%" if attendance.get("rate") is not None else "-",
            ]
        )

    meta_table = Table(meta_rows, colWidths=[25 * mm, 65 * mm, 25 * mm, 65 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#555555")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#DDDDDD")),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 5 * mm))

    # Component columns are whatever the school configured -- two or five.
    component_codes: list[str] = []
    for subject in payload.get("subjects", []):
        for code in (subject.get("components") or {}).keys():
            if code not in component_codes:
                component_codes.append(code)
    show_components = template.get("show_component_breakdown", True) and component_codes

    header = ["Subject"]
    if show_components:
        header += component_codes
    header += ["Total", "Grade", "Remark"]
    if template.get("show_position", True):
        header.append("Pos")
    if template.get("show_class_average", True):
        header.append("Class avg")

    rows = [header]
    for subject in payload.get("subjects", []):
        row = [subject["subject"]]
        if show_components:
            for code in component_codes:
                component = (subject.get("components") or {}).get(code) or {}
                row.append(_fmt(component.get("raw_score")))
        row += [
            _fmt(subject.get("total_score")),
            subject.get("grade") or "-",
            subject.get("remark") or "-",
        ]
        if template.get("show_position", True):
            row.append(str(subject.get("position") or "-"))
        if template.get("show_class_average", True):
            row.append(_fmt(subject.get("class_average")))
        rows.append(row)

    subject_table = Table(rows, repeatRows=1, hAlign="LEFT")
    subject_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3352")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F7F9")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(subject_table)
    story.append(Spacer(1, 5 * mm))

    remarks = payload.get("remarks", {})
    if template.get("show_teacher_remark", True) and remarks.get("teacher"):
        story.append(Paragraph(f"<b>Class teacher:</b> {remarks['teacher']}", small))
        story.append(Spacer(1, 2 * mm))
    if template.get("show_head_remark", True) and remarks.get("head_teacher"):
        story.append(Paragraph(f"<b>Head teacher:</b> {remarks['head_teacher']}", small))
        story.append(Spacer(1, 3 * mm))

    if template.get("show_grade_key", True) and payload.get("grade_key"):
        key_text = " &nbsp;|&nbsp; ".join(
            f"{band['grade']}: {_fmt(band['min_score'])}-{_fmt(band['max_score'])}"
            f"{' ' + band['remark'] if band.get('remark') else ''}"
            for band in payload["grade_key"]
        )
        story.append(Paragraph(f"<b>Grading key</b><br/>{key_text}", small))
        story.append(Spacer(1, 4 * mm))

    signatures = template.get("signature_blocks") or ["Class teacher", "Head teacher"]
    signature_row = [[f"{'_' * 26}<br/>{label}" for label in signatures]]
    signature_table = Table(
        [[Paragraph(cell, small) for cell in signature_row[0]]],
        colWidths=[(180 / max(len(signatures), 1)) * mm] * len(signatures),
    )
    signature_table.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 8)]))
    story.append(signature_table)

    if template.get("footer_text"):
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(template["footer_text"], small))

    doc.build(story)
    return buffer.getvalue()


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        return str(int(number)) if number == int(number) else f"{number:.2f}"
    return str(value)


def _position_label(position, class_size) -> str:
    if position is None:
        return "-"
    suffix = "th"
    if position % 100 not in (11, 12, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(position % 10, "th")
    label = f"{position}{suffix}"
    return f"{label} of {class_size}" if class_size else label


# --------------------------------------------------------------------------
# Storage and generation
# --------------------------------------------------------------------------
def _storage_dir() -> str | None:
    path = current_app.config.get("STORAGE_LOCAL_PATH")
    if not path:
        return None
    school_dir = os.path.join(path, "report_cards", str(current_school_id()))
    try:
        os.makedirs(school_dir, exist_ok=True)
    except OSError:
        current_app.logger.warning("report card storage unavailable at %s", school_dir)
        return None
    return school_dir


def generate_for_student(student_id, term_id, template=None, user_id=None) -> GeneratedReportCard:
    template = template or default_template()
    payload = build_payload(student_id, term_id, template)
    pdf_bytes = render_pdf(payload)

    record = GeneratedReportCard.query.filter_by(student_id=student_id, term_id=term_id).first()
    if record is None:
        record = GeneratedReportCard(
            school_id=current_school_id(),
            student_id=student_id,
            term_id=term_id,
            class_id=uuid.UUID(payload["class"]["id"]),
            version=0,
        )
        db.session.add(record)

    directory = _storage_dir()
    if directory:
        filename = f"{student_id}_{term_id}.pdf"
        full_path = os.path.join(directory, filename)
        with open(full_path, "wb") as handle:
            handle.write(pdf_bytes)
        record.file_path = full_path

    record.template_id = template.id if template else None
    record.payload = payload
    record.file_size = len(pdf_bytes)
    record.version = (record.version or 0) + 1
    record.generated_by = user_id
    db.session.flush()
    return record


def generate_for_class(class_id, term_id, user_id=None) -> ReportCardJob:
    """Batch generation. Runs inline today; the job row is the async contract.

    When the worker lands, only the body of the loop moves -- the job record,
    its progress fields and the polling endpoint stay exactly as they are.
    """
    school_class = SchoolClass.query.filter_by(id=class_id).first()
    if school_class is None:
        raise not_found("Class")

    enrollments = Enrollment.query.filter_by(class_id=class_id, status="active").all()
    template = default_template()

    job = ReportCardJob(
        school_id=current_school_id(),
        class_id=class_id,
        term_id=term_id,
        status="processing",
        total=len(enrollments),
        requested_by=user_id,
    )
    db.session.add(job)
    db.session.flush()

    generated_ids = []
    failures = []
    for enrollment in enrollments:
        try:
            record = generate_for_student(
                enrollment.student_id, term_id, template=template, user_id=user_id
            )
            generated_ids.append(str(record.id))
            job.completed += 1
        except Exception as exc:  # one bad card must not kill the batch
            job.failed += 1
            failures.append({"student_id": str(enrollment.student_id), "reason": str(exc)})

    job.status = "completed" if not job.failed else ("partial" if job.completed else "failed")
    job.failure_reason = failures[0]["reason"] if failures and not job.completed else None
    job.result = {"generated": generated_ids, "failures": failures}
    job.finished_at = datetime.now(timezone.utc)
    db.session.flush()
    return job
