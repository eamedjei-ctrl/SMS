"""M1 -- turning a signed-up school into a configured, ready-to-use platform.

The template loader materialises seed JSON into real rows. It either fully
succeeds or fully rolls back: a half-applied curriculum is worse than none.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from ..extensions import db
from ..models import (
    AcademicYear,
    AssessmentComponent,
    AssessmentSettings,
    AttendanceSettings,
    AttendanceStatus,
    ClassSubject,
    GradeBand,
    GradeScale,
    Permission,
    ReportCardTemplate,
    Role,
    RolePermission,
    SchoolClass,
    Subject,
    Term,
)
from ..permissions import (
    ALL_PERMISSIONS,
    ROLE_LABELS,
    SCHOOL_ROLE_KEYS,
    module_of,
    permissions_for_role,
)
from ..tenancy import unscoped

DEFAULT_ATTENDANCE_STATUSES = [
    {"code": "present", "label": "Present", "counts_as_present": True, "is_default": True},
    {
        "code": "absent",
        "label": "Absent",
        "counts_as_present": False,
        "triggers_notification": True,
    },
    {"code": "late", "label": "Late", "counts_as_present": True},
    {"code": "excused", "label": "Excused", "counts_as_present": False},
]


def ensure_permission_catalog() -> dict[str, Permission]:
    """The permission vocabulary is platform-wide and shared by every school."""
    with unscoped():  # platform tier: permissions are not tenant-owned
        existing = {p.code: p for p in Permission.query.all()}
        for code in ALL_PERMISSIONS:
            if code not in existing:
                permission = Permission(code=code, module=module_of(code))
                db.session.add(permission)
                existing[code] = permission
        db.session.flush()
    return existing


def provision_school_roles(school_id) -> dict[str, Role]:
    """Create the system roles for a school and wire them to the matrix."""
    catalog = ensure_permission_catalog()
    roles: dict[str, Role] = {r.key: r for r in Role.query.filter_by(school_id=school_id).all()}

    for role_key in SCHOOL_ROLE_KEYS:
        role = roles.get(role_key)
        if role is None:
            role = Role(
                school_id=school_id,
                key=role_key,
                name=ROLE_LABELS[role_key],
                is_system=True,
            )
            db.session.add(role)
            db.session.flush()
            roles[role_key] = role

        current = {p.code for p in role.permissions}
        for code in permissions_for_role(role_key):
            if code not in current:
                db.session.add(RolePermission(role_id=role.id, permission_id=catalog[code].id))
    db.session.flush()
    return roles


def provision_school_defaults(school) -> None:
    """Rows every school needs before the wizard runs: roles, settings, statuses."""
    provision_school_roles(school.id)

    if AssessmentSettings.query.filter_by(school_id=school.id).first() is None:
        db.session.add(AssessmentSettings(school_id=school.id))

    if AttendanceSettings.query.filter_by(school_id=school.id).first() is None:
        db.session.add(AttendanceSettings(school_id=school.id))

    if not AttendanceStatus.query.filter_by(school_id=school.id).first():
        for index, status in enumerate(DEFAULT_ATTENDANCE_STATUSES):
            db.session.add(
                AttendanceStatus(
                    school_id=school.id,
                    sequence=index,
                    triggers_notification=status.get("triggers_notification", False),
                    is_default=status.get("is_default", False),
                    code=status["code"],
                    label=status["label"],
                    counts_as_present=status["counts_as_present"],
                )
            )
    db.session.flush()


def apply_curriculum_template(school, payload: dict, academic_year_name: str | None = None) -> dict:
    """Materialise a seed template into the school's own rows.

    Nothing here is curriculum-specific: it reads names, weights, bands and
    rules out of the template and writes them as configuration.
    """
    summary = {"levels": 0, "subjects": 0, "components": 0, "bands": 0, "terms": 0}

    structure = payload.get("academic_structure", {}) or {}
    term_names = structure.get("term_names") or [
        f"Term {i + 1}" for i in range(int(structure.get("terms_per_year", 3)))
    ]

    # ---- academic year and terms -------------------------------------------
    today = date.today()
    year_name = academic_year_name or _format_year_name(
        structure.get("year_name_format", "{start}/{end}"), today
    )
    academic_year = AcademicYear.query.filter_by(school_id=school.id, name=year_name).first()
    if academic_year is None:
        academic_year = AcademicYear(school_id=school.id, name=year_name, is_current=True)
        db.session.add(academic_year)
        db.session.flush()

    for index, term_name in enumerate(term_names):
        exists = Term.query.filter_by(
            school_id=school.id, academic_year_id=academic_year.id, sequence=index + 1
        ).first()
        if exists is None:
            db.session.add(
                Term(
                    school_id=school.id,
                    academic_year_id=academic_year.id,
                    name=term_name,
                    sequence=index + 1,
                    is_current=(index == 0),
                )
            )
            summary["terms"] += 1

    # ---- classes from the level ladder --------------------------------------
    for level in payload.get("levels", []) or []:
        exists = SchoolClass.query.filter_by(
            school_id=school.id,
            academic_year_id=academic_year.id,
            name=level["name"],
            section=level.get("section"),
        ).first()
        if exists is None:
            db.session.add(
                SchoolClass(
                    school_id=school.id,
                    academic_year_id=academic_year.id,
                    name=level["name"],
                    level=int(level.get("level", 1)),
                    section=level.get("section"),
                    curriculum=payload.get("curriculum"),
                )
            )
            summary["levels"] += 1

    # ---- subjects -----------------------------------------------------------
    for index, subject in enumerate(payload.get("subjects", []) or []):
        exists = Subject.query.filter_by(school_id=school.id, code=subject["code"]).first()
        if exists is None:
            db.session.add(
                Subject(
                    school_id=school.id,
                    name=subject["name"],
                    code=subject["code"],
                    is_core=bool(subject.get("is_core", True)),
                    sequence=index,
                )
            )
            summary["subjects"] += 1

    # ---- assessment components ---------------------------------------------
    for index, component in enumerate(payload.get("assessment_components", []) or []):
        exists = AssessmentComponent.query.filter_by(
            school_id=school.id, code=component["code"]
        ).first()
        if exists is None:
            db.session.add(
                AssessmentComponent(
                    school_id=school.id,
                    name=component["name"],
                    code=component["code"],
                    weight=Decimal(str(component["weight"])),
                    max_score=Decimal(str(component["max_score"])),
                    sequence=int(component.get("sequence", index + 1)),
                    scope=component.get("scope", "term"),
                    applies_to=component.get("applies_to", {}) or {},
                )
            )
            summary["components"] += 1

    # ---- grade scale and bands ----------------------------------------------
    scale_payload = payload.get("grade_scale") or {}
    if scale_payload:
        scale = GradeScale.query.filter_by(school_id=school.id, name=scale_payload["name"]).first()
        if scale is None:
            scale = GradeScale(
                school_id=school.id,
                name=scale_payload["name"],
                applies_to=scale_payload.get("applies_to", {}) or {},
                is_default=not GradeScale.query.filter_by(
                    school_id=school.id, is_default=True
                ).first(),
            )
            db.session.add(scale)
            db.session.flush()

            for index, band in enumerate(scale_payload.get("bands", []) or []):
                db.session.add(
                    GradeBand(
                        school_id=school.id,
                        grade_scale_id=scale.id,
                        min_score=Decimal(str(band["min"])),
                        max_score=Decimal(str(band["max"])),
                        grade=str(band["grade"]),
                        remark=band.get("remark"),
                        points=(
                            Decimal(str(band["points"])) if band.get("points") is not None else None
                        ),
                        sequence=index,
                    )
                )
                summary["bands"] += 1

    # ---- computation rules ---------------------------------------------------
    rules = payload.get("computation_rules") or {}
    if rules:
        settings = AssessmentSettings.query.filter_by(school_id=school.id).first()
        if settings is None:
            settings = AssessmentSettings(school_id=school.id)
            db.session.add(settings)
        rounding = rules.get("rounding") or {}
        settings.rounding_mode = rounding.get("mode", settings.rounding_mode)
        settings.rounding_decimals = int(rounding.get("decimals", settings.rounding_decimals))
        settings.missing_score_rule = rules.get("missing_score", settings.missing_score_rule)
        settings.absent_rule = rules.get("absent_handling", settings.absent_rule)
        settings.position_basis = rules.get("position_basis", settings.position_basis)
        settings.position_scope = rules.get("position_scope", settings.position_scope)
        settings.tie_rule = rules.get("tie_rule", settings.tie_rule)
        settings.aggregate_method = rules.get("aggregate_method", settings.aggregate_method)
        settings.weight_interpretation = rules.get(
            "weight_interpretation", settings.weight_interpretation
        )
        if rules.get("best_n") is not None:
            settings.best_n = int(rules["best_n"])
        if rules.get("pass_mark") is not None:
            settings.pass_mark = Decimal(str(rules["pass_mark"]))

    # ---- report card template ------------------------------------------------
    card = payload.get("report_card") or {}
    if card:
        name = card.get("name") or f"{payload.get('name', 'School')} report card"
        template = ReportCardTemplate.query.filter_by(school_id=school.id, name=name).first()
        if template is None:
            db.session.add(
                ReportCardTemplate(
                    school_id=school.id,
                    name=name,
                    template_key=card.get("template", "standard"),
                    is_default=True,
                    show_position=bool(card.get("show_position", True)),
                    show_class_average=bool(card.get("show_class_average", True)),
                    show_attendance=bool(card.get("show_attendance", True)),
                    show_teacher_remark=bool(card.get("show_teacher_remark", True)),
                    show_head_remark=bool(card.get("show_head_remark", True)),
                    show_grade_key=bool(card.get("show_grade_key", True)),
                    signature_blocks=card.get("signature_blocks", []) or [],
                )
            )

    db.session.flush()
    return summary


def attach_subjects_to_classes(school_id, academic_year_id=None) -> int:
    """Convenience for the wizard: attach every core subject to every class."""
    classes = SchoolClass.query.filter_by(school_id=school_id)
    if academic_year_id:
        classes = classes.filter_by(academic_year_id=academic_year_id)
    subjects = Subject.query.filter_by(school_id=school_id, is_active=True).all()

    attached = 0
    for school_class in classes.all():
        existing = {
            cs.subject_id
            for cs in ClassSubject.query.filter_by(
                school_id=school_id, class_id=school_class.id
            ).all()
        }
        for subject in subjects:
            if subject.id in existing:
                continue
            db.session.add(
                ClassSubject(
                    school_id=school_id,
                    class_id=school_class.id,
                    subject_id=subject.id,
                    is_elective=not subject.is_core,
                )
            )
            attached += 1
    db.session.flush()
    return attached


def _format_year_name(fmt: str, today: date) -> str:
    start = today.year if today.month >= 8 else today.year - 1
    return fmt.replace("{start}", str(start)).replace("{end}", str(start + 1))


def mark_onboarding_complete(school) -> None:
    school.onboarding_completed_at = datetime.now(timezone.utc)
    if school.status == "trial":
        school.status = "active"
