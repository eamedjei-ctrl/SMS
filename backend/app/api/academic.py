"""M4 -- academic years, terms, classes, subjects and teaching assignments."""

from __future__ import annotations

from flask import Blueprint, request

from ..extensions import db
from ..models import (
    AcademicYear,
    ClassSubject,
    ClassSubjectTeacher,
    SchoolClass,
    Staff,
    Subject,
    Term,
)
from ..security import current_user, is_scoped, requires
from ..services.audit_service import diff, record
from ..services.scope_service import taught_class_ids
from ..tenancy import current_school_id
from ..utils.errors import duplicate, invalid_state, not_found
from ..utils.responses import body, created, ok
from ..utils.validation import Validator, arg_uuid

bp = Blueprint("academic", __name__)


def _current_term() -> Term | None:
    return Term.query.filter_by(is_current=True).first()


# ==========================================================================
# Academic years and terms
# ==========================================================================
@bp.get("/academic-years")
@requires("classes.view")
def list_years():
    years = AcademicYear.query.filter(AcademicYear.deleted_at.is_(None)).order_by(
        AcademicYear.name.desc()
    )
    return ok([year.to_dict(include_terms=True) for year in years.all()])


@bp.post("/academic-years")
@requires("classes.manage")
def create_year():
    payload = body()
    validator = Validator(payload)
    name = validator.string("name", required=True, max_length=50)
    start_date = validator.date("start_date")
    end_date = validator.date("end_date")
    is_current = validator.boolean("is_current", default=False)
    terms = validator.sequence("terms", default=[])
    validator.raise_if_invalid()

    if AcademicYear.query.filter_by(name=name).first():
        raise duplicate("An academic year with that name already exists.")

    if is_current:
        for year in AcademicYear.query.filter_by(is_current=True).all():
            year.is_current = False

    year = AcademicYear(
        school_id=current_school_id(),
        name=name,
        start_date=start_date,
        end_date=end_date,
        is_current=is_current,
    )
    db.session.add(year)
    db.session.flush()

    for index, term in enumerate(terms):
        term_validator = Validator(term)
        term_name = term_validator.string("name", required=True, max_length=60)
        term_start = term_validator.date("start_date")
        term_end = term_validator.date("end_date")
        term_validator.raise_if_invalid()
        db.session.add(
            Term(
                school_id=current_school_id(),
                academic_year_id=year.id,
                name=term_name,
                sequence=index + 1,
                start_date=term_start,
                end_date=term_end,
                is_current=is_current and index == 0,
            )
        )

    db.session.flush()
    record("create", "academic_year", year.id, new_values=year.to_dict())
    db.session.commit()
    return created(year.to_dict(include_terms=True))


@bp.post("/terms")
@requires("classes.manage")
def create_term():
    payload = body()
    validator = Validator(payload)
    academic_year_id = validator.uuid("academic_year_id", required=True)
    name = validator.string("name", required=True, max_length=60)
    sequence = validator.integer("sequence", required=True, minimum=1)
    start_date = validator.date("start_date")
    end_date = validator.date("end_date")
    validator.raise_if_invalid()

    if AcademicYear.query.filter_by(id=academic_year_id).first() is None:
        raise not_found("Academic year")
    if Term.query.filter_by(academic_year_id=academic_year_id, sequence=sequence).first():
        raise duplicate("A term with that sequence already exists in this year.")

    term = Term(
        school_id=current_school_id(),
        academic_year_id=academic_year_id,
        name=name,
        sequence=sequence,
        start_date=start_date,
        end_date=end_date,
    )
    db.session.add(term)
    db.session.flush()
    record("create", "term", term.id, new_values=term.to_dict())
    db.session.commit()
    return created(term.to_dict())


@bp.get("/terms/current")
@requires("classes.view")
def get_current_term():
    """The whole application shell depends on knowing the current term."""
    term = _current_term()
    year = AcademicYear.query.filter_by(is_current=True).first()
    return ok(
        {
            "term": term.to_dict() if term else None,
            "academic_year": year.to_dict() if year else None,
        }
    )


@bp.post("/terms/<uuid:term_id>/set-current")
@requires("classes.manage")
def set_current_term(term_id):
    """Exactly one term is current per school; setting one clears the rest."""
    term = Term.query.filter_by(id=term_id).first()
    if term is None:
        raise not_found("Term")

    for other in Term.query.filter_by(is_current=True).all():
        other.is_current = False
    term.is_current = True

    for year in AcademicYear.query.filter_by(is_current=True).all():
        year.is_current = False
    year = AcademicYear.query.filter_by(id=term.academic_year_id).first()
    if year:
        year.is_current = True

    record("update", "term", term.id, new_values={"is_current": True})
    db.session.commit()
    return ok(term.to_dict())


@bp.post("/terms/<uuid:term_id>/lock")
@requires("results.approve")
def lock_term(term_id):
    term = Term.query.filter_by(id=term_id).first()
    if term is None:
        raise not_found("Term")
    if term.results_locked:
        return ok(term.to_dict())

    term.results_locked = True
    term.locked_at = db.func.now()
    term.locked_by = current_user().id
    record("approve", "term", term.id, new_values={"results_locked": True})
    db.session.commit()
    return ok(term.to_dict())


@bp.post("/terms/<uuid:term_id>/unlock")
@requires("results.unlock")
def unlock_term(term_id):
    """Unlocking is an audited act: the reason is mandatory."""
    payload = body()
    validator = Validator(payload)
    reason = validator.string("reason", required=True, min_length=5, max_length=500)
    validator.raise_if_invalid()

    term = Term.query.filter_by(id=term_id).first()
    if term is None:
        raise not_found("Term")

    term.results_locked = False
    term.locked_at = None
    term.locked_by = None
    record(
        "unlock",
        "term",
        term.id,
        old_values={"results_locked": True},
        new_values={"results_locked": False},
        reason=reason,
    )
    db.session.commit()
    return ok(term.to_dict())


# ==========================================================================
# Subjects
# ==========================================================================
@bp.get("/subjects")
@requires("classes.view")
def list_subjects():
    subjects = (
        Subject.query.filter(Subject.deleted_at.is_(None))
        .order_by(Subject.sequence, Subject.name)
        .all()
    )
    return ok([s.to_dict() for s in subjects])


@bp.post("/subjects")
@requires("subjects.manage")
def create_subject():
    payload = body()
    validator = Validator(payload)
    name = validator.string("name", required=True, max_length=120)
    code = validator.string("code", required=True, max_length=20)
    is_core = validator.boolean("is_core", default=True)
    sequence = validator.integer("sequence", default=0)
    validator.raise_if_invalid()

    if Subject.query.filter_by(code=code).first():
        raise duplicate("A subject with that code already exists.")

    subject = Subject(
        school_id=current_school_id(),
        name=name,
        code=code,
        is_core=is_core,
        sequence=sequence,
    )
    db.session.add(subject)
    db.session.flush()
    record("create", "subject", subject.id, new_values=subject.to_dict())
    db.session.commit()
    return created(subject.to_dict())


@bp.patch("/subjects/<uuid:subject_id>")
@requires("subjects.manage")
def update_subject(subject_id):
    subject = Subject.query.filter_by(id=subject_id).first()
    if subject is None or subject.is_deleted:
        raise not_found("Subject")
    before = subject.to_dict()

    payload = body()
    validator = Validator(payload)
    if "name" in payload:
        validator.string("name", max_length=120)
    if "code" in payload:
        validator.string("code", max_length=20)
    if "is_core" in payload:
        validator.boolean("is_core")
    if "is_active" in payload:
        validator.boolean("is_active")
    if "sequence" in payload:
        validator.integer("sequence")
    data = validator.raise_if_invalid()

    for field, value in data.items():
        if field in payload:
            setattr(subject, field, value)
    db.session.flush()

    old_values, new_values = diff(before, subject.to_dict())
    record("update", "subject", subject.id, old_values=old_values, new_values=new_values)
    db.session.commit()
    return ok(subject.to_dict())


# ==========================================================================
# Classes
# ==========================================================================
@bp.get("/classes")
@requires("classes.view")
def list_classes():
    query = SchoolClass.query.filter(SchoolClass.deleted_at.is_(None))

    year_id = arg_uuid("academic_year_id")
    if year_id:
        query = query.filter(SchoolClass.academic_year_id == year_id)
    elif request.args.get("current_year", "true") == "true":
        year = AcademicYear.query.filter_by(is_current=True).first()
        if year:
            query = query.filter(SchoolClass.academic_year_id == year.id)

    if is_scoped("classes.view"):
        allowed = taught_class_ids()
        if not allowed:
            return ok([])
        query = query.filter(SchoolClass.id.in_(allowed))

    classes = query.order_by(SchoolClass.level, SchoolClass.name).all()
    return ok([c.to_dict() for c in classes])


@bp.post("/classes")
@requires("classes.manage")
def create_class():
    payload = body()
    validator = Validator(payload)
    academic_year_id = validator.uuid("academic_year_id")
    name = validator.string("name", required=True, max_length=100)
    level = validator.integer("level", required=True, minimum=0)
    section = validator.string("section", max_length=40)
    class_teacher_id = validator.uuid("class_teacher_id")
    capacity = validator.integer("capacity", minimum=1)
    curriculum = validator.string("curriculum", max_length=40)
    validator.raise_if_invalid()

    if academic_year_id is None:
        year = AcademicYear.query.filter_by(is_current=True).first()
        if year is None:
            raise invalid_state("Create an academic year before creating classes.")
        academic_year_id = year.id

    if class_teacher_id and Staff.query.filter_by(id=class_teacher_id).first() is None:
        raise not_found("Staff")

    if SchoolClass.query.filter_by(
        academic_year_id=academic_year_id, name=name, section=section
    ).first():
        raise duplicate("A class with that name and section already exists this year.")

    school_class = SchoolClass(
        school_id=current_school_id(),
        academic_year_id=academic_year_id,
        name=name,
        level=level,
        section=section,
        class_teacher_id=class_teacher_id,
        capacity=capacity,
        curriculum=curriculum,
    )
    db.session.add(school_class)
    db.session.flush()
    record("create", "class", school_class.id, new_values=school_class.to_dict())
    db.session.commit()
    return created(school_class.to_dict())


@bp.patch("/classes/<uuid:class_id>")
@requires("classes.manage")
def update_class(class_id):
    school_class = SchoolClass.query.filter_by(id=class_id).first()
    if school_class is None or school_class.is_deleted:
        raise not_found("Class")
    before = school_class.to_dict()

    payload = body()
    validator = Validator(payload)
    if "name" in payload:
        validator.string("name", max_length=100)
    if "level" in payload:
        validator.integer("level", minimum=0)
    if "section" in payload:
        validator.string("section", max_length=40)
    if "class_teacher_id" in payload:
        validator.uuid("class_teacher_id")
    if "capacity" in payload:
        validator.integer("capacity", minimum=1)
    if "curriculum" in payload:
        validator.string("curriculum", max_length=40)
    data = validator.raise_if_invalid()

    for field, value in data.items():
        if field in payload:
            setattr(school_class, field, value)
    db.session.flush()

    old_values, new_values = diff(before, school_class.to_dict())
    record("update", "class", school_class.id, old_values=old_values, new_values=new_values)
    db.session.commit()
    return ok(school_class.to_dict())


# ==========================================================================
# Class-subject-teacher matrix
# ==========================================================================
@bp.get("/classes/<uuid:class_id>/subjects")
@requires("classes.view")
def list_class_subjects(class_id):
    from ..services.scope_service import assert_can_access_class

    assert_can_access_class(class_id, "classes.view")
    rows = ClassSubject.query.filter_by(class_id=class_id).all()
    return ok([row.to_dict() for row in rows])


@bp.post("/classes/<uuid:class_id>/subjects")
@requires("classes.manage")
def attach_subject(class_id):
    school_class = SchoolClass.query.filter_by(id=class_id).first()
    if school_class is None:
        raise not_found("Class")

    payload = body()
    validator = Validator(payload)
    subject_id = validator.uuid("subject_id", required=True)
    is_elective = validator.boolean("is_elective", default=False)
    grade_scale_id = validator.uuid("grade_scale_id")
    validator.raise_if_invalid()

    if Subject.query.filter_by(id=subject_id).first() is None:
        raise not_found("Subject")
    if ClassSubject.query.filter_by(class_id=class_id, subject_id=subject_id).first():
        raise duplicate("That subject is already attached to this class.")

    row = ClassSubject(
        school_id=current_school_id(),
        class_id=class_id,
        subject_id=subject_id,
        is_elective=is_elective,
        grade_scale_id=grade_scale_id,
    )
    db.session.add(row)
    db.session.flush()
    record("create", "class_subject", row.id, new_values=row.to_dict())
    db.session.commit()
    return created(row.to_dict())


@bp.post("/class-subjects/<uuid:class_subject_id>/teachers")
@requires("classes.manage")
def assign_teacher(class_subject_id):
    """Assigning a teacher is what grants them scoped access to that class."""
    class_subject = ClassSubject.query.filter_by(id=class_subject_id).first()
    if class_subject is None:
        raise not_found("Class subject")

    payload = body()
    validator = Validator(payload)
    staff_id = validator.uuid("staff_id", required=True)
    is_primary = validator.boolean("is_primary", default=True)
    validator.raise_if_invalid()

    if Staff.query.filter_by(id=staff_id).first() is None:
        raise not_found("Staff")
    if ClassSubjectTeacher.query.filter_by(
        class_subject_id=class_subject_id, staff_id=staff_id
    ).first():
        raise duplicate("That teacher is already assigned to this class and subject.")

    row = ClassSubjectTeacher(
        school_id=current_school_id(),
        class_subject_id=class_subject_id,
        staff_id=staff_id,
        is_primary=is_primary,
    )
    db.session.add(row)
    db.session.flush()
    record(
        "create",
        "class_subject_teacher",
        row.id,
        new_values={"class_subject_id": str(class_subject_id), "staff_id": str(staff_id)},
    )
    db.session.commit()
    return created(
        {
            "id": str(row.id),
            "class_subject_id": str(class_subject_id),
            "staff_id": str(staff_id),
            "is_primary": is_primary,
        }
    )


@bp.delete("/class-subjects/<uuid:class_subject_id>/teachers/<uuid:staff_id>")
@requires("classes.manage")
def unassign_teacher(class_subject_id, staff_id):
    row = ClassSubjectTeacher.query.filter_by(
        class_subject_id=class_subject_id, staff_id=staff_id
    ).first()
    if row is None:
        raise not_found("Teacher assignment")
    record("delete", "class_subject_teacher", row.id)
    db.session.delete(row)
    db.session.commit()
    return ok({"unassigned": True})


@bp.get("/my/classes")
@requires("classes.view")
def my_classes():
    """A teacher's own classes -- the entry point for the mobile shell."""
    class_ids = taught_class_ids()
    if not class_ids:
        return ok([])
    classes = SchoolClass.query.filter(
        SchoolClass.id.in_(class_ids), SchoolClass.deleted_at.is_(None)
    ).all()

    payload = []
    for school_class in classes:
        subjects = ClassSubject.query.filter_by(class_id=school_class.id).all()
        payload.append({**school_class.to_dict(), "subjects": [s.to_dict() for s in subjects]})
    return ok(payload)
