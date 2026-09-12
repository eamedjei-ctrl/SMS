"""M5 -- enrollment, transfers and year-end promotion."""

from __future__ import annotations

from datetime import date

from flask import Blueprint

from ..extensions import db
from ..models import Enrollment, EnrollmentHistory, PromotionBatch, SchoolClass, Student, TermResult
from ..security import current_user, requires
from ..services.audit_service import record
from ..services.scope_service import assert_can_access_class, assert_can_access_student
from ..tenancy import current_school_id
from ..utils.errors import duplicate, invalid_state, not_found
from ..utils.responses import body, created, ok
from ..utils.validation import Validator

bp = Blueprint("enrollment", __name__)


def _active_enrollment(student_id, academic_year_id=None) -> Enrollment | None:
    query = Enrollment.query.filter_by(student_id=student_id, status="active")
    if academic_year_id:
        query = query.filter_by(academic_year_id=academic_year_id)
    return query.first()


@bp.get("/classes/<uuid:class_id>/roster")
@requires("enrollment.view")
def class_roster(class_id):
    """The class roster in one request -- score entry and marking both start here."""
    school_class = assert_can_access_class(class_id, "enrollment.view")
    enrollments = (
        Enrollment.query.filter_by(class_id=school_class.id, status="active")
        .order_by(Enrollment.created_at)
        .all()
    )
    students = {
        s.id: s
        for s in Student.query.filter(
            Student.id.in_([e.student_id for e in enrollments] or [None])
        ).all()
    }
    roster = [
        {**enrollments_to_dict(e), "student": students[e.student_id].to_dict()}
        for e in enrollments
        if e.student_id in students
    ]
    roster.sort(
        key=lambda row: (row["student"]["last_name"] or "", row["student"]["first_name"] or "")
    )
    return ok({"class": school_class.to_dict(), "count": len(roster), "students": roster})


def enrollments_to_dict(enrollment: Enrollment) -> dict:
    return enrollment.to_dict()


@bp.post("/enrollments")
@requires("enrollment.manage")
def enroll_student():
    payload = body()
    validator = Validator(payload)
    student_id = validator.uuid("student_id", required=True)
    class_id = validator.uuid("class_id", required=True)
    enrolled_on = validator.date("enrolled_on", default=date.today())
    validator.raise_if_invalid()

    student = Student.query.filter_by(id=student_id).first()
    if student is None or student.is_deleted:
        raise not_found("Student")
    school_class = SchoolClass.query.filter_by(id=class_id).first()
    if school_class is None or school_class.is_deleted:
        raise not_found("Class")

    if _active_enrollment(student_id, school_class.academic_year_id):
        raise duplicate("This student already has an active enrollment for that year.")

    enrollment = Enrollment(
        school_id=current_school_id(),
        student_id=student_id,
        class_id=class_id,
        academic_year_id=school_class.academic_year_id,
        enrolled_on=enrolled_on,
        status="active",
    )
    db.session.add(enrollment)
    db.session.add(
        EnrollmentHistory(
            school_id=current_school_id(),
            student_id=student_id,
            to_class_id=class_id,
            action="enrolled",
            effective_date=enrolled_on,
            performed_by=current_user().id,
        )
    )
    db.session.flush()
    record("create", "enrollment", enrollment.id, new_values=enrollment.to_dict())
    db.session.commit()
    return created(enrollment.to_dict())


@bp.post("/enrollments/bulk")
@requires("enrollment.manage")
def bulk_enroll():
    payload = body()
    validator = Validator(payload)
    class_id = validator.uuid("class_id", required=True)
    student_ids = validator.sequence("student_ids", required=True)
    enrolled_on = validator.date("enrolled_on", default=date.today())
    validator.raise_if_invalid()

    school_class = SchoolClass.query.filter_by(id=class_id).first()
    if school_class is None:
        raise not_found("Class")

    enrolled, skipped = [], []
    for raw_id in student_ids:
        student = Student.query.filter_by(id=raw_id).first()
        if student is None or student.is_deleted:
            skipped.append({"student_id": str(raw_id), "reason": "Not found"})
            continue
        if _active_enrollment(student.id, school_class.academic_year_id):
            skipped.append({"student_id": str(raw_id), "reason": "Already enrolled this year"})
            continue

        enrollment = Enrollment(
            school_id=current_school_id(),
            student_id=student.id,
            class_id=class_id,
            academic_year_id=school_class.academic_year_id,
            enrolled_on=enrolled_on,
            status="active",
        )
        db.session.add(enrollment)
        db.session.add(
            EnrollmentHistory(
                school_id=current_school_id(),
                student_id=student.id,
                to_class_id=class_id,
                action="enrolled",
                effective_date=enrolled_on,
                performed_by=current_user().id,
            )
        )
        enrolled.append(str(student.id))

    db.session.flush()
    record(
        "create",
        "enrollment_bulk",
        class_id,
        new_values={"enrolled": len(enrolled), "skipped": len(skipped)},
    )
    db.session.commit()
    return ok({"enrolled": enrolled, "skipped": skipped})


@bp.post("/enrollments/<uuid:enrollment_id>/transfer")
@requires("enrollment.manage")
def transfer(enrollment_id):
    """Mid-year move. The old enrollment ends; attendance history stays attached."""
    payload = body()
    validator = Validator(payload)
    target_class_id = validator.uuid("target_class_id", required=True)
    effective_date = validator.date("effective_date", default=date.today())
    reason = validator.string("reason", required=True, min_length=3, max_length=500)
    validator.raise_if_invalid()

    enrollment = Enrollment.query.filter_by(id=enrollment_id).first()
    if enrollment is None:
        raise not_found("Enrollment")
    if enrollment.status != "active":
        raise invalid_state("Only an active enrollment can be transferred.")

    target = SchoolClass.query.filter_by(id=target_class_id).first()
    if target is None:
        raise not_found("Class")

    source_class_id = enrollment.class_id
    enrollment.status = "transferred"
    enrollment.ended_on = effective_date
    enrollment.reason = reason

    new_enrollment = Enrollment(
        school_id=current_school_id(),
        student_id=enrollment.student_id,
        class_id=target.id,
        academic_year_id=target.academic_year_id,
        enrolled_on=effective_date,
        status="active",
    )
    db.session.add(new_enrollment)
    db.session.add(
        EnrollmentHistory(
            school_id=current_school_id(),
            student_id=enrollment.student_id,
            from_class_id=source_class_id,
            to_class_id=target.id,
            action="transferred",
            effective_date=effective_date,
            reason=reason,
            performed_by=current_user().id,
        )
    )
    db.session.flush()
    record(
        "update",
        "enrollment",
        enrollment.id,
        old_values={"class_id": str(source_class_id), "status": "active"},
        new_values={"class_id": str(target.id), "status": "transferred"},
        reason=reason,
    )
    db.session.commit()
    return ok(new_enrollment.to_dict())


@bp.get("/students/<uuid:student_id>/enrollments")
@requires("enrollment.view")
def student_history(student_id):
    student = assert_can_access_student(student_id, "enrollment.view")
    enrollments = (
        Enrollment.query.filter_by(student_id=student.id)
        .order_by(Enrollment.enrolled_on.desc())
        .all()
    )
    history = (
        EnrollmentHistory.query.filter_by(student_id=student.id)
        .order_by(EnrollmentHistory.effective_date.desc())
        .all()
    )
    return ok(
        {
            "enrollments": [e.to_dict() for e in enrollments],
            "history": [h.to_dict() for h in history],
        }
    )


@bp.post("/promotions/preview")
@requires("promotion.execute")
def preview_promotion():
    """Show each student's average before anyone is moved."""
    payload = body()
    validator = Validator(payload)
    source_class_id = validator.uuid("source_class_id", required=True)
    term_id = validator.uuid("term_id")
    threshold = validator.decimal("average_threshold")
    validator.raise_if_invalid()

    enrollments = Enrollment.query.filter_by(class_id=source_class_id, status="active").all()
    students = {
        s.id: s
        for s in Student.query.filter(
            Student.id.in_([e.student_id for e in enrollments] or [None])
        ).all()
    }

    term_results = {}
    if term_id:
        term_results = {
            r.student_id: r
            for r in TermResult.query.filter_by(class_id=source_class_id, term_id=term_id).all()
        }

    rows = []
    for enrollment in enrollments:
        student = students.get(enrollment.student_id)
        if student is None:
            continue
        result = term_results.get(enrollment.student_id)
        aggregate = float(result.aggregate) if result and result.aggregate is not None else None
        rows.append(
            {
                "student_id": str(student.id),
                "student_name": student.full_name,
                "student_code": student.student_code,
                "aggregate": aggregate,
                "position": result.overall_position if result else None,
                "meets_threshold": (
                    None
                    if aggregate is None or threshold is None
                    else aggregate >= float(threshold)
                ),
            }
        )
    rows.sort(key=lambda row: row["student_name"])
    return ok({"count": len(rows), "students": rows})


@bp.post("/promotions/execute")
@requires("promotion.execute")
def execute_promotion():
    """Move a whole class in one transaction, holding back the named exceptions."""
    payload = body()
    validator = Validator(payload)
    source_class_id = validator.uuid("source_class_id", required=True)
    target_class_id = validator.uuid("target_class_id", required=True)
    retained_ids = validator.sequence("retained_student_ids", default=[])
    effective_date = validator.date("effective_date", default=date.today())
    validator.raise_if_invalid()

    source = SchoolClass.query.filter_by(id=source_class_id).first()
    target = SchoolClass.query.filter_by(id=target_class_id).first()
    if source is None:
        raise not_found("Source class")
    if target is None:
        raise not_found("Target class")
    if source.id == target.id:
        raise invalid_state("Source and target classes must differ.")

    retained = {str(s) for s in retained_ids}
    enrollments = Enrollment.query.filter_by(class_id=source.id, status="active").all()

    promoted_count = 0
    retained_count = 0
    for enrollment in enrollments:
        held_back = str(enrollment.student_id) in retained
        enrollment.status = "repeated" if held_back else "promoted"
        enrollment.ended_on = effective_date

        destination = source if held_back else target
        db.session.add(
            Enrollment(
                school_id=current_school_id(),
                student_id=enrollment.student_id,
                class_id=destination.id,
                academic_year_id=destination.academic_year_id,
                enrolled_on=effective_date,
                status="active",
            )
        )
        db.session.add(
            EnrollmentHistory(
                school_id=current_school_id(),
                student_id=enrollment.student_id,
                from_class_id=source.id,
                to_class_id=destination.id,
                action="repeated" if held_back else "promoted",
                effective_date=effective_date,
                performed_by=current_user().id,
            )
        )
        if held_back:
            retained_count += 1
        else:
            promoted_count += 1

    batch = PromotionBatch(
        school_id=current_school_id(),
        source_class_id=source.id,
        target_class_id=target.id,
        promoted_count=promoted_count,
        retained_count=retained_count,
        retained_student_ids=sorted(retained),
        executed_by=current_user().id,
    )
    db.session.add(batch)
    db.session.flush()

    record("create", "promotion_batch", batch.id, new_values=batch.to_dict())
    db.session.commit()
    return created(batch.to_dict())
