"""M6 -- attendance: one screen, one save."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, request

from ..extensions import db
from ..models import (
    AttendanceRecord,
    AttendanceSettings,
    AttendanceStatus,
    Enrollment,
    Student,
    Term,
)
from ..security import current_user, is_scoped, requires
from ..services.audit_service import record as audit
from ..services.scope_service import (
    accessible_student_ids,
    assert_can_access_class,
    assert_can_access_student,
    assert_can_mark_class,
)
from ..tenancy import current_school_id
from ..utils.errors import invalid_state
from ..utils.responses import body, ok
from ..utils.validation import Validator, arg_uuid

bp = Blueprint("attendance", __name__)


def _settings() -> AttendanceSettings:
    settings = AttendanceSettings.query.first()
    if settings is None:
        settings = AttendanceSettings(school_id=current_school_id())
        db.session.add(settings)
        db.session.flush()
    return settings


def _statuses() -> dict[str, AttendanceStatus]:
    return {s.code: s for s in AttendanceStatus.query.order_by(AttendanceStatus.sequence).all()}


def _term_for(target_date: date) -> Term:
    term = Term.query.filter(Term.start_date <= target_date, Term.end_date >= target_date).first()
    if term is None:
        term = Term.query.filter_by(is_current=True).first()
    if term is None:
        raise invalid_state("No academic term covers that date.")
    return term


@bp.get("/attendance/statuses")
@requires("attendance.view")
def list_statuses():
    settings = _settings()
    db.session.commit()
    return ok(
        {
            "statuses": [s.to_dict() for s in _statuses().values()],
            "settings": settings.to_dict(),
        }
    )


@bp.get("/attendance/register")
@requires("attendance.view")
def register():
    """The marking screen's single request: roster plus whatever is already marked."""
    class_id = arg_uuid("class_id")
    if not class_id:
        raise invalid_state("class_id is required.")

    target_date = _parse_date(request.args.get("date")) or date.today()
    period_id = arg_uuid("period_id")

    school_class = assert_can_access_class(class_id, "attendance.view")
    enrollments = Enrollment.query.filter_by(class_id=school_class.id, status="active").all()
    students = {
        s.id: s
        for s in Student.query.filter(
            Student.id.in_([e.student_id for e in enrollments] or [None])
        ).all()
    }

    existing = {
        r.student_id: r
        for r in AttendanceRecord.query.filter_by(
            class_id=school_class.id, date=target_date, period_id=period_id
        ).all()
    }

    statuses = _statuses()
    default_status = next(
        (code for code, status in statuses.items() if status.is_default), "present"
    )

    rows = []
    for enrollment in enrollments:
        student = students.get(enrollment.student_id)
        if student is None:
            continue
        marked = existing.get(student.id)
        rows.append(
            {
                "student_id": str(student.id),
                "student_name": student.full_name,
                "student_code": student.student_code,
                "status_code": marked.status_code if marked else None,
                "note": marked.note if marked else None,
                "is_marked": marked is not None,
            }
        )
    rows.sort(key=lambda row: row["student_name"])

    db.session.commit()
    return ok(
        {
            "class": school_class.to_dict(),
            "date": target_date.isoformat(),
            "period_id": period_id,
            "default_status": default_status,
            "statuses": [s.to_dict() for s in statuses.values()],
            "marked_count": sum(1 for row in rows if row["is_marked"]),
            "students": rows,
        }
    )


@bp.post("/attendance")
@requires("attendance.mark")
def mark_attendance():
    """Mark a whole class in one request: send only the exceptions if you like."""
    payload = body()
    validator = Validator(payload)
    class_id = validator.uuid("class_id", required=True)
    target_date = validator.date("date", default=date.today())
    period_id = validator.uuid("period_id")
    default_status = validator.string("default_status")
    entries = validator.sequence("entries", default=[])
    apply_default_to_all = validator.boolean("apply_default_to_all", default=False)
    validator.raise_if_invalid()

    school_class = assert_can_mark_class(class_id, "attendance.mark")
    settings = _settings()
    statuses = _statuses()

    if target_date > date.today():
        raise invalid_state("Attendance cannot be marked for a future date.")
    window = settings.backdate_window_days
    if window and target_date < date.today() - timedelta(days=window):
        raise invalid_state(
            f"Attendance can only be backdated {window} day(s). Ask an administrator."
        )

    term = _term_for(target_date)

    if default_status and default_status not in statuses:
        raise invalid_state(f"Unknown attendance status '{default_status}'.")

    enrollments = Enrollment.query.filter_by(class_id=school_class.id, status="active").all()
    roster_ids = {e.student_id for e in enrollments}

    by_student: dict = {}
    for entry in entries:
        entry_validator = Validator(entry if isinstance(entry, dict) else {})
        student_id = entry_validator.uuid("student_id", required=True)
        status_code = entry_validator.string("status_code", required=True)
        note = entry_validator.string("note", max_length=280)
        entry_validator.raise_if_invalid()

        if status_code not in statuses:
            raise invalid_state(f"Unknown attendance status '{status_code}'.")
        if student_id not in roster_ids:
            raise invalid_state("One or more students are not enrolled in this class.")
        by_student[student_id] = (status_code, note)

    if apply_default_to_all:
        if not default_status:
            raise invalid_state("default_status is required when applying to the whole class.")
        for student_id in roster_ids:
            by_student.setdefault(student_id, (default_status, None))

    if not by_student:
        raise invalid_state("Nothing to mark.")

    existing = {
        r.student_id: r
        for r in AttendanceRecord.query.filter(
            AttendanceRecord.class_id == school_class.id,
            AttendanceRecord.date == target_date,
            AttendanceRecord.period_id == period_id,
            AttendanceRecord.student_id.in_(list(by_student.keys())),
        ).all()
    }

    now = datetime.now(timezone.utc)
    written = 0
    for student_id, (status_code, note) in by_student.items():
        row = existing.get(student_id)
        if row is None:
            row = AttendanceRecord(
                school_id=current_school_id(),
                student_id=student_id,
                class_id=school_class.id,
                term_id=term.id,
                date=target_date,
                period_id=period_id,
            )
            db.session.add(row)
        row.status_code = status_code
        row.note = note
        row.marked_by = current_user().id
        row.marked_at = now
        written += 1

    audit(
        "update",
        "attendance",
        school_class.id,
        new_values={
            "date": target_date.isoformat(),
            "class_id": str(school_class.id),
            "records": written,
        },
    )
    db.session.commit()
    return ok(
        {
            "class_id": str(school_class.id),
            "date": target_date.isoformat(),
            "records_written": written,
        }
    )


@bp.get("/attendance/summary")
@requires("attendance.view")
def summary():
    """Rates by student for a class and term, or for one student."""
    class_id = arg_uuid("class_id")
    student_id = arg_uuid("student_id")
    term_id = arg_uuid("term_id")

    if not term_id:
        term = Term.query.filter_by(is_current=True).first()
        if term is None:
            raise invalid_state("No current term is set.")
        term_id = term.id

    query = AttendanceRecord.query.filter(AttendanceRecord.term_id == term_id)

    if student_id:
        student = assert_can_access_student(student_id, "attendance.view")
        query = query.filter(AttendanceRecord.student_id == student.id)
    elif class_id:
        school_class = assert_can_access_class(class_id, "attendance.view")
        query = query.filter(AttendanceRecord.class_id == school_class.id)
    else:
        allowed = accessible_student_ids() if is_scoped("attendance.view") else None
        if allowed is not None:
            if not allowed:
                return ok({"term_id": str(term_id), "students": []})
            query = query.filter(AttendanceRecord.student_id.in_(allowed))

    statuses = _statuses()
    buckets: dict = {}
    for row in query.all():
        bucket = buckets.setdefault(row.student_id, {"present": 0, "total": 0, "by_status": {}})
        bucket["total"] += 1
        bucket["by_status"][row.status_code] = bucket["by_status"].get(row.status_code, 0) + 1
        status = statuses.get(row.status_code)
        if status is not None and status.counts_as_present:
            bucket["present"] += 1

    students = {
        s.id: s for s in Student.query.filter(Student.id.in_(list(buckets.keys()) or [None])).all()
    }

    rows = []
    for student_uuid, bucket in buckets.items():
        student = students.get(student_uuid)
        rows.append(
            {
                "student_id": str(student_uuid),
                "student_name": student.full_name if student else None,
                "days_marked": bucket["total"],
                "days_present": bucket["present"],
                "days_absent": bucket["total"] - bucket["present"],
                "rate": (
                    round(bucket["present"] / bucket["total"] * 100, 1) if bucket["total"] else None
                ),
                "by_status": bucket["by_status"],
            }
        )
    rows.sort(key=lambda row: row["student_name"] or "")
    return ok({"term_id": str(term_id), "students": rows})


@bp.get("/students/<uuid:student_id>/attendance")
@requires("attendance.view")
def student_calendar(student_id):
    """Calendar view: every marked day, attributed to the class at the time."""
    student = assert_can_access_student(student_id, "attendance.view")
    query = AttendanceRecord.query.filter_by(student_id=student.id)

    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))
    if date_from:
        query = query.filter(AttendanceRecord.date >= date_from)
    if date_to:
        query = query.filter(AttendanceRecord.date <= date_to)
    term_id = arg_uuid("term_id")
    if term_id:
        query = query.filter(AttendanceRecord.term_id == term_id)

    records = query.order_by(AttendanceRecord.date.desc()).limit(400).all()
    return ok([r.to_dict() for r in records])


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None
