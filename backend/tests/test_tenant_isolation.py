"""Tenant isolation (spec 8.2). If anything here fails, nothing ships.

Two schools are created with identical data shapes, then School A's session is
pointed at every School B resource we can name.
"""

from __future__ import annotations

import pytest

from app.extensions import db


@pytest.fixture
def two_schools(school_a, school_b):
    return school_a, school_b


# ==========================================================================
# 1. Reading another tenant's records by id
# ==========================================================================
def test_cannot_read_another_schools_student(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    victim = beta.students[0]

    response = client.get(f"/api/v1/students/{victim.id}", headers=headers)
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_cannot_read_another_schools_class_roster(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    response = client.get(f"/api/v1/classes/{beta.class_id}/roster", headers=headers)
    assert response.status_code == 404


def test_cannot_read_another_schools_broadsheet(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "head_teacher")
    response = client.get(
        f"/api/v1/results/broadsheet?class_id={beta.class_id}&term_id={beta.term_id}",
        headers=headers,
    )
    assert response.status_code == 404


def test_cannot_read_another_schools_results(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    response = client.get(f"/api/v1/students/{beta.students[0].id}/results", headers=headers)
    assert response.status_code == 404


def test_listing_never_includes_another_tenants_rows(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")

    response = client.get("/api/v1/students?per_page=100", headers=headers)
    assert response.status_code == 200
    codes = {row["student_code"] for row in response.get_json()["data"]}

    assert codes == {s.student_code for s in alpha.students}
    assert not codes & {s.student_code for s in beta.students}


def test_subject_and_class_lists_are_scoped(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")

    subjects = client.get("/api/v1/subjects", headers=headers).get_json()["data"]
    classes = client.get("/api/v1/classes", headers=headers).get_json()["data"]

    beta_class_ids = {str(beta.class_id)}
    assert not {c["id"] for c in classes} & beta_class_ids
    # Both schools have subjects; Alpha must only see its own rows.
    assert len(subjects) == len(alpha.subjects)


# ==========================================================================
# 2. Writing to another tenant's records
# ==========================================================================
def test_cannot_update_another_schools_student(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    response = client.patch(
        f"/api/v1/students/{beta.students[0].id}",
        json={"first_name": "Hijacked"},
        headers=headers,
    )
    assert response.status_code == 404

    db.session.expire_all()
    from app.models import Student
    from app.tenancy import tenant_context, set_current_school

    with tenant_context(beta.school.id):
        set_current_school(beta.school.id)
        assert Student.query.filter_by(id=beta.students[0].id).first().first_name != "Hijacked"


def test_cannot_delete_another_schools_student(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    response = client.delete(f"/api/v1/students/{beta.students[0].id}", headers=headers)
    assert response.status_code == 404


def test_cannot_enter_scores_for_another_schools_class(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "teacher")
    response = client.post(
        "/api/v1/scores",
        json={
            "class_id": str(beta.class_id),
            "subject_id": str(beta.subjects[0].id),
            "term_id": str(beta.term_id),
            "scores": [
                {
                    "student_id": str(beta.students[0].id),
                    "component_id": str(beta.components[0].id),
                    "raw_score": 99,
                }
            ],
        },
        headers=headers,
    )
    assert response.status_code == 404


def test_cannot_mark_attendance_for_another_schools_class(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "teacher")
    response = client.post(
        "/api/v1/attendance",
        json={
            "class_id": str(beta.class_id),
            "entries": [{"student_id": str(beta.students[0].id), "status_code": "absent"}],
        },
        headers=headers,
    )
    assert response.status_code == 404


def test_cannot_enroll_another_schools_student_into_own_class(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    response = client.post(
        "/api/v1/enrollments",
        json={"student_id": str(beta.students[0].id), "class_id": str(alpha.class_id)},
        headers=headers,
    )
    assert response.status_code == 404


def test_cannot_approve_another_schools_results(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "head_teacher")
    response = client.post(
        "/api/v1/results/approve",
        json={"class_id": str(beta.class_id), "term_id": str(beta.term_id)},
        headers=headers,
    )
    assert response.status_code == 404


def test_cannot_generate_report_card_for_another_schools_student(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    response = client.post(
        "/api/v1/report-cards/generate",
        json={"student_id": str(beta.students[0].id), "term_id": str(beta.term_id)},
        headers=headers,
    )
    assert response.status_code == 404


# ==========================================================================
# 3. Injected school_id must be ignored
# ==========================================================================
def test_school_id_in_the_request_body_is_ignored(client, two_schools, login):
    """A client-supplied school_id must never influence where a row lands."""
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")

    response = client.post(
        "/api/v1/students",
        json={
            "school_id": str(beta.school.id),
            "student_code": "INJECT-1",
            "first_name": "Injected",
            "last_name": "Row",
        },
        headers=headers,
    )
    assert response.status_code == 201

    from app.models import Student
    from app.tenancy import set_current_school, tenant_context

    with tenant_context(alpha.school.id):
        set_current_school(alpha.school.id)
        assert Student.query.filter_by(student_code="INJECT-1").first() is not None
    with tenant_context(beta.school.id):
        set_current_school(beta.school.id)
        assert Student.query.filter_by(student_code="INJECT-1").first() is None


def test_school_id_in_the_query_string_is_ignored(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    response = client.get(
        f"/api/v1/students?school_id={beta.school.id}&per_page=100", headers=headers
    )
    assert response.status_code == 200
    codes = {row["student_code"] for row in response.get_json()["data"]}
    assert not codes & {s.student_code for s in beta.students}


# ==========================================================================
# 4. A token from one school presented at another school's subdomain
# ==========================================================================
def test_token_from_school_a_rejected_at_school_b_subdomain(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    headers["X-School-Subdomain"] = beta.subdomain

    response = client.get("/api/v1/students", headers=headers)
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "TENANT_MISMATCH"


def test_tenant_mismatch_writes_a_security_audit_entry(client, two_schools, login):
    alpha, beta = two_schools
    headers = login(alpha, "school_admin")
    headers["X-School-Subdomain"] = beta.subdomain
    client.get("/api/v1/students", headers=headers)

    from app.models import AuditLog
    from app.tenancy import set_current_school, tenant_context

    with tenant_context(beta.school.id):
        set_current_school(beta.school.id)
        entry = AuditLog.query.filter_by(action="security", entity_id="tenant_mismatch").first()
    assert entry is not None
    assert entry.new_values["token_school_id"] == str(alpha.school.id)


def test_credentials_from_one_school_do_not_work_at_another(client, two_schools):
    alpha, beta = two_schools
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": f"school_admin@{alpha.subdomain}.test", "password": "Passw0rd!test"},
        headers={"X-School-Subdomain": beta.subdomain},
    )
    assert response.status_code == 401


def test_unknown_subdomain_is_404(client, school_a):
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "someone@nowhere.test", "password": "whatever"},
        headers={"X-School-Subdomain": "does-not-exist"},
    )
    assert response.status_code == 404


def test_suspended_school_is_blocked_with_402(client, school_a, login):
    headers = login(school_a, "school_admin")

    from app.models import School
    from app.tenancy import unscoped

    with unscoped():
        School.query.filter_by(id=school_a.school.id).first().status = "suspended"
        db.session.commit()

    response = client.get("/api/v1/students", headers=headers)
    assert response.status_code == 402
    assert response.get_json()["error"]["code"] == "SUBSCRIPTION_INACTIVE"


# ==========================================================================
# 5. The ORM guard itself
# ==========================================================================
def test_orm_queries_are_scoped_without_any_explicit_filter(app, two_schools):
    """The guard, not developer discipline, is what enforces isolation."""
    from app.models import Student
    from app.tenancy import set_current_school, tenant_context

    with tenant_context(two_schools[0].school.id):
        set_current_school(two_schools[0].school.id)
        assert Student.query.count() == len(two_schools[0].students)

    with tenant_context(two_schools[1].school.id):
        set_current_school(two_schools[1].school.id)
        assert Student.query.count() == len(two_schools[1].students)


def test_no_tenant_bound_returns_nothing_rather_than_everything(app, two_schools):
    """A missing tenant context must fail closed."""
    from app.models import Student
    from app.tenancy import set_current_school, tenant_context

    with tenant_context(None):
        set_current_school(None)
        assert Student.query.count() == 0


def test_joins_are_scoped_too(app, two_schools):
    """A query that never mentions school_id still cannot cross the boundary."""
    from app.models import Enrollment, Student
    from app.tenancy import set_current_school, tenant_context

    alpha, beta = two_schools
    with tenant_context(alpha.school.id):
        set_current_school(alpha.school.id)
        rows = db.session.query(Student).join(Enrollment, Enrollment.student_id == Student.id).all()
        assert {r.id for r in rows} == {s.id for s in alpha.students}


def test_relationship_loads_do_not_leak(app, two_schools):
    from app.models import Role, User
    from app.tenancy import set_current_school, tenant_context

    alpha, _ = two_schools
    with tenant_context(alpha.school.id):
        set_current_school(alpha.school.id)
        user = User.query.filter_by(email=f"teacher@{alpha.subdomain}.test").first()
        assert user is not None
        for role in user.roles:
            assert role.school_id == alpha.school.id
        assert Role.query.count() == 5


# ==========================================================================
# 6. Redis keys are tenant-namespaced
# ==========================================================================
def test_every_cache_key_carries_the_school_id(app, school_a):
    """A cache key without school_id is a cross-tenant leak waiting to happen."""
    from app.services import token_store
    from app.tenancy import set_current_school, tenant_context

    with app.test_request_context():
        with tenant_context(school_a.school.id):
            set_current_school(school_a.school.id)
            key = token_store._key("some-jti")

    # The session blacklist is keyed by jti, which is unique per token issue --
    # every other namespace must carry the tenant id explicitly.
    assert key.startswith(f"{app.config['ENV_NAME']}:v1:session:blacklist:")

    from app.services.cache_keys import (
        class_results_key,
        report_card_key,
        school_config_key,
        user_permissions_key,
    )

    school_id = school_a.school.id
    for key in (
        school_config_key("grading", school_id=school_id),
        class_results_key("class-1", "term-1", school_id=school_id),
        report_card_key("student-1", "term-1", school_id=school_id),
        user_permissions_key("user-1", school_id=school_id),
    ):
        assert f":t:{school_id}:" in key, f"{key} is not tenant-namespaced"
