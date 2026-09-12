"""M3 -- students, guardians and staff."""

from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, request

from ..extensions import db
from ..models import Guardian, ImportJob, Staff, Student, StudentGuardian
from ..security import current_user, has_permission, is_scoped, requires
from ..services.audit_service import diff, record
from ..services.scope_service import accessible_student_ids, assert_can_access_student
from ..tenancy import current_school_id
from ..utils.errors import duplicate, invalid_state, not_found
from ..utils.responses import (
    apply_pagination,
    body,
    body_list,
    created,
    ok,
    paginated,
    pagination_args,
)
from ..utils.validation import Validator, arg_uuid

bp = Blueprint("people", __name__)

STUDENT_IMPORT_COLUMNS = [
    "student_code",
    "first_name",
    "middle_name",
    "last_name",
    "date_of_birth",
    "gender",
    "admission_date",
    "guardian_first_name",
    "guardian_last_name",
    "guardian_phone",
    "guardian_email",
    "guardian_relationship",
]


# ==========================================================================
# Students
# ==========================================================================
@bp.get("/students")
@requires("students.view")
def list_students():
    page, per_page = pagination_args()
    query = Student.query.filter(Student.deleted_at.is_(None))

    allowed = accessible_student_ids() if is_scoped("students.view") else None
    if allowed is not None:
        if not allowed:
            return paginated([], page, per_page, 0)
        query = query.filter(Student.id.in_(allowed))

    search = (request.args.get("q") or "").strip()
    if search:
        pattern = f"%{search.lower()}%"
        query = query.filter(
            db.or_(
                db.func.lower(Student.first_name).like(pattern),
                db.func.lower(Student.last_name).like(pattern),
                db.func.lower(Student.student_code).like(pattern),
            )
        )

    statuses = [s for s in (request.args.get("status") or "").split(",") if s]
    if statuses:
        query = query.filter(Student.status.in_(statuses))

    class_id = arg_uuid("class_id")
    if class_id:
        from ..models import Enrollment

        enrolled = db.session.query(Enrollment.student_id).filter(
            Enrollment.class_id == class_id, Enrollment.status == "active"
        )
        query = query.filter(Student.id.in_(enrolled))

    sort_column = {
        "last_name": Student.last_name,
        "first_name": Student.first_name,
        "student_code": Student.student_code,
        "created_at": Student.created_at,
    }.get(request.args.get("sort", "last_name"), Student.last_name)
    if request.args.get("order", "asc") == "desc":
        sort_column = sort_column.desc()

    query = query.order_by(sort_column)
    items, total = apply_pagination(query, page, per_page)
    include_medical = has_permission("students.medical.view")
    return paginated([s.to_dict(include_medical) for s in items], page, per_page, total)


@bp.post("/students")
@requires("students.create")
def create_student():
    payload = body()
    validator = Validator(payload)
    student_code = validator.string("student_code", required=True, max_length=50)
    first_name = validator.string("first_name", required=True, max_length=100)
    validator.string("middle_name", max_length=100)
    last_name = validator.string("last_name", required=True, max_length=100)
    validator.date("date_of_birth")
    validator.string("gender", max_length=40)
    validator.date("admission_date", default=date.today())
    validator.string(
        "status", default="active", choices=("active", "graduated", "transferred", "withdrawn")
    )
    validator.string("photo_url")
    validator.string("medical_notes")
    validator.mapping("custom_fields", default={})
    data = validator.raise_if_invalid()

    if Student.query.filter_by(student_code=student_code).first():
        raise duplicate("A student with that code already exists in this school.")

    student = Student(
        school_id=current_school_id(),
        student_code=student_code,
        first_name=first_name,
        middle_name=data.get("middle_name"),
        last_name=last_name,
        date_of_birth=data.get("date_of_birth"),
        gender=data.get("gender"),
        admission_date=data.get("admission_date"),
        status=data.get("status") or "active",
        photo_url=data.get("photo_url"),
        medical_notes=data.get("medical_notes"),
        custom_fields=data.get("custom_fields") or {},
        created_by=current_user().id,
    )
    db.session.add(student)
    db.session.flush()

    record("create", "student", student.id, new_values=student.to_dict())
    db.session.commit()
    return created(student.to_dict(include_medical=has_permission("students.medical.view")))


@bp.get("/students/<uuid:student_id>")
@requires("students.view")
def get_student(student_id):
    student = assert_can_access_student(student_id, "students.view")
    return ok(student.to_dict(include_medical=has_permission("students.medical.view")))


@bp.patch("/students/<uuid:student_id>")
@requires("students.update")
def update_student(student_id):
    student = assert_can_access_student(student_id, "students.update")
    before = student.to_dict(include_medical=True)

    payload = body()
    validator = Validator(payload)
    editable = {
        "first_name": lambda: validator.string("first_name", max_length=100),
        "middle_name": lambda: validator.string("middle_name", max_length=100),
        "last_name": lambda: validator.string("last_name", max_length=100),
        "date_of_birth": lambda: validator.date("date_of_birth"),
        "gender": lambda: validator.string("gender", max_length=40),
        "admission_date": lambda: validator.date("admission_date"),
        "status": lambda: validator.string(
            "status", choices=("active", "graduated", "transferred", "withdrawn")
        ),
        "photo_url": lambda: validator.string("photo_url"),
        "custom_fields": lambda: validator.mapping("custom_fields"),
    }
    for field, read in editable.items():
        if field in payload:
            read()
    if "medical_notes" in payload:
        if not has_permission("students.medical.view"):
            raise invalid_state("You do not have permission to edit medical notes.")
        validator.string("medical_notes")
    data = validator.raise_if_invalid()

    for field, value in data.items():
        if field in payload:
            setattr(student, field, value)
    student.updated_by = current_user().id
    db.session.flush()

    old_values, new_values = diff(before, student.to_dict(include_medical=True))
    record("update", "student", student.id, old_values=old_values, new_values=new_values)
    db.session.commit()
    return ok(student.to_dict(include_medical=has_permission("students.medical.view")))


@bp.delete("/students/<uuid:student_id>")
@requires("students.delete")
def delete_student(student_id):
    student = Student.query.filter_by(id=student_id).first()
    if student is None or student.is_deleted:
        raise not_found("Student")
    student.soft_delete()
    student.updated_by = current_user().id
    record("delete", "student", student.id, old_values={"student_code": student.student_code})
    db.session.commit()
    return ok({"deleted": True})


# ==========================================================================
# Guardians
# ==========================================================================
@bp.get("/guardians")
@requires("guardians.manage")
def list_guardians():
    page, per_page = pagination_args()
    query = Guardian.query.filter(Guardian.deleted_at.is_(None))
    search = (request.args.get("q") or "").strip().lower()
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                db.func.lower(Guardian.first_name).like(pattern),
                db.func.lower(Guardian.last_name).like(pattern),
                db.func.lower(Guardian.phone).like(pattern),
            )
        )
    items, total = apply_pagination(query.order_by(Guardian.last_name), page, per_page)
    return paginated([g.to_dict() for g in items], page, per_page, total)


@bp.post("/guardians")
@requires("guardians.manage")
def create_guardian():
    payload = body()
    validator = Validator(payload)
    first_name = validator.string("first_name", required=True, max_length=100)
    last_name = validator.string("last_name", required=True, max_length=100)
    validator.email("email")
    validator.string("phone", max_length=40)
    validator.string("occupation", max_length=120)
    validator.string("address")
    data = validator.raise_if_invalid()

    guardian = Guardian(
        school_id=current_school_id(),
        first_name=first_name,
        last_name=last_name,
        email=data.get("email"),
        phone=data.get("phone"),
        occupation=data.get("occupation"),
        address=data.get("address"),
        created_by=current_user().id,
    )
    db.session.add(guardian)
    db.session.flush()
    record("create", "guardian", guardian.id, new_values=guardian.to_dict())
    db.session.commit()
    return created(guardian.to_dict())


@bp.get("/students/<uuid:student_id>/guardians")
@requires("students.view")
def list_student_guardians(student_id):
    student = assert_can_access_student(student_id, "students.view")
    links = StudentGuardian.query.filter_by(student_id=student.id).all()
    guardians = {
        g.id: g
        for g in Guardian.query.filter(
            Guardian.id.in_([link.guardian_id for link in links] or [None])
        ).all()
    }
    return ok(
        [
            {**link.to_dict(), "guardian": guardians[link.guardian_id].to_dict()}
            for link in links
            if link.guardian_id in guardians
        ]
    )


@bp.post("/students/<uuid:student_id>/guardians")
@requires("guardians.manage")
def link_guardian(student_id):
    """Link an existing guardian to a (second) child, or create and link."""
    student = Student.query.filter_by(id=student_id).first()
    if student is None or student.is_deleted:
        raise not_found("Student")

    payload = body()
    validator = Validator(payload)
    guardian_id = validator.uuid("guardian_id")
    relationship_type = validator.string("relationship_type", default="guardian", max_length=40)
    is_primary = validator.boolean("is_primary_contact", default=False)
    validator.raise_if_invalid()

    if guardian_id:
        guardian = Guardian.query.filter_by(id=guardian_id).first()
        if guardian is None:
            raise not_found("Guardian")
    else:
        sub = Validator(payload.get("guardian") or {})
        first_name = sub.string("first_name", required=True)
        last_name = sub.string("last_name", required=True)
        sub.email("email")
        sub.string("phone")
        guardian_data = sub.raise_if_invalid()
        guardian = Guardian(
            school_id=current_school_id(),
            first_name=first_name,
            last_name=last_name,
            email=guardian_data.get("email"),
            phone=guardian_data.get("phone"),
            created_by=current_user().id,
        )
        db.session.add(guardian)
        db.session.flush()

    if StudentGuardian.query.filter_by(student_id=student.id, guardian_id=guardian.id).first():
        raise duplicate("That guardian is already linked to this student.")

    if is_primary:
        for existing in StudentGuardian.query.filter_by(student_id=student.id).all():
            existing.is_primary_contact = False

    link = StudentGuardian(
        school_id=current_school_id(),
        student_id=student.id,
        guardian_id=guardian.id,
        relationship_type=relationship_type,
        is_primary_contact=is_primary,
    )
    db.session.add(link)
    db.session.flush()
    record("create", "student_guardian", link.id, new_values=link.to_dict())
    db.session.commit()
    return created({**link.to_dict(), "guardian": guardian.to_dict()})


@bp.delete("/students/<uuid:student_id>/guardians/<uuid:guardian_id>")
@requires("guardians.manage")
def unlink_guardian(student_id, guardian_id):
    link = StudentGuardian.query.filter_by(student_id=student_id, guardian_id=guardian_id).first()
    if link is None:
        raise not_found("Guardian link")
    record("delete", "student_guardian", link.id, old_values=link.to_dict())
    db.session.delete(link)
    db.session.commit()
    return ok({"unlinked": True})


# ==========================================================================
# Staff
# ==========================================================================
@bp.get("/staff")
@requires("staff.manage")
def list_staff():
    page, per_page = pagination_args()
    query = Staff.query.filter(Staff.deleted_at.is_(None))
    search = (request.args.get("q") or "").strip().lower()
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                db.func.lower(Staff.first_name).like(pattern),
                db.func.lower(Staff.last_name).like(pattern),
                db.func.lower(Staff.staff_code).like(pattern),
            )
        )
    items, total = apply_pagination(query.order_by(Staff.last_name), page, per_page)
    return paginated([s.to_dict() for s in items], page, per_page, total)


@bp.post("/staff")
@requires("staff.manage")
def create_staff():
    payload = body()
    validator = Validator(payload)
    staff_code = validator.string("staff_code", required=True, max_length=50)
    first_name = validator.string("first_name", required=True, max_length=100)
    last_name = validator.string("last_name", required=True, max_length=100)
    validator.email("email")
    validator.string("phone", max_length=40)
    validator.string("department", max_length=120)
    validator.string("qualification", max_length=200)
    validator.date("hired_on")
    data = validator.raise_if_invalid()

    if Staff.query.filter_by(staff_code=staff_code).first():
        raise duplicate("A staff member with that code already exists.")

    staff = Staff(
        school_id=current_school_id(),
        staff_code=staff_code,
        first_name=first_name,
        last_name=last_name,
        email=data.get("email"),
        phone=data.get("phone"),
        department=data.get("department"),
        qualification=data.get("qualification"),
        hired_on=data.get("hired_on"),
        created_by=current_user().id,
    )
    db.session.add(staff)
    db.session.flush()
    record("create", "staff", staff.id, new_values=staff.to_dict())
    db.session.commit()
    return created(staff.to_dict())


@bp.patch("/staff/<uuid:staff_id>")
@requires("staff.manage")
def update_staff(staff_id):
    staff = Staff.query.filter_by(id=staff_id).first()
    if staff is None or staff.is_deleted:
        raise not_found("Staff")
    before = staff.to_dict()

    payload = body()
    validator = Validator(payload)
    for field in ("first_name", "last_name", "department", "qualification", "phone"):
        if field in payload:
            validator.string(field, max_length=200)
    if "email" in payload:
        validator.email("email")
    if "status" in payload:
        validator.string("status", choices=("active", "suspended", "left"))
    data = validator.raise_if_invalid()

    for field, value in data.items():
        if field in payload:
            setattr(staff, field, value)
    staff.updated_by = current_user().id
    db.session.flush()

    old_values, new_values = diff(before, staff.to_dict())
    record("update", "staff", staff.id, old_values=old_values, new_values=new_values)
    db.session.commit()
    return ok(staff.to_dict())


# ==========================================================================
# Bulk import -- validate everything, then commit atomically
# ==========================================================================
@bp.get("/students/import/template")
@requires("students.import")
def import_template():
    return ok({"columns": STUDENT_IMPORT_COLUMNS, "format": "json_rows"})


@bp.post("/students/import")
@requires("students.import")
def import_students():
    """Dry run: report every bad row with its row number, write nothing."""
    rows = body_list()
    existing_codes = {s.student_code.lower() for s in Student.query.all()}
    seen_codes: set[str] = set()
    errors: list[dict] = []
    valid_rows: list[dict] = []

    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            errors.append({"row": index, "errors": {"_row": ["Expected an object."]}})
            continue

        validator = Validator(raw)
        code = validator.string("student_code", required=True, max_length=50)
        validator.string("first_name", required=True, max_length=100)
        validator.string("last_name", required=True, max_length=100)
        validator.string("middle_name", max_length=100)
        validator.date("date_of_birth")
        validator.date("admission_date")
        validator.string("gender", max_length=40)
        validator.string("guardian_first_name", max_length=100)
        validator.string("guardian_last_name", max_length=100)
        validator.string("guardian_phone", max_length=40)
        validator.email("guardian_email")
        validator.string("guardian_relationship", max_length=40, default="guardian")

        if code:
            if code.lower() in existing_codes:
                validator.add_error("student_code", "Already exists in this school.")
            elif code.lower() in seen_codes:
                validator.add_error("student_code", "Duplicated within this file.")
            else:
                seen_codes.add(code.lower())

        if validator.errors:
            errors.append({"row": index, "errors": validator.errors})
        else:
            payload = dict(validator.data)
            for key in ("date_of_birth", "admission_date"):
                if isinstance(payload.get(key), (date, datetime)):
                    payload[key] = payload[key].isoformat()
            valid_rows.append({"row": index, "data": payload})

    job = ImportJob(
        school_id=current_school_id(),
        entity_type="student",
        status="validated" if not errors else "validated_with_errors",
        total_rows=len(rows),
        valid_rows=len(valid_rows),
        error_rows=len(errors),
        errors=errors,
        payload=valid_rows,
        created_by=current_user().id,
    )
    db.session.add(job)
    db.session.commit()
    return ok(job.to_dict())


@bp.post("/students/import/<uuid:job_id>/commit")
@requires("students.import")
def commit_import(job_id):
    job = ImportJob.query.filter_by(id=job_id, entity_type="student").first()
    if job is None:
        raise not_found("Import job")
    if job.committed_at is not None:
        raise invalid_state("This import has already been committed.")
    if job.error_rows:
        raise invalid_state(
            f"This file has {job.error_rows} invalid row(s). Fix them and upload again."
        )

    created_students = 0
    created_guardians = 0
    for entry in job.payload or []:
        data = entry["data"]
        student = Student(
            school_id=current_school_id(),
            student_code=data["student_code"],
            first_name=data["first_name"],
            middle_name=data.get("middle_name"),
            last_name=data["last_name"],
            date_of_birth=_parse_date(data.get("date_of_birth")),
            gender=data.get("gender"),
            admission_date=_parse_date(data.get("admission_date")) or date.today(),
            created_by=current_user().id,
        )
        db.session.add(student)
        db.session.flush()
        created_students += 1

        if data.get("guardian_first_name") and data.get("guardian_last_name"):
            guardian = None
            if data.get("guardian_phone"):
                guardian = Guardian.query.filter_by(phone=data["guardian_phone"]).first()
            if guardian is None:
                guardian = Guardian(
                    school_id=current_school_id(),
                    first_name=data["guardian_first_name"],
                    last_name=data["guardian_last_name"],
                    phone=data.get("guardian_phone"),
                    email=data.get("guardian_email"),
                    created_by=current_user().id,
                )
                db.session.add(guardian)
                db.session.flush()
                created_guardians += 1
            db.session.add(
                StudentGuardian(
                    school_id=current_school_id(),
                    student_id=student.id,
                    guardian_id=guardian.id,
                    relationship_type=data.get("guardian_relationship") or "guardian",
                    is_primary_contact=True,
                )
            )

    job.committed_at = db.func.now()
    job.status = "committed"
    record(
        "create",
        "import_job",
        job.id,
        new_values={"students": created_students, "guardians": created_guardians},
    )
    db.session.commit()
    return ok(
        {
            "job": job.to_dict(),
            "students_created": created_students,
            "guardians_created": created_guardians,
        }
    )


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None
