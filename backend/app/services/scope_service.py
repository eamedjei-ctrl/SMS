"""Resource-level scope checks.

"May this person enter results?" is the role question. "For which class?" is this
module. A teacher holding ``results.enter`` may only touch the class-subject
pairs assigned to them; a guardian holding ``results.view`` may only see students
linked to them. Role alone is never sufficient authorisation.
"""

from __future__ import annotations

import uuid

from ..models import (
    ClassSubject,
    ClassSubjectTeacher,
    Enrollment,
    Guardian,
    SchoolClass,
    Staff,
    Student,
    StudentGuardian,
)
from ..permissions import GUARDIAN, HEAD_TEACHER, SCHOOL_ADMIN, STUDENT, TEACHER
from ..security import current_roles, current_user, is_scoped
from ..utils.errors import not_found, permission_denied


def staff_for_current_user() -> Staff | None:
    user = current_user()
    if user is None:
        return None
    return Staff.query.filter_by(user_id=user.id).first()


def student_for_current_user() -> Student | None:
    user = current_user()
    if user is None:
        return None
    return Student.query.filter_by(user_id=user.id).first()


def guardian_for_current_user() -> Guardian | None:
    user = current_user()
    if user is None:
        return None
    return Guardian.query.filter_by(user_id=user.id).first()


def has_role(role_key: str) -> bool:
    return role_key in current_roles()


def is_privileged() -> bool:
    """School-wide roles see everything within their own tenant."""
    return has_role(SCHOOL_ADMIN) or has_role(HEAD_TEACHER)


def taught_class_subject_ids() -> set[uuid.UUID]:
    staff = staff_for_current_user()
    if staff is None:
        return set()
    rows = ClassSubjectTeacher.query.filter_by(staff_id=staff.id).all()
    return {row.class_subject_id for row in rows}


def taught_class_ids() -> set[uuid.UUID]:
    staff = staff_for_current_user()
    if staff is None:
        return set()
    class_ids = {
        row.class_id
        for row in ClassSubject.query.filter(
            ClassSubject.id.in_(
                [r.class_subject_id for r in ClassSubjectTeacher.query.filter_by(staff_id=staff.id)]
            )
        ).all()
    }
    # A class teacher owns their whole class, not only the subjects they teach.
    class_ids |= {c.id for c in SchoolClass.query.filter_by(class_teacher_id=staff.id).all()}
    return class_ids


def guarded_student_ids() -> set[uuid.UUID]:
    guardian = guardian_for_current_user()
    if guardian is None:
        return set()
    return {
        link.student_id for link in StudentGuardian.query.filter_by(guardian_id=guardian.id).all()
    }


def accessible_student_ids() -> set[uuid.UUID] | None:
    """``None`` means "no restriction beyond the tenant"."""
    if is_privileged():
        return None
    if has_role(GUARDIAN):
        return guarded_student_ids()
    if has_role(STUDENT):
        student = student_for_current_user()
        return {student.id} if student else set()
    if has_role(TEACHER):
        class_ids = taught_class_ids()
        if not class_ids:
            return set()
        rows = Enrollment.query.filter(
            Enrollment.class_id.in_(class_ids), Enrollment.status == "active"
        ).all()
        return {row.student_id for row in rows}
    return set()


def assert_can_access_student(student_id, permission: str = "students.view") -> Student:
    student = Student.query.filter_by(id=student_id).first()
    if student is None or student.is_deleted:
        raise not_found("Student")
    if not is_scoped(permission):
        return student
    allowed = accessible_student_ids()
    if allowed is not None and student.id not in allowed:
        # Outside the caller's scope: 404, so the response cannot confirm the row exists.
        raise not_found("Student")
    return student


def assert_can_access_class(class_id, permission: str = "classes.view") -> SchoolClass:
    school_class = SchoolClass.query.filter_by(id=class_id).first()
    if school_class is None or school_class.is_deleted:
        raise not_found("Class")
    if not is_scoped(permission):
        return school_class
    if has_role(TEACHER) and school_class.id in taught_class_ids():
        return school_class
    if has_role(STUDENT) or has_role(GUARDIAN):
        student_ids = accessible_student_ids() or set()
        if student_ids:
            enrolled = Enrollment.query.filter(
                Enrollment.class_id == school_class.id,
                Enrollment.student_id.in_(student_ids),
                Enrollment.status == "active",
            ).first()
            if enrolled:
                return school_class
    raise not_found("Class")


def assert_can_mark_class(class_id, permission: str = "attendance.mark") -> SchoolClass:
    school_class = SchoolClass.query.filter_by(id=class_id).first()
    if school_class is None or school_class.is_deleted:
        raise not_found("Class")
    if not is_scoped(permission):
        return school_class
    if school_class.id not in taught_class_ids():
        raise permission_denied("You are not assigned to this class.")
    return school_class


def assert_can_enter_results(
    class_id, subject_id, permission: str = "results.enter"
) -> ClassSubject:
    class_subject = ClassSubject.query.filter_by(class_id=class_id, subject_id=subject_id).first()
    if class_subject is None:
        raise not_found("Class subject")
    if not is_scoped(permission):
        return class_subject
    if class_subject.id not in taught_class_subject_ids():
        raise permission_denied("You are not assigned to this class and subject.")
    return class_subject
