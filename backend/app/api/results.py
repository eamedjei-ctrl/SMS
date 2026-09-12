"""M7 (runtime half) -- score entry, computation, broadsheet and approval."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

from ..extensions import db
from ..models import (
    AssessmentComponent,
    AssessmentScore,
    ClassSubject,
    Enrollment,
    Result,
    ResultRemark,
    SchoolClass,
    Student,
    Subject,
    Term,
    TermResult,
)
from ..security import current_user, is_scoped, requires
from ..services.audit_service import record
from ..services.results_engine import recompute_class_term
from ..services.scope_service import (
    accessible_student_ids,
    assert_can_access_class,
    assert_can_access_student,
    assert_can_enter_results,
)
from ..tenancy import current_school_id
from ..utils.errors import invalid_state, not_found, term_locked, validation_error
from ..utils.responses import body, ok
from ..utils.validation import Validator, arg_uuid

bp = Blueprint("results", __name__)


def _term_or_current(term_id=None) -> Term:
    term = (
        Term.query.filter_by(id=term_id).first()
        if term_id
        else Term.query.filter_by(is_current=True).first()
    )
    if term is None:
        raise not_found("Term")
    return term


def _assert_writable(term: Term) -> None:
    if term.results_locked:
        raise term_locked()


# ==========================================================================
# Score entry
# ==========================================================================
@bp.get("/scores")
@requires("results.enter", "results.view", require_all=False)
def score_sheet():
    """Everything the score-entry screen needs, in one request."""
    class_id = arg_uuid("class_id")
    subject_id = arg_uuid("subject_id")
    if not class_id or not subject_id:
        raise invalid_state("class_id and subject_id are required.")

    term = _term_or_current(arg_uuid("term_id"))
    assert_can_enter_results(class_id, subject_id, "results.enter")
    school_class = SchoolClass.query.filter_by(id=class_id).first()
    subject = Subject.query.filter_by(id=subject_id).first()

    components = [
        c
        for c in AssessmentComponent.query.filter_by(is_active=True)
        .order_by(AssessmentComponent.sequence)
        .all()
        if c.applies_to_subject(subject_id)
    ]

    enrollments = Enrollment.query.filter_by(class_id=class_id, status="active").all()
    students = {
        s.id: s
        for s in Student.query.filter(
            Student.id.in_([e.student_id for e in enrollments] or [None])
        ).all()
    }

    scores = AssessmentScore.query.filter_by(
        class_id=class_id, subject_id=subject_id, term_id=term.id
    ).all()
    index: dict = {}
    for score in scores:
        index.setdefault(score.student_id, {})[str(score.component_id)] = score

    rows = []
    for enrollment in enrollments:
        student = students.get(enrollment.student_id)
        if student is None:
            continue
        entered = index.get(student.id, {})
        component_values = {}
        for component in components:
            score = entered.get(str(component.id))
            component_values[str(component.id)] = {
                "raw_score": (
                    float(score.raw_score) if score and score.raw_score is not None else None
                ),
                "is_absent": bool(score.is_absent) if score else False,
            }
        marked = sum(
            1
            for value in component_values.values()
            if value["raw_score"] is not None or value["is_absent"]
        )
        rows.append(
            {
                "student_id": str(student.id),
                "student_name": student.full_name,
                "student_code": student.student_code,
                "scores": component_values,
                "is_complete": marked == len(components) and components != [],
            }
        )
    rows.sort(key=lambda row: row["student_name"])

    return ok(
        {
            "class": school_class.to_dict() if school_class else None,
            "subject": subject.to_dict() if subject else None,
            "term": term.to_dict(),
            "is_locked": term.results_locked,
            "components": [c.to_dict() for c in components],
            "unmarked_count": sum(1 for row in rows if not row["is_complete"]),
            "students": rows,
        }
    )


@bp.post("/scores")
@requires("results.enter")
def save_scores():
    """Progressive save: send one cell or forty, it is the same endpoint.

    The teacher's screen calls this as they type, so a dropped connection costs
    at most the last unsent cell.
    """
    payload = body()
    validator = Validator(payload)
    class_id = validator.uuid("class_id", required=True)
    subject_id = validator.uuid("subject_id", required=True)
    term_id = validator.uuid("term_id")
    entries = validator.sequence("scores", required=True)
    recompute = validator.boolean("recompute", default=False)
    validator.raise_if_invalid()

    term = _term_or_current(term_id)
    _assert_writable(term)
    assert_can_enter_results(class_id, subject_id, "results.enter")

    components = {
        str(c.id): c
        for c in AssessmentComponent.query.filter_by(is_active=True).all()
        if c.applies_to_subject(subject_id)
    }
    roster = {
        e.student_id for e in Enrollment.query.filter_by(class_id=class_id, status="active").all()
    }

    errors: dict[str, list[str]] = {}
    parsed: list[tuple] = []

    for index, raw in enumerate(entries):
        entry_validator = Validator(raw if isinstance(raw, dict) else {})
        student_id = entry_validator.uuid("student_id", required=True)
        component_id = entry_validator.uuid("component_id", required=True)
        raw_score = entry_validator.decimal("raw_score")
        is_absent = entry_validator.boolean("is_absent", default=False)

        if entry_validator.errors:
            errors[f"scores[{index}]"] = [
                f"{field}: {'; '.join(messages)}"
                for field, messages in entry_validator.errors.items()
            ]
            continue

        component = components.get(str(component_id))
        if component is None:
            errors[f"scores[{index}].component_id"] = [
                "That component is not active for this subject."
            ]
            continue
        if student_id not in roster:
            errors[f"scores[{index}].student_id"] = ["Student not found in this class."]
            continue
        if raw_score is not None and raw_score < 0:
            errors[f"scores[{index}].raw_score"] = ["Score cannot be negative."]
            continue
        if raw_score is not None and raw_score > Decimal(component.max_score):
            errors[f"scores[{index}].raw_score"] = [
                f"Score exceeds the maximum of {float(component.max_score):g} for this component."
            ]
            continue

        parsed.append((student_id, component_id, raw_score, is_absent))

    if errors:
        raise validation_error(errors)

    existing = {
        (s.student_id, s.component_id): s
        for s in AssessmentScore.query.filter(
            AssessmentScore.class_id == class_id,
            AssessmentScore.subject_id == subject_id,
            AssessmentScore.term_id == term.id,
        ).all()
    }

    now = datetime.now(timezone.utc)
    written = 0
    for student_id, component_id, raw_score, is_absent in parsed:
        row = existing.get((student_id, component_id))
        if row is None:
            row = AssessmentScore(
                school_id=current_school_id(),
                student_id=student_id,
                subject_id=subject_id,
                class_id=class_id,
                term_id=term.id,
                component_id=component_id,
            )
            db.session.add(row)
        row.raw_score = None if is_absent else raw_score
        row.is_absent = is_absent
        row.entered_by = current_user().id
        row.entered_at = now
        written += 1

    db.session.flush()
    record(
        "update",
        "assessment_scores",
        class_id,
        new_values={
            "subject_id": str(subject_id),
            "term_id": str(term.id),
            "scores_written": written,
        },
    )

    response = {"scores_written": written, "term_id": str(term.id)}
    if recompute:
        response["computation"] = recompute_class_term(class_id, term.id)

    db.session.commit()
    return ok(response)


# ==========================================================================
# Computation
# ==========================================================================
@bp.post("/results/compute")
@requires("results.recompute")
def compute():
    payload = body()
    validator = Validator(payload)
    class_id = validator.uuid("class_id", required=True)
    term_id = validator.uuid("term_id")
    validator.raise_if_invalid()

    term = _term_or_current(term_id)
    if term.results_locked:
        raise term_locked("This term is locked. Unlock it before recomputing.")

    summary = recompute_class_term(class_id, term.id)
    record("update", "results_computation", class_id, new_values=summary)
    db.session.commit()
    return ok(summary)


# ==========================================================================
# Reading results
# ==========================================================================
@bp.get("/results/broadsheet")
@requires("results.view")
def broadsheet():
    """The full class-by-subject table administrators work from."""
    class_id = arg_uuid("class_id")
    if not class_id:
        raise invalid_state("class_id is required.")

    term = _term_or_current(arg_uuid("term_id"))
    school_class = assert_can_access_class(class_id, "results.view")

    class_subjects = ClassSubject.query.filter_by(class_id=school_class.id).all()
    subjects = [
        {
            "id": str(cs.subject_id),
            "name": cs.subject.name if cs.subject else "-",
            "code": cs.subject.code if cs.subject else None,
        }
        for cs in class_subjects
    ]

    results = Result.query.filter_by(class_id=school_class.id, term_id=term.id).all()
    term_results = {
        r.student_id: r
        for r in TermResult.query.filter_by(class_id=school_class.id, term_id=term.id).all()
    }

    enrollments = Enrollment.query.filter_by(class_id=school_class.id, status="active").all()
    students = {
        s.id: s
        for s in Student.query.filter(
            Student.id.in_([e.student_id for e in enrollments] or [None])
        ).all()
    }

    by_student: dict = {}
    for row in results:
        by_student.setdefault(row.student_id, {})[str(row.subject_id)] = row

    rows = []
    for student_id, student in students.items():
        subject_cells = by_student.get(student_id, {})
        summary = term_results.get(student_id)
        rows.append(
            {
                "student_id": str(student_id),
                "student_name": student.full_name,
                "student_code": student.student_code,
                "subjects": {
                    subject_id: {
                        "total_score": (
                            float(cell.total_score) if cell.total_score is not None else None
                        ),
                        "grade": cell.grade,
                        "position": cell.subject_position,
                    }
                    for subject_id, cell in subject_cells.items()
                },
                "aggregate": (
                    float(summary.aggregate) if summary and summary.aggregate is not None else None
                ),
                "overall_position": summary.overall_position if summary else None,
                "is_approved": (
                    all(cell.is_approved for cell in subject_cells.values())
                    if subject_cells
                    else False
                ),
            }
        )
    rows.sort(key=lambda row: (row["overall_position"] is None, row["overall_position"] or 0))

    return ok(
        {
            "class": school_class.to_dict(),
            "term": term.to_dict(),
            "is_locked": term.results_locked,
            "subjects": subjects,
            "students": rows,
        }
    )


@bp.get("/students/<uuid:student_id>/results")
@requires("results.view")
def student_results(student_id):
    """A student's own results. Unapproved results stay hidden from families."""
    student = assert_can_access_student(student_id, "results.view")
    term = _term_or_current(arg_uuid("term_id"))

    results = Result.query.filter_by(student_id=student.id, term_id=term.id).all()
    summary = TermResult.query.filter_by(student_id=student.id, term_id=term.id).first()

    from ..services.scope_service import has_role

    audience_is_family = has_role("student") or has_role("guardian")
    if audience_is_family:
        results = [row for row in results if row.is_approved]
        if summary is not None and not results:
            summary = None

    subject_names = {
        s.id: s.name
        for s in Subject.query.filter(
            Subject.id.in_([r.subject_id for r in results] or [None])
        ).all()
    }

    remarks = {
        remark.author_role: remark.body
        for remark in ResultRemark.query.filter_by(student_id=student.id, term_id=term.id).all()
    }

    return ok(
        {
            "student": student.to_dict(),
            "term": term.to_dict(),
            "results": [
                {**row.to_dict(), "subject_name": subject_names.get(row.subject_id)}
                for row in results
            ],
            "summary": summary.to_dict() if summary else None,
            "remarks": remarks,
            "published": bool(results),
        }
    )


@bp.get("/my/results")
@requires("results.view")
def my_results():
    """Student and guardian entry point: whatever this account may see."""
    allowed = accessible_student_ids() if is_scoped("results.view") else None
    if allowed is None:
        raise invalid_state("Use /students/{id}/results for staff access.")
    if not allowed:
        return ok([])

    term = _term_or_current(request.args.get("term_id"))
    students = Student.query.filter(Student.id.in_(allowed)).all()

    payload = []
    for student in students:
        results = Result.query.filter_by(
            student_id=student.id, term_id=term.id, is_approved=True
        ).all()
        summary = TermResult.query.filter_by(student_id=student.id, term_id=term.id).first()
        subject_names = {
            s.id: s.name
            for s in Subject.query.filter(
                Subject.id.in_([r.subject_id for r in results] or [None])
            ).all()
        }
        payload.append(
            {
                "student": student.to_dict(),
                "results": [
                    {**row.to_dict(), "subject_name": subject_names.get(row.subject_id)}
                    for row in results
                ],
                "summary": summary.to_dict() if summary and results else None,
            }
        )
    return ok({"term": term.to_dict(), "children": payload})


# ==========================================================================
# Approval
# ==========================================================================
@bp.post("/results/approve")
@requires("results.approve")
def approve():
    """Head teacher signs off a class's results and locks them from edits."""
    payload = body()
    validator = Validator(payload)
    class_id = validator.uuid("class_id", required=True)
    term_id = validator.uuid("term_id")
    lock_term = validator.boolean("lock_term", default=False)
    validator.raise_if_invalid()

    term = _term_or_current(term_id)
    school_class = SchoolClass.query.filter_by(id=class_id).first()
    if school_class is None:
        raise not_found("Class")

    results = Result.query.filter_by(class_id=class_id, term_id=term.id).all()
    if not results:
        raise invalid_state("There are no computed results for this class and term.")

    now = datetime.now(timezone.utc)
    for row in results:
        row.is_approved = True
        row.approved_by = current_user().id
        row.approved_at = now

    if lock_term:
        term.results_locked = True
        term.locked_at = now
        term.locked_by = current_user().id

    record(
        "approve",
        "results",
        class_id,
        new_values={
            "term_id": str(term.id),
            "results_approved": len(results),
            "term_locked": lock_term,
        },
    )
    db.session.commit()
    return ok(
        {
            "class_id": str(class_id),
            "term_id": str(term.id),
            "results_approved": len(results),
            "term_locked": term.results_locked,
        }
    )


# ==========================================================================
# Remarks
# ==========================================================================
@bp.put("/students/<uuid:student_id>/remarks")
@requires("results.enter")
def save_remark(student_id):
    """A remark is saved by a human, whether or not AI drafted it."""
    student = assert_can_access_student(student_id, "results.enter")

    payload = body()
    validator = Validator(payload)
    term_id = validator.uuid("term_id")
    author_role = validator.string(
        "author_role", default="teacher", choices=("teacher", "head_teacher")
    )
    text = validator.string("body", required=True, max_length=1000)
    is_ai_assisted = validator.boolean("is_ai_assisted", default=False)
    validator.raise_if_invalid()

    term = _term_or_current(term_id)
    _assert_writable(term)

    if author_role == "head_teacher":
        from ..security import has_permission

        if not has_permission("results.approve"):
            from ..utils.errors import permission_denied

            raise permission_denied("Only a head teacher may write the head teacher's remark.")

    remark = ResultRemark.query.filter_by(
        student_id=student.id, term_id=term.id, author_role=author_role
    ).first()
    if remark is None:
        remark = ResultRemark(
            school_id=current_school_id(),
            student_id=student.id,
            term_id=term.id,
            author_role=author_role,
        )
        db.session.add(remark)

    remark.body = text
    remark.is_ai_assisted = is_ai_assisted
    remark.written_by = current_user().id
    db.session.flush()

    record("update", "result_remark", remark.id, new_values={"author_role": author_role})
    db.session.commit()
    return ok(remark.to_dict())
