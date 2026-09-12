"""M7 (configuration half) -- components, grade scales, bands and rules."""

from __future__ import annotations

from flask import Blueprint

from ..extensions import db
from ..models import AssessmentComponent, AssessmentSettings, GradeBand, GradeScale
from ..security import requires
from ..services.audit_service import diff, record
from ..tenancy import current_school_id
from ..utils.errors import duplicate, invalid_state, not_found
from ..utils.responses import body, created, ok
from ..utils.validation import Validator

bp = Blueprint("assessment", __name__)


def _settings() -> AssessmentSettings:
    settings = AssessmentSettings.query.first()
    if settings is None:
        settings = AssessmentSettings(school_id=current_school_id())
        db.session.add(settings)
        db.session.flush()
    return settings


# ==========================================================================
# Components
# ==========================================================================
@bp.get("/assessment/components")
@requires("classes.view")
def list_components():
    components = AssessmentComponent.query.order_by(AssessmentComponent.sequence).all()
    total_weight = sum(float(c.weight) for c in components if c.is_active)
    return ok(
        {
            "components": [c.to_dict() for c in components],
            "total_weight": total_weight,
        }
    )


@bp.post("/assessment/components")
@requires("assessment.configure")
def create_component():
    payload = body()
    validator = Validator(payload)
    name = validator.string("name", required=True, max_length=100)
    code = validator.string("code", required=True, max_length=20)
    weight = validator.decimal("weight", required=True, minimum=0)
    max_score = validator.decimal("max_score", required=True, minimum=0.01)
    sequence = validator.integer("sequence", default=0)
    scope = validator.string("scope", default="term", choices=("term", "year"))
    applies_to = validator.mapping("applies_to", default={})
    validator.raise_if_invalid()

    if AssessmentComponent.query.filter_by(code=code).first():
        raise duplicate("A component with that code already exists.")

    component = AssessmentComponent(
        school_id=current_school_id(),
        name=name,
        code=code,
        weight=weight,
        max_score=max_score,
        sequence=sequence,
        scope=scope,
        applies_to=applies_to,
    )
    db.session.add(component)
    db.session.flush()
    record("create", "assessment_component", component.id, new_values=component.to_dict())
    db.session.commit()
    return created(component.to_dict())


@bp.patch("/assessment/components/<uuid:component_id>")
@requires("assessment.configure")
def update_component(component_id):
    component = AssessmentComponent.query.filter_by(id=component_id).first()
    if component is None:
        raise not_found("Assessment component")
    _assert_no_locked_terms()
    before = component.to_dict()

    payload = body()
    validator = Validator(payload)
    if "name" in payload:
        validator.string("name", max_length=100)
    if "code" in payload:
        validator.string("code", max_length=20)
    if "weight" in payload:
        validator.decimal("weight", minimum=0)
    if "max_score" in payload:
        validator.decimal("max_score", minimum=0.01)
    if "sequence" in payload:
        validator.integer("sequence")
    if "is_active" in payload:
        validator.boolean("is_active")
    if "applies_to" in payload:
        validator.mapping("applies_to")
    data = validator.raise_if_invalid()

    for field, value in data.items():
        if field in payload:
            setattr(component, field, value)
    db.session.flush()

    old_values, new_values = diff(before, component.to_dict())
    record(
        "update",
        "assessment_component",
        component.id,
        old_values=old_values,
        new_values=new_values,
    )
    db.session.commit()
    return ok(
        {
            "component": component.to_dict(),
            "note": "Existing results keep their stored values until you recompute.",
        }
    )


@bp.delete("/assessment/components/<uuid:component_id>")
@requires("assessment.configure")
def deactivate_component(component_id):
    """Components are deactivated, never deleted: old results reference them."""
    component = AssessmentComponent.query.filter_by(id=component_id).first()
    if component is None:
        raise not_found("Assessment component")
    _assert_no_locked_terms()
    component.is_active = False
    record("update", "assessment_component", component.id, new_values={"is_active": False})
    db.session.commit()
    return ok(component.to_dict())


# ==========================================================================
# Grade scales and bands
# ==========================================================================
@bp.get("/assessment/grade-scales")
@requires("classes.view")
def list_scales():
    scales = GradeScale.query.order_by(GradeScale.name).all()
    return ok([scale.to_dict() for scale in scales])


@bp.post("/assessment/grade-scales")
@requires("assessment.configure")
def create_scale():
    payload = body()
    validator = Validator(payload)
    name = validator.string("name", required=True, max_length=120)
    applies_to = validator.mapping("applies_to", default={})
    is_default = validator.boolean("is_default", default=False)
    bands = validator.sequence("bands", default=[])
    validator.raise_if_invalid()

    if GradeScale.query.filter_by(name=name).first():
        raise duplicate("A grade scale with that name already exists.")

    parsed_bands = _parse_bands(bands)
    _assert_bands_coherent(parsed_bands)

    if is_default:
        for scale in GradeScale.query.filter_by(is_default=True).all():
            scale.is_default = False

    scale = GradeScale(
        school_id=current_school_id(),
        name=name,
        applies_to=applies_to,
        is_default=is_default or GradeScale.query.first() is None,
    )
    db.session.add(scale)
    db.session.flush()

    for index, band in enumerate(parsed_bands):
        db.session.add(
            GradeBand(
                school_id=current_school_id(),
                grade_scale_id=scale.id,
                min_score=band["min_score"],
                max_score=band["max_score"],
                grade=band["grade"],
                remark=band.get("remark"),
                points=band.get("points"),
                sequence=index,
            )
        )

    db.session.flush()
    record("create", "grade_scale", scale.id, new_values={"name": name, "bands": len(parsed_bands)})
    db.session.commit()
    return created(scale.to_dict())


@bp.put("/assessment/grade-scales/<uuid:scale_id>/bands")
@requires("assessment.configure")
def replace_bands(scale_id):
    """Replace the whole band set -- the editor saves the table as one unit."""
    scale = GradeScale.query.filter_by(id=scale_id).first()
    if scale is None:
        raise not_found("Grade scale")
    _assert_no_locked_terms()

    payload = body()
    validator = Validator(payload)
    bands = validator.sequence("bands", required=True)
    validator.raise_if_invalid()

    parsed_bands = _parse_bands(bands)
    _assert_bands_coherent(parsed_bands)

    before = [band.to_dict() for band in scale.bands]
    for band in list(scale.bands):
        db.session.delete(band)
    db.session.flush()

    for index, band in enumerate(parsed_bands):
        db.session.add(
            GradeBand(
                school_id=current_school_id(),
                grade_scale_id=scale.id,
                min_score=band["min_score"],
                max_score=band["max_score"],
                grade=band["grade"],
                remark=band.get("remark"),
                points=band.get("points"),
                sequence=index,
            )
        )

    db.session.flush()
    db.session.refresh(scale)
    record(
        "update",
        "grade_scale",
        scale.id,
        old_values={"bands": before},
        new_values={"bands": [b.to_dict() for b in scale.bands]},
    )
    db.session.commit()
    return ok(scale.to_dict())


def _parse_bands(raw_bands: list) -> list[dict]:
    parsed = []
    for index, raw in enumerate(raw_bands):
        validator = Validator(raw if isinstance(raw, dict) else {})
        min_score = validator.decimal("min_score", required=True)
        max_score = validator.decimal("max_score", required=True)
        grade = validator.string("grade", required=True, max_length=20)
        remark = validator.string("remark", max_length=120)
        points = validator.decimal("points")
        if min_score is not None and max_score is not None and min_score > max_score:
            validator.add_error("min_score", "Must not be greater than max_score.")
        try:
            validator.raise_if_invalid()
        except Exception as exc:  # re-key the error onto the row for the editor
            from ..utils.errors import validation_error

            raise validation_error({f"bands[{index}]": [str(exc)]}) from exc
        parsed.append(
            {
                "min_score": min_score,
                "max_score": max_score,
                "grade": grade,
                "remark": remark,
                "points": points,
            }
        )
    return parsed


def _assert_bands_coherent(bands: list[dict]) -> None:
    """Bands must not overlap or the same score would resolve to two grades."""
    if not bands:
        raise invalid_state("A grade scale needs at least one band.")
    ordered = sorted(bands, key=lambda b: b["min_score"])
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier["max_score"] >= later["min_score"]:
            raise invalid_state(f"Bands '{earlier['grade']}' and '{later['grade']}' overlap.")


# ==========================================================================
# Computation rules
# ==========================================================================
@bp.get("/assessment/settings")
@requires("classes.view")
def get_settings():
    settings = _settings()
    db.session.commit()
    return ok(settings.to_dict())


@bp.patch("/assessment/settings")
@requires("assessment.configure")
def update_settings():
    settings = _settings()
    before = settings.to_dict()

    payload = body()
    validator = Validator(payload)
    from ..models.assessment import (
        ABSENT_RULES,
        AGGREGATE_METHODS,
        MISSING_SCORE_RULES,
        POSITION_BASES,
        POSITION_SCOPES,
        ROUNDING_MODES,
        TIE_RULES,
        WEIGHT_INTERPRETATIONS,
    )

    field_choices = {
        "weight_interpretation": WEIGHT_INTERPRETATIONS,
        "rounding_mode": ROUNDING_MODES,
        "missing_score_rule": MISSING_SCORE_RULES,
        "absent_rule": ABSENT_RULES,
        "position_basis": POSITION_BASES,
        "position_scope": POSITION_SCOPES,
        "tie_rule": TIE_RULES,
        "aggregate_method": AGGREGATE_METHODS,
    }
    for field, choices in field_choices.items():
        if field in payload:
            validator.string(field, choices=choices)
    if "rounding_decimals" in payload:
        validator.integer("rounding_decimals", minimum=0, maximum=4)
    if "best_n" in payload:
        validator.integer("best_n", minimum=1)
    if "pass_mark" in payload:
        validator.decimal("pass_mark", minimum=0)
    if "require_approval_before_publish" in payload:
        validator.boolean("require_approval_before_publish")
    if "best_n_compulsory_subject_ids" in payload:
        validator.sequence("best_n_compulsory_subject_ids")
    data = validator.raise_if_invalid()

    for field, value in data.items():
        if field in payload:
            if field == "best_n_compulsory_subject_ids":
                value = [str(v) for v in (value or [])]
            setattr(settings, field, value)
    db.session.flush()

    old_values, new_values = diff(before, settings.to_dict())
    record(
        "update",
        "assessment_settings",
        settings.id,
        old_values=old_values,
        new_values=new_values,
    )
    db.session.commit()
    return ok(
        {
            "settings": settings.to_dict(),
            "note": "Recompute affected terms for the change to reach stored results.",
        }
    )


def _assert_no_locked_terms() -> None:
    from ..models import Term

    if Term.query.filter_by(is_current=True, results_locked=True).first():
        from ..utils.errors import term_locked

        raise term_locked(
            "The current term's results are locked. Unlock it before changing "
            "assessment configuration."
        )
