from __future__ import annotations

import json
import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app  # noqa: E402
from app.extensions import db as _db  # noqa: E402

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


@pytest.fixture(scope="session")
def app():
    application = create_app("testing")
    application.config.update(TESTING=True, STORAGE_LOCAL_PATH="")
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(autouse=True)
def clean_database(app):
    """Every test starts from an empty database."""
    yield
    _db.session.rollback()
    for table in reversed(_db.metadata.sorted_tables):
        _db.session.execute(table.delete())
    _db.session.commit()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def templates(app):
    """Load the real curriculum seed templates into the platform tier."""
    from app.models import CurriculumTemplate
    from app.tenancy import unscoped

    loaded = {}
    with unscoped():
        for path in sorted(SEED_DIR.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            template = CurriculumTemplate(
                template_key=payload["template_id"],
                name=payload["name"],
                curriculum=payload["curriculum"],
                country=payload.get("country", "GH"),
                version=int(payload.get("version", 1)),
                payload=payload,
            )
            _db.session.add(template)
            loaded[payload["template_id"]] = payload
        _db.session.commit()
    return loaded


class SchoolFixture:
    """A fully configured school with people, scores and computed results."""

    def __init__(self, school, users, class_id, term_id, students, subjects, components):
        self.school = school
        self.users = users
        self.class_id = class_id
        self.term_id = term_id
        self.students = students
        self.subjects = subjects
        self.components = components

    @property
    def subdomain(self):
        return self.school.subdomain


def build_school(subdomain: str, name: str, template_payload: dict, student_count: int = 4):
    from app.models import (
        AssessmentComponent,
        ClassSubject,
        ClassSubjectTeacher,
        Enrollment,
        Guardian,
        Role,
        School,
        SchoolClass,
        Staff,
        Student,
        StudentGuardian,
        Subject,
        Term,
        User,
    )
    from app.security import hash_password
    from app.services.provisioning import (
        apply_curriculum_template,
        attach_subjects_to_classes,
        mark_onboarding_complete,
        provision_school_defaults,
    )
    from app.tenancy import set_current_school, tenant_context, unscoped

    with unscoped():
        school = School(
            name=name,
            subdomain=subdomain,
            curriculum_mode=template_payload["curriculum"],
            status="active",
        )
        _db.session.add(school)
        _db.session.flush()

    with tenant_context(school.id):
        set_current_school(school.id)
        provision_school_defaults(school)
        apply_curriculum_template(school, template_payload)
        attach_subjects_to_classes(school.id)
        _db.session.flush()

        roles = {r.key: r for r in Role.query.all()}
        users = {}

        def make_user(role_key: str, full_name: str) -> User:
            user = User(
                school_id=school.id,
                full_name=full_name,
                email=f"{role_key}@{subdomain}.test",
                password_hash=hash_password("Passw0rd!test"),
                status="active",
            )
            user.roles.append(roles[role_key])
            _db.session.add(user)
            _db.session.flush()
            users[role_key] = user
            return user

        make_user("school_admin", "Admin User")
        make_user("head_teacher", "Head Teacher")
        teacher_user = make_user("teacher", "Teacher User")
        student_user = make_user("student", "Student User")
        guardian_user = make_user("guardian", "Guardian User")

        staff = Staff(
            school_id=school.id,
            user_id=teacher_user.id,
            staff_code="T-1",
            first_name="Teacher",
            last_name="User",
        )
        _db.session.add(staff)
        _db.session.flush()

        school_class = SchoolClass.query.order_by(SchoolClass.level).first()
        school_class.class_teacher_id = staff.id
        class_subjects = ClassSubject.query.filter_by(class_id=school_class.id).all()
        for class_subject in class_subjects:
            _db.session.add(
                ClassSubjectTeacher(
                    school_id=school.id,
                    class_subject_id=class_subject.id,
                    staff_id=staff.id,
                )
            )

        term = Term.query.filter_by(is_current=True).first()
        components = AssessmentComponent.query.order_by(AssessmentComponent.sequence).all()

        students = []
        for index in range(student_count):
            student = Student(
                school_id=school.id,
                student_code=f"{subdomain.upper()}-{100 + index}",
                first_name=f"Student{index}",
                last_name=subdomain.capitalize(),
                admission_date=date.today() - timedelta(days=60),
            )
            _db.session.add(student)
            _db.session.flush()
            students.append(student)
            _db.session.add(
                Enrollment(
                    school_id=school.id,
                    student_id=student.id,
                    class_id=school_class.id,
                    academic_year_id=school_class.academic_year_id,
                    enrolled_on=date.today() - timedelta(days=30),
                    status="active",
                )
            )

        students[0].user_id = student_user.id

        guardian = Guardian(
            school_id=school.id,
            first_name="Guardian",
            last_name="User",
            user_id=guardian_user.id,
            phone=f"+2332000{abs(hash(subdomain)) % 10000:04d}",
        )
        _db.session.add(guardian)
        _db.session.flush()
        _db.session.add(
            StudentGuardian(
                school_id=school.id,
                student_id=students[0].id,
                guardian_id=guardian.id,
                relationship_type="father",
                is_primary_contact=True,
            )
        )

        mark_onboarding_complete(school)
        _db.session.commit()

        subjects = Subject.query.all()
        return SchoolFixture(
            school=school,
            users=users,
            class_id=school_class.id,
            term_id=term.id,
            students=students,
            subjects=subjects,
            components=components,
        )


@pytest.fixture
def school_a(app, templates):
    return build_school("alpha", "Alpha Basic School", templates["ges-basic-v1"])


@pytest.fixture
def school_b(app, templates):
    return build_school(
        "beta", "Beta International School", templates["cambridge-lower-secondary-v1"]
    )


@pytest.fixture
def login(client):
    """Sign in and return the auth headers for a role at a school."""

    def _login(school: SchoolFixture, role_key: str = "school_admin", password="Passw0rd!test"):
        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": f"{role_key}@{school.subdomain}.test", "password": password},
            headers={"X-School-Subdomain": school.subdomain},
        )
        assert response.status_code == 200, response.get_json()
        token = response.get_json()["data"]["access_token"]
        return {
            "Authorization": f"Bearer {token}",
            "X-School-Subdomain": school.subdomain,
        }

    return _login


@pytest.fixture
def enter_scores(app):
    """Write raw scores directly, so result tests do not depend on the API."""

    def _enter(school: SchoolFixture, values: dict):
        """values: {student_index: {component_code: raw_score}} for every subject."""
        from app.models import AssessmentScore
        from app.tenancy import set_current_school, tenant_context

        with tenant_context(school.school.id):
            set_current_school(school.school.id)
            components = {c.code: c for c in school.components}
            for student_index, component_scores in values.items():
                student = school.students[student_index]
                for subject in school.subjects:
                    for code, raw in component_scores.items():
                        _db.session.add(
                            AssessmentScore(
                                school_id=school.school.id,
                                student_id=student.id,
                                subject_id=subject.id,
                                class_id=school.class_id,
                                term_id=school.term_id,
                                component_id=components[code].id,
                                raw_score=None if raw is None else Decimal(str(raw)),
                                is_absent=raw is None,
                            )
                        )
            _db.session.commit()

    return _enter
