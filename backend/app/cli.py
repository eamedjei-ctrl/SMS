"""Flask CLI commands: bootstrap, seed templates, and a working demo school."""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import click
from flask import Flask
from flask.cli import with_appcontext

from .extensions import db

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def register_cli(app: Flask) -> None:
    app.cli.add_command(bootstrap)
    app.cli.add_command(seed_templates)
    app.cli.add_command(create_platform_user)
    app.cli.add_command(seed_demo)


@click.command("bootstrap")
@with_appcontext
def bootstrap():
    """Create tables (dev only -- use migrations elsewhere) and sync permissions."""
    from .services.provisioning import ensure_permission_catalog

    db.create_all()
    ensure_permission_catalog()
    db.session.commit()
    click.echo("Schema ready and permission catalogue synced.")


@click.command("seed-templates")
@with_appcontext
def seed_templates():
    """Load the curriculum seed templates from ./seed into the platform tier."""
    from .models import CurriculumTemplate
    from .tenancy import unscoped

    loaded = 0
    with unscoped():  # platform tier: shared templates
        for path in sorted(SEED_DIR.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            key = payload["template_id"]
            template = CurriculumTemplate.query.filter_by(template_key=key).first()
            if template is None:
                template = CurriculumTemplate(template_key=key)
                db.session.add(template)
            template.name = payload["name"]
            template.curriculum = payload["curriculum"]
            template.country = payload.get("country", "GH")
            template.version = int(payload.get("version", 1))
            template.payload = payload
            template.is_active = True
            loaded += 1
        db.session.commit()
    click.echo(f"Loaded {loaded} curriculum template(s).")


@click.command("create-platform-user")
@click.option("--email", required=True)
@click.option("--name", required=True)
@click.option("--password", required=True, prompt=True, hide_input=True)
@click.option(
    "--role", default="platform_admin", type=click.Choice(["platform_admin", "platform_support"])
)
@with_appcontext
def create_platform_user(email: str, name: str, password: str, role: str):
    """Create one of our own staff accounts."""
    from .models import PlatformUser
    from .security import hash_password
    from .tenancy import unscoped

    with unscoped():  # platform tier
        if PlatformUser.query.filter_by(email=email.lower()).first():
            raise click.ClickException("A platform account with that email already exists.")
        db.session.add(
            PlatformUser(
                email=email.lower(),
                full_name=name,
                password_hash=hash_password(password),
                role=role,
            )
        )
        db.session.commit()
    click.echo(f"Created platform user {email} ({role}).")


@click.command("seed-demo")
@click.option("--subdomain", default="demo")
@click.option("--name", default="Demo Basic School")
@click.option("--template", "template_key", default="ges-basic-v1")
@click.option("--password", default="Passw0rd!demo", show_default=True)
@click.option("--students", "student_count", default=30, show_default=True)
@with_appcontext
def seed_demo(subdomain: str, name: str, template_key: str, password: str, student_count: int):
    """A working demo school in one command: configured, populated, computed."""
    from .models import (
        AssessmentComponent,
        ClassSubject,
        ClassSubjectTeacher,
        CurriculumTemplate,
        Enrollment,
        Guardian,
        Role,
        School,
        SchoolClass,
        Staff,
        Student,
        StudentGuardian,
        Term,
        User,
    )
    from .security import hash_password
    from .services.provisioning import (
        apply_curriculum_template,
        attach_subjects_to_classes,
        mark_onboarding_complete,
        provision_school_defaults,
    )
    from .services.results_engine import recompute_class_term
    from .tenancy import set_current_school, tenant_context, unscoped

    random.seed(42)

    with unscoped():  # platform tier: the school registry
        if School.query.filter_by(subdomain=subdomain).first():
            raise click.ClickException(
                f"A school with subdomain '{subdomain}' already exists. Pick another."
            )
        template = CurriculumTemplate.query.filter_by(template_key=template_key).first()
        if template is None:
            raise click.ClickException(
                f"Template '{template_key}' not found. Run `flask seed-templates` first."
            )
        school = School(
            name=name,
            subdomain=subdomain,
            curriculum_mode=template.curriculum,
            status="active",
        )
        db.session.add(school)
        db.session.flush()
        template_payload = template.payload

    with tenant_context(school.id):
        set_current_school(school.id)
        provision_school_defaults(school)
        apply_curriculum_template(school, template_payload)
        attach_subjects_to_classes(school.id)
        db.session.flush()

        roles = {r.key: r for r in Role.query.all()}

        def make_user(full_name: str, email: str, role_key: str) -> User:
            user = User(
                school_id=school.id,
                full_name=full_name,
                email=email,
                password_hash=hash_password(password),
                status="active",
            )
            user.roles.append(roles[role_key])
            db.session.add(user)
            db.session.flush()
            return user

        admin_user = make_user("Grace Owusu", f"admin@{subdomain}.test", "school_admin")
        head_user = make_user("Kwame Asare", f"head@{subdomain}.test", "head_teacher")
        teacher_user = make_user("Daniel Mensah", f"teacher@{subdomain}.test", "teacher")

        teacher_staff = Staff(
            school_id=school.id,
            user_id=teacher_user.id,
            staff_code="T-101",
            first_name="Daniel",
            last_name="Mensah",
            email=teacher_user.email,
            department="Mathematics",
        )
        db.session.add(teacher_staff)
        db.session.flush()

        school_class = SchoolClass.query.order_by(SchoolClass.level).first()
        school_class.class_teacher_id = teacher_staff.id

        class_subjects = ClassSubject.query.filter_by(class_id=school_class.id).all()
        for class_subject in class_subjects:
            db.session.add(
                ClassSubjectTeacher(
                    school_id=school.id,
                    class_subject_id=class_subject.id,
                    staff_id=teacher_staff.id,
                )
            )

        term = Term.query.filter_by(is_current=True).first()
        components = AssessmentComponent.query.filter_by(is_active=True).all()

        first_names = [
            "Kojo",
            "Abena",
            "Yaw",
            "Efua",
            "Kwesi",
            "Adjoa",
            "Kofi",
            "Ama",
            "Nana",
            "Akosua",
        ]
        last_names = ["Mensah", "Owusu", "Boadi", "Ansah", "Appiah", "Frimpong", "Asare", "Baidoo"]

        students = []
        for index in range(student_count):
            student = Student(
                school_id=school.id,
                student_code=f"{subdomain.upper()[:3]}-{2200 + index}",
                first_name=random.choice(first_names),
                last_name=random.choice(last_names),
                date_of_birth=date(2014, 1, 1) + timedelta(days=random.randint(0, 900)),
                gender=random.choice(["M", "F"]),
                admission_date=date.today() - timedelta(days=random.randint(30, 700)),
            )
            db.session.add(student)
            db.session.flush()
            students.append(student)

            db.session.add(
                Enrollment(
                    school_id=school.id,
                    student_id=student.id,
                    class_id=school_class.id,
                    academic_year_id=school_class.academic_year_id,
                    enrolled_on=date.today() - timedelta(days=30),
                    status="active",
                )
            )

        # One guardian with two children, so the "many wards, one login" path is real.
        guardian = Guardian(
            school_id=school.id,
            first_name="Yaw",
            last_name="Mensah",
            phone="+233200000001",
            email=f"parent@{subdomain}.test",
        )
        db.session.add(guardian)
        db.session.flush()
        guardian_user = make_user(guardian.full_name, guardian.email, "guardian")
        guardian.user_id = guardian_user.id

        for student in students[:2]:
            db.session.add(
                StudentGuardian(
                    school_id=school.id,
                    student_id=student.id,
                    guardian_id=guardian.id,
                    relationship_type="father",
                    is_primary_contact=student is students[0],
                )
            )

        student_user = make_user(students[0].full_name, f"student@{subdomain}.test", "student")
        students[0].user_id = student_user.id

        from .models import AssessmentScore

        for student in students:
            for class_subject in class_subjects:
                ability = random.randint(35, 95)
                for component in components:
                    raw = max(
                        0,
                        min(
                            float(component.max_score),
                            random.gauss(
                                ability / 100 * float(component.max_score),
                                float(component.max_score) * 0.08,
                            ),
                        ),
                    )
                    db.session.add(
                        AssessmentScore(
                            school_id=school.id,
                            student_id=student.id,
                            subject_id=class_subject.subject_id,
                            class_id=school_class.id,
                            term_id=term.id,
                            component_id=component.id,
                            raw_score=Decimal(str(round(raw, 2))),
                            entered_by=teacher_user.id,
                        )
                    )
        db.session.flush()

        summary = recompute_class_term(school_class.id, term.id)
        mark_onboarding_complete(school)
        db.session.commit()

    click.echo(
        "\n".join(
            [
                f"Demo school ready: {name} ({subdomain})",
                f"  classes seeded from template: {template_key}",
                f"  students: {len(students)} in {school_class.display_name}",
                f"  subjects: {len(class_subjects)}, components: {len(components)}",
                f"  results computed: {summary['results_written']}",
                "",
                "Sign in with X-School-Subdomain: " + subdomain,
                f"  admin    {admin_user.email}",
                f"  head     {head_user.email}",
                f"  teacher  {teacher_user.email}",
                f"  student  {student_user.email}",
                f"  guardian {guardian_user.email}",
                f"  password {password}",
            ]
        )
    )
