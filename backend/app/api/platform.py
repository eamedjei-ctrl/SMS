"""M1 -- the platform tier: our own staff onboarding and operating schools."""

from __future__ import annotations

from flask import Blueprint

from ..extensions import db
from ..models import CurriculumTemplate, PlatformUser, School, User
from ..permissions import PLATFORM_ADMIN
from ..security import (
    current_user,
    hash_password,
    issue_platform_token,
    requires_platform,
    verify_password,
)
from ..services.audit_service import record
from ..services.provisioning import provision_school_defaults
from ..tenancy import set_current_school, tenant_context, unscoped
from ..utils.errors import ApiError, ErrorCode, duplicate, not_found
from ..utils.responses import body, created, ok, pagination_args
from ..utils.validation import Validator

auth_bp = Blueprint("platform_auth", __name__)
bp = Blueprint("platform", __name__)


@auth_bp.post("/platform/auth/login")
def login():
    payload = body()
    validator = Validator(payload)
    email = validator.email("email", required=True)
    password = validator.string("password", required=True)
    validator.raise_if_invalid()

    with unscoped():  # platform tier: our own staff are not tenant-owned
        user = PlatformUser.query.filter_by(email=email).first()

    if user is None or not verify_password(user.password_hash, password):
        raise ApiError(
            ErrorCode.AUTHENTICATION_REQUIRED, "Those credentials did not match our records."
        )
    if user.status != "active":
        raise ApiError(ErrorCode.PERMISSION_DENIED, "This account is not active.")

    user.last_login_at = db.func.now()
    db.session.commit()

    return ok(
        {
            "access_token": issue_platform_token(user),
            "token_type": "Bearer",
            "user": user.to_dict(),
            "platform": True,
        }
    )


@bp.get("/platform/subdomains/<subdomain>")
def check_subdomain(subdomain: str):
    """Live availability check for step 1 of the wizard."""
    validator = Validator({"subdomain": subdomain})
    value = validator.subdomain("subdomain")
    if validator.errors:
        return ok(
            {
                "subdomain": subdomain,
                "available": False,
                "reason": validator.errors["subdomain"][0],
                "suggestions": [],
            }
        )

    with unscoped():  # platform tier: the school registry
        taken = School.query.filter_by(subdomain=value).first() is not None
        suggestions = []
        if taken:
            for suffix in ("-school", "-academy", "-gh", "1", "2"):
                candidate = f"{value}{suffix}"
                if School.query.filter_by(subdomain=candidate).first() is None:
                    suggestions.append(candidate)
                if len(suggestions) >= 3:
                    break

    return ok(
        {
            "subdomain": value,
            "available": not taken,
            "reason": "That subdomain is already taken." if taken else None,
            "suggestions": suggestions,
        }
    )


@bp.get("/platform/schools")
@requires_platform()
def list_schools():
    page, per_page = pagination_args()
    with unscoped():  # platform tier: listing every tenant is the point
        query = School.query.order_by(School.created_at.desc())
        total = query.count()
        schools = query.limit(per_page).offset((page - 1) * per_page).all()
    from ..utils.responses import paginated

    return paginated([s.to_dict() for s in schools], page, per_page, total)


@bp.post("/platform/schools")
@requires_platform(PLATFORM_ADMIN)
def create_school():
    """Create a tenant and its head-teacher account, ready for the wizard."""
    payload = body()
    validator = Validator(payload)
    name = validator.string("name", required=True, max_length=200)
    subdomain = validator.subdomain("subdomain", required=True)
    curriculum_mode = validator.string(
        "curriculum_mode", default="ges", choices=("ges", "cambridge", "hybrid")
    )
    admin_name = validator.string("admin_full_name", required=True, max_length=200)
    admin_email = validator.email("admin_email", required=True)
    admin_password = validator.string("admin_password", required=True)
    country = validator.string("country", default="GH")
    timezone_name = validator.string("timezone", default="Africa/Accra")
    currency = validator.string("currency", default="GHS")
    validator.raise_if_invalid()

    from ..services.auth_service import validate_password_policy

    validate_password_policy(admin_password, field="admin_password")

    with unscoped():  # platform tier: the school registry
        if School.query.filter_by(subdomain=subdomain).first():
            raise duplicate("That subdomain is already taken.")

        school = School(
            name=name,
            subdomain=subdomain,
            curriculum_mode=curriculum_mode,
            country=country,
            timezone=timezone_name,
            currency=currency,
            status="trial",
        )
        db.session.add(school)
        db.session.flush()

    with tenant_context(school.id):
        set_current_school(school.id)
        provision_school_defaults(school)

        from ..models import Role

        admin_role = Role.query.filter_by(school_id=school.id, key="school_admin").first()
        admin_user = User(
            school_id=school.id,
            email=admin_email,
            full_name=admin_name,
            password_hash=hash_password(admin_password),
            status="active",
            must_change_password=True,
        )
        admin_user.roles.append(admin_role)
        db.session.add(admin_user)
        db.session.flush()

        record(
            "create",
            "school",
            school.id,
            new_values={"name": name, "subdomain": subdomain},
            school_id=school.id,
        )

    db.session.commit()
    return created({"school": school.to_dict(), "admin_user": admin_user.to_dict()})


@bp.get("/platform/schools/<uuid:school_id>")
@requires_platform()
def get_school(school_id):
    with unscoped():  # platform tier
        school = School.query.filter_by(id=school_id).first()
    if school is None:
        raise not_found("School")
    return ok(school.to_dict())


@bp.patch("/platform/schools/<uuid:school_id>/status")
@requires_platform(PLATFORM_ADMIN)
def update_school_status(school_id):
    payload = body()
    validator = Validator(payload)
    status = validator.string(
        "status", required=True, choices=("trial", "active", "suspended", "archived")
    )
    reason = validator.string("reason")
    validator.raise_if_invalid()

    with unscoped():  # platform tier
        school = School.query.filter_by(id=school_id).first()
        if school is None:
            raise not_found("School")
        previous = school.status
        school.status = status

    record(
        "update",
        "school",
        school.id,
        old_values={"status": previous},
        new_values={"status": status},
        reason=reason,
        school_id=school.id,
    )
    db.session.commit()
    return ok(school.to_dict())


@bp.get("/platform/templates")
def list_templates():
    """Curriculum templates are shared, so the wizard can read them pre-auth."""
    with unscoped():  # platform tier: shared seed templates
        templates = CurriculumTemplate.query.filter_by(is_active=True).all()
    return ok([t.to_dict() for t in templates])


@bp.post("/platform/users")
@requires_platform(PLATFORM_ADMIN)
def create_platform_user():
    payload = body()
    validator = Validator(payload)
    email = validator.email("email", required=True)
    full_name = validator.string("full_name", required=True)
    password = validator.string("password", required=True)
    role = validator.string(
        "role", default="platform_support", choices=("platform_admin", "platform_support")
    )
    validator.raise_if_invalid()

    from ..services.auth_service import validate_password_policy

    validate_password_policy(password)

    with unscoped():  # platform tier
        if PlatformUser.query.filter_by(email=email).first():
            raise duplicate("A platform account with that email already exists.")
        user = PlatformUser(
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            role=role,
        )
        db.session.add(user)
    db.session.commit()
    return created(user.to_dict())


@bp.get("/platform/me")
@requires_platform()
def platform_me():
    return ok({"user": current_user().to_dict(), "platform": True})
