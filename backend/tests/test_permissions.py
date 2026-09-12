"""Role and resource-scope enforcement (spec M2, Appendix B).

"May this person approve results?" is the role question. "For which class?" is
the one that gets forgotten, so most of this file is about the second.
"""

from __future__ import annotations

import pytest

from app.extensions import db


@pytest.fixture
def second_class(school_a):
    """A class the fixture teacher is NOT assigned to."""
    from app.models import ClassSubject, Enrollment, SchoolClass, Student
    from app.tenancy import set_current_school, tenant_context

    with tenant_context(school_a.school.id):
        set_current_school(school_a.school.id)
        other = SchoolClass(
            school_id=school_a.school.id,
            academic_year_id=SchoolClass.query.first().academic_year_id,
            name="Unassigned Class",
            level=99,
        )
        db.session.add(other)
        db.session.flush()

        for subject in school_a.subjects:
            db.session.add(
                ClassSubject(school_id=school_a.school.id, class_id=other.id, subject_id=subject.id)
            )

        student = Student(
            school_id=school_a.school.id,
            student_code="OTHER-1",
            first_name="Other",
            last_name="Pupil",
        )
        db.session.add(student)
        db.session.flush()
        db.session.add(
            Enrollment(
                school_id=school_a.school.id,
                student_id=student.id,
                class_id=other.id,
                academic_year_id=other.academic_year_id,
                enrolled_on=db.func.current_date(),
                status="active",
            )
        )
        db.session.commit()
        return {"class_id": other.id, "student_id": student.id}


# ==========================================================================
# Role-level checks
# ==========================================================================
def test_teacher_cannot_create_students(client, school_a, login):
    headers = login(school_a, "teacher")
    response = client.post(
        "/api/v1/students",
        json={"student_code": "X-1", "first_name": "New", "last_name": "Pupil"},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "PERMISSION_DENIED"


def test_teacher_cannot_approve_results(client, school_a, login):
    headers = login(school_a, "teacher")
    response = client.post(
        "/api/v1/results/approve",
        json={"class_id": str(school_a.class_id), "term_id": str(school_a.term_id)},
        headers=headers,
    )
    assert response.status_code == 403


def test_head_teacher_cannot_unlock_a_term(client, school_a, login):
    """Approval and unlocking are deliberately different powers."""
    headers = login(school_a, "head_teacher")
    response = client.post(
        f"/api/v1/terms/{school_a.term_id}/unlock",
        json={"reason": "Correcting a mark"},
        headers=headers,
    )
    assert response.status_code == 403


def test_admin_can_unlock_a_term_and_the_reason_is_audited(client, school_a, login):
    headers = login(school_a, "school_admin")
    client.post(f"/api/v1/terms/{school_a.term_id}/lock", json={}, headers=headers)
    response = client.post(
        f"/api/v1/terms/{school_a.term_id}/unlock",
        json={"reason": "Mathematics exam mark corrected after remark"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["results_locked"] is False

    from app.models import AuditLog
    from app.tenancy import set_current_school, tenant_context

    with tenant_context(school_a.school.id):
        set_current_school(school_a.school.id)
        entry = AuditLog.query.filter_by(action="unlock", entity_type="term").first()
    assert entry is not None
    assert "remark" in entry.reason


def test_student_cannot_list_the_whole_school(client, school_a, login):
    headers = login(school_a, "student")
    response = client.get("/api/v1/students?per_page=100", headers=headers)
    assert response.status_code == 200
    rows = response.get_json()["data"]
    assert len(rows) == 1
    assert rows[0]["student_code"] == school_a.students[0].student_code


def test_unauthenticated_request_is_401(client, school_a):
    response = client.get("/api/v1/students", headers={"X-School-Subdomain": school_a.subdomain})
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_permissions_are_returned_with_the_session(client, school_a, login):
    headers = login(school_a, "teacher")
    response = client.get("/api/v1/auth/me", headers=headers)
    data = response.get_json()["data"]
    assert "results.enter" in data["permissions"]
    assert "students.create" not in data["permissions"]
    assert data["roles"] == ["teacher"]


# ==========================================================================
# Resource scope -- the check that actually gets forgotten
# ==========================================================================
def test_teacher_cannot_enter_scores_for_a_class_they_do_not_teach(
    client, school_a, login, second_class
):
    headers = login(school_a, "teacher")
    response = client.post(
        "/api/v1/scores",
        json={
            "class_id": str(second_class["class_id"]),
            "subject_id": str(school_a.subjects[0].id),
            "term_id": str(school_a.term_id),
            "scores": [
                {
                    "student_id": str(second_class["student_id"]),
                    "component_id": str(school_a.components[0].id),
                    "raw_score": 100,
                }
            ],
        },
        headers=headers,
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "PERMISSION_DENIED"


def test_teacher_cannot_mark_attendance_for_another_class(client, school_a, login, second_class):
    headers = login(school_a, "teacher")
    response = client.post(
        "/api/v1/attendance",
        json={
            "class_id": str(second_class["class_id"]),
            "entries": [{"student_id": str(second_class["student_id"]), "status_code": "absent"}],
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_teacher_cannot_read_a_student_outside_their_classes(client, school_a, login, second_class):
    headers = login(school_a, "teacher")
    response = client.get(f"/api/v1/students/{second_class['student_id']}", headers=headers)
    assert response.status_code == 404


def test_teacher_can_act_within_their_own_class(client, school_a, login):
    headers = login(school_a, "teacher")
    response = client.post(
        "/api/v1/scores",
        json={
            "class_id": str(school_a.class_id),
            "subject_id": str(school_a.subjects[0].id),
            "term_id": str(school_a.term_id),
            "scores": [
                {
                    "student_id": str(school_a.students[0].id),
                    "component_id": str(school_a.components[0].id),
                    "raw_score": 55,
                }
            ],
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["scores_written"] == 1


def test_guardian_sees_only_their_own_children(client, school_a, login):
    headers = login(school_a, "guardian")
    response = client.get("/api/v1/students?per_page=100", headers=headers)
    assert response.status_code == 200
    rows = response.get_json()["data"]
    assert [row["student_code"] for row in rows] == [school_a.students[0].student_code]


def test_guardian_cannot_read_an_unlinked_child(client, school_a, login):
    headers = login(school_a, "guardian")
    response = client.get(f"/api/v1/students/{school_a.students[2].id}", headers=headers)
    assert response.status_code == 404


def test_student_cannot_read_another_students_results(client, school_a, login):
    headers = login(school_a, "student")
    response = client.get(f"/api/v1/students/{school_a.students[1].id}/results", headers=headers)
    assert response.status_code == 404


# ==========================================================================
# Medical notes are a restricted field, not general student data
# ==========================================================================
def test_medical_notes_are_hidden_from_a_teacher(client, school_a, login):
    from app.models import Student
    from app.tenancy import set_current_school, tenant_context

    with tenant_context(school_a.school.id):
        set_current_school(school_a.school.id)
        Student.query.filter_by(id=school_a.students[0].id).first().medical_notes = "Asthma"
        db.session.commit()

    teacher_headers = login(school_a, "teacher")
    response = client.get(f"/api/v1/students/{school_a.students[0].id}", headers=teacher_headers)
    assert response.status_code == 200
    assert "medical_notes" not in response.get_json()["data"]

    admin_headers = login(school_a, "school_admin")
    response = client.get(f"/api/v1/students/{school_a.students[0].id}", headers=admin_headers)
    assert response.get_json()["data"]["medical_notes"] == "Asthma"
