"""M1 -- the ten-step configuration wizard, resumable."""

from __future__ import annotations

from flask import Blueprint

from ..extensions import db
from ..models import CurriculumTemplate, OnboardingProgress, School
from ..security import requires
from ..services.audit_service import record
from ..services.provisioning import (
    apply_curriculum_template,
    attach_subjects_to_classes,
    mark_onboarding_complete,
)
from ..tenancy import current_school_id, unscoped
from ..utils.errors import invalid_state, not_found
from ..utils.responses import body, ok
from ..utils.validation import Validator

bp = Blueprint("onboarding", __name__)

WIZARD_STEPS = [
    "school_identity",
    "curriculum_choice",
    "academic_calendar",
    "class_structure",
    "subjects",
    "assessment_setup",
    "grading_scale",
    "report_card",
    "admin_account",
    "review",
]


def _progress() -> OnboardingProgress:
    progress = OnboardingProgress.query.first()
    if progress is None:
        progress = OnboardingProgress(school_id=current_school_id())
        db.session.add(progress)
        db.session.flush()
    return progress


def _school() -> School:
    with unscoped():  # platform tier: the school registry is not tenant-owned
        school = School.query.filter_by(id=current_school_id()).first()
    if school is None:
        raise not_found("School")
    return school


@bp.get("/onboarding")
@requires("onboarding.manage")
def get_progress():
    progress = _progress()
    school = _school()
    db.session.commit()
    return ok(
        {
            "steps": WIZARD_STEPS,
            "progress": progress.to_dict(),
            "school": school.to_dict(),
            "is_complete": school.is_onboarded,
        }
    )


@bp.put("/onboarding/steps/<step_key>")
@requires("onboarding.manage")
def save_step(step_key: str):
    """Save-and-resume: each step persists on its own."""
    if step_key not in WIZARD_STEPS:
        raise not_found("Wizard step")

    payload = body()
    progress = _progress()
    step_data = dict(progress.step_data or {})
    step_data[step_key] = payload
    progress.step_data = step_data

    completed = list(progress.completed_steps or [])
    if step_key not in completed:
        completed.append(step_key)
    progress.completed_steps = completed
    progress.current_step = min(WIZARD_STEPS.index(step_key) + 2, len(WIZARD_STEPS))

    # Step 1 writes straight through to the school record.
    if step_key == "school_identity":
        school = _school()
        for field in ("name", "address", "phone", "email", "logo_url"):
            if payload.get(field):
                setattr(school, field, payload[field])

    if step_key == "curriculum_choice" and payload.get("curriculum_mode"):
        school = _school()
        school.curriculum_mode = payload["curriculum_mode"]

    db.session.commit()
    return ok(progress.to_dict())


@bp.post("/onboarding/apply-template")
@requires("onboarding.manage")
def apply_template():
    """Materialise a seed template into real rows -- all or nothing."""
    payload = body()
    validator = Validator(payload)
    template_key = validator.string("template_key", required=True)
    academic_year_name = validator.string("academic_year_name")
    attach_subjects = validator.boolean("attach_subjects_to_classes", default=True)
    validator.raise_if_invalid()

    with unscoped():  # platform tier: templates are shared across schools
        template = CurriculumTemplate.query.filter_by(
            template_key=template_key, is_active=True
        ).first()
    if template is None:
        raise not_found("Curriculum template")

    school = _school()
    if school.is_onboarded:
        raise invalid_state(
            "This school is already active. Edit configuration directly instead "
            "of reapplying a template."
        )

    summary = apply_curriculum_template(school, template.payload, academic_year_name)
    if attach_subjects:
        summary["class_subjects"] = attach_subjects_to_classes(school.id)

    progress = _progress()
    progress.template_key = template_key
    progress.template_applied_at = db.func.now()

    record(
        "create",
        "curriculum_template_application",
        template.id,
        new_values={"template_key": template_key, "summary": summary},
    )
    db.session.commit()
    return ok({"template": template.to_dict(), "applied": summary})


@bp.post("/onboarding/activate")
@requires("onboarding.manage")
def activate():
    """Step 10: confirm and go live."""
    from ..models import AssessmentComponent, GradeScale, SchoolClass, Subject, Term

    school = _school()
    if school.is_onboarded:
        return ok({"school": school.to_dict(), "already_active": True})

    blocking: list[str] = []
    if not Term.query.first():
        blocking.append("No academic terms have been created.")
    if not SchoolClass.query.first():
        blocking.append("No classes have been created.")
    if not Subject.query.first():
        blocking.append("No subjects have been created.")

    components = AssessmentComponent.query.filter_by(is_active=True).all()
    if not components:
        blocking.append("No assessment components have been configured.")

    scale = GradeScale.query.first()
    if scale is None or not scale.bands:
        blocking.append("No grading scale has been configured.")
    else:
        bands = sorted(scale.bands, key=lambda b: b.min_score)
        for earlier, later in zip(bands, bands[1:]):
            if earlier.max_score >= later.min_score:
                blocking.append(f"Grade bands overlap between {earlier.grade} and {later.grade}.")
                break

    if blocking:
        raise invalid_state("; ".join(blocking))

    mark_onboarding_complete(school)
    record("update", "school", school.id, new_values={"status": school.status})
    db.session.commit()
    return ok({"school": school.to_dict(), "activated": True})


@bp.get("/onboarding/preview")
@requires("onboarding.manage")
def worked_example():
    """Step 6's live worked example: the sentence that prevents support tickets.

    "Class Test 30% + Exam 70% -> a student scoring 24/30 and 56/70 gets 80,
    which is grade B, Very Good." Every number is read from configuration.
    """
    from decimal import Decimal

    from ..services.results_engine import (
        ScoreInput,
        grade_subject,
        load_bands,
        load_components,
        load_settings,
    )

    components = load_components()
    if not components:
        return ok({"available": False, "reason": "No assessment components configured yet."})

    settings = load_settings()
    bands = load_bands()

    # A worked example uses 80% of each component's own maximum.
    scores = {
        component.id: ScoreInput(
            component_id=component.id,
            raw_score=(component.max_score * Decimal("0.8")).quantize(Decimal("0.01")),
        )
        for component in components
    }
    outcome = grade_subject(scores, components, bands, settings)

    return ok(
        {
            "available": True,
            "components": [
                {
                    "name": c.name,
                    "code": c.code,
                    "weight": float(c.weight),
                    "max_score": float(c.max_score),
                    "example_raw_score": float(scores[c.id].raw_score),
                }
                for c in components
            ],
            "total_score": float(outcome.total_score) if outcome.has_total else None,
            "grade": outcome.grade,
            "remark": outcome.remark,
            "rounding": {
                "mode": settings.rounding_mode,
                "decimals": settings.rounding_decimals,
            },
            "total_weight": float(sum(c.weight for c in components)),
        }
    )
