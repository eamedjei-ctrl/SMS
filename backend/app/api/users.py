"""M2 (administration half) -- accounts, roles and the audit log."""

from __future__ import annotations

from flask import Blueprint, request

from ..extensions import db
from ..models import AuditLog, Guardian, Permission, Role, RolePermission, Staff, Student, User
from ..permissions import ALL_PERMISSIONS, SCHOOL_ROLE_KEYS
from ..security import current_user, hash_password, requires
from ..services.audit_service import diff, record
from ..services.auth_service import validate_password_policy
from ..tenancy import current_school_id, unscoped
from ..utils.errors import duplicate, invalid_state, not_found
from ..utils.responses import apply_pagination, body, created, ok, paginated, pagination_args
from ..utils.validation import Validator, arg_uuid

bp = Blueprint("users", __name__)


@bp.get("/users")
@requires("users.view")
def list_users():
    page, per_page = pagination_args()
    query = User.query

    search = (request.args.get("q") or "").strip().lower()
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                db.func.lower(User.full_name).like(pattern),
                db.func.lower(User.email).like(pattern),
            )
        )
    statuses = [s for s in (request.args.get("status") or "").split(",") if s]
    if statuses:
        query = query.filter(User.status.in_(statuses))

    role_key = request.args.get("role")
    if role_key:
        role = Role.query.filter_by(key=role_key).first()
        if role is None:
            return paginated([], page, per_page, 0)
        query = query.filter(User.roles.any(Role.id == role.id))

    items, total = apply_pagination(query.order_by(User.full_name), page, per_page)
    return paginated([u.to_dict() for u in items], page, per_page, total)


@bp.post("/users")
@requires("users.create")
def create_user():
    """Create an account and optionally bind it to a person record."""
    payload = body()
    validator = Validator(payload)
    full_name = validator.string("full_name", required=True, max_length=200)
    email = validator.email("email")
    phone = validator.string("phone", max_length=40)
    password = validator.string("password", required=True)
    role_keys = validator.sequence("roles", required=True)
    student_id = validator.uuid("student_id")
    guardian_id = validator.uuid("guardian_id")
    staff_id = validator.uuid("staff_id")
    must_change = validator.boolean("must_change_password", default=True)
    validator.raise_if_invalid()

    if not email and not phone:
        raise invalid_state("Provide an email address or a phone number.")
    validate_password_policy(password)

    if email and User.query.filter(db.func.lower(User.email) == email).first():
        raise duplicate("An account with that email already exists in this school.")
    if phone and User.query.filter_by(phone=phone).first():
        raise duplicate("An account with that phone number already exists in this school.")

    roles = Role.query.filter(Role.key.in_([str(r) for r in role_keys])).all()
    if len(roles) != len(set(str(r) for r in role_keys)):
        raise invalid_state("One or more roles do not exist in this school.")

    user = User(
        school_id=current_school_id(),
        full_name=full_name,
        email=email,
        phone=phone,
        password_hash=hash_password(password),
        status="active",
        must_change_password=must_change,
    )
    user.roles.extend(roles)
    db.session.add(user)
    db.session.flush()

    # Bind the login to the person it represents, so scope checks resolve.
    linked = None
    if student_id:
        student = Student.query.filter_by(id=student_id).first()
        if student is None:
            raise not_found("Student")
        student.user_id = user.id
        linked = {"student_id": str(student.id)}
    if guardian_id:
        guardian = Guardian.query.filter_by(id=guardian_id).first()
        if guardian is None:
            raise not_found("Guardian")
        guardian.user_id = user.id
        linked = {"guardian_id": str(guardian.id)}
    if staff_id:
        staff = Staff.query.filter_by(id=staff_id).first()
        if staff is None:
            raise not_found("Staff")
        staff.user_id = user.id
        linked = {"staff_id": str(staff.id)}

    record("create", "user", user.id, new_values={**user.to_dict(), "linked": linked})
    db.session.commit()
    return created(user.to_dict())


@bp.get("/users/<uuid:user_id>")
@requires("users.view")
def get_user(user_id):
    user = User.query.filter_by(id=user_id).first()
    if user is None:
        raise not_found("User")
    return ok(user.to_dict())


@bp.patch("/users/<uuid:user_id>")
@requires("users.create")
def update_user(user_id):
    user = User.query.filter_by(id=user_id).first()
    if user is None:
        raise not_found("User")
    before = user.to_dict()

    payload = body()
    validator = Validator(payload)
    if "full_name" in payload:
        validator.string("full_name", max_length=200)
    if "email" in payload:
        validator.email("email")
    if "phone" in payload:
        validator.string("phone", max_length=40)
    if "roles" in payload:
        validator.sequence("roles")
    data = validator.raise_if_invalid()

    for field in ("full_name", "email", "phone"):
        if field in payload:
            setattr(user, field, data.get(field))

    if "roles" in payload:
        roles = Role.query.filter(Role.key.in_([str(r) for r in data["roles"]])).all()
        if len(roles) != len(set(str(r) for r in data["roles"])):
            raise invalid_state("One or more roles do not exist in this school.")
        user.roles = roles

    db.session.flush()
    old_values, new_values = diff(before, user.to_dict())
    record("update", "user", user.id, old_values=old_values, new_values=new_values)
    db.session.commit()
    return ok(user.to_dict())


@bp.post("/users/<uuid:user_id>/suspend")
@requires("users.suspend")
def suspend_user(user_id):
    user = User.query.filter_by(id=user_id).first()
    if user is None:
        raise not_found("User")
    if user.id == current_user().id:
        raise invalid_state("You cannot suspend your own account.")

    payload = body()
    reason = (payload.get("reason") or "").strip() or None

    user.status = "suspended"
    from ..services.auth_service import revoke_all_sessions

    revoke_all_sessions(user)
    record(
        "update",
        "user",
        user.id,
        old_values={"status": "active"},
        new_values={"status": "suspended"},
        reason=reason,
    )
    db.session.commit()
    return ok(user.to_dict())


@bp.post("/users/<uuid:user_id>/reactivate")
@requires("users.suspend")
def reactivate_user(user_id):
    user = User.query.filter_by(id=user_id).first()
    if user is None:
        raise not_found("User")
    user.status = "active"
    user.failed_login_count = 0
    user.locked_until = None
    record("update", "user", user.id, new_values={"status": "active"})
    db.session.commit()
    return ok(user.to_dict())


@bp.post("/users/<uuid:user_id>/reset-password")
@requires("users.create")
def admin_reset_password(user_id):
    """Issue a temporary password; the user must change it at next sign-in."""
    user = User.query.filter_by(id=user_id).first()
    if user is None:
        raise not_found("User")

    payload = body()
    validator = Validator(payload)
    new_password = validator.string("new_password", required=True)
    validator.raise_if_invalid()
    validate_password_policy(new_password, field="new_password")

    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    from ..services.auth_service import revoke_all_sessions

    revoke_all_sessions(user)
    record("update", "user", user.id, new_values={"password": "reset_by_admin"})
    db.session.commit()
    return ok({"message": "Temporary password set. The user must change it at next sign-in."})


# ==========================================================================
# Roles
# ==========================================================================
@bp.get("/roles")
@requires("roles.manage")
def list_roles():
    roles = Role.query.order_by(Role.is_system.desc(), Role.name).all()
    return ok(
        {
            "roles": [role.to_dict() for role in roles],
            "available_permissions": list(ALL_PERMISSIONS),
            "system_role_keys": list(SCHOOL_ROLE_KEYS),
        }
    )


@bp.post("/roles")
@requires("roles.manage")
def create_role():
    """Schools may define custom roles on top of the system ones."""
    payload = body()
    validator = Validator(payload)
    key = validator.string("key", required=True, max_length=60, lower=True)
    name = validator.string("name", required=True, max_length=120)
    description = validator.string("description", max_length=300)
    permission_codes = validator.sequence("permissions", default=[])
    validator.raise_if_invalid()

    if key in SCHOOL_ROLE_KEYS:
        raise duplicate("That key is reserved for a system role.")
    if Role.query.filter_by(key=key).first():
        raise duplicate("A role with that key already exists.")

    unknown = [c for c in permission_codes if c not in ALL_PERMISSIONS]
    if unknown:
        raise invalid_state(f"Unknown permissions: {', '.join(unknown)}")

    role = Role(school_id=current_school_id(), key=key, name=name, description=description)
    db.session.add(role)
    db.session.flush()

    with unscoped():  # platform tier: the permission catalogue is shared
        catalog = {p.code: p for p in Permission.query.all()}
    for code in permission_codes:
        db.session.add(RolePermission(role_id=role.id, permission_id=catalog[code].id))

    db.session.flush()
    db.session.refresh(role)
    record("create", "role", role.id, new_values=role.to_dict())
    db.session.commit()
    return created(role.to_dict())


@bp.put("/roles/<uuid:role_id>/permissions")
@requires("roles.manage")
def set_role_permissions(role_id):
    role = Role.query.filter_by(id=role_id).first()
    if role is None:
        raise not_found("Role")
    if role.is_system:
        raise invalid_state(
            "System role permissions are governed by the platform permission matrix."
        )

    payload = body()
    validator = Validator(payload)
    permission_codes = validator.sequence("permissions", required=True)
    validator.raise_if_invalid()

    unknown = [c for c in permission_codes if c not in ALL_PERMISSIONS]
    if unknown:
        raise invalid_state(f"Unknown permissions: {', '.join(unknown)}")

    before = sorted(p.code for p in role.permissions)
    RolePermission.query.filter_by(role_id=role.id).delete()

    with unscoped():  # platform tier: the permission catalogue is shared
        catalog = {p.code: p for p in Permission.query.all()}
    for code in permission_codes:
        db.session.add(RolePermission(role_id=role.id, permission_id=catalog[code].id))

    db.session.flush()
    db.session.refresh(role)
    record(
        "update",
        "role",
        role.id,
        old_values={"permissions": before},
        new_values={"permissions": sorted(permission_codes)},
    )
    db.session.commit()
    return ok(role.to_dict())


# ==========================================================================
# Audit log
# ==========================================================================
@bp.get("/audit-logs")
@requires("audit.view")
def list_audit_logs():
    page, per_page = pagination_args()
    query = AuditLog.query

    if request.args.get("action"):
        query = query.filter(AuditLog.action.in_(request.args["action"].split(",")))
    if request.args.get("entity_type"):
        query = query.filter(AuditLog.entity_type == request.args["entity_type"])
    if request.args.get("entity_id"):
        query = query.filter(AuditLog.entity_id == request.args["entity_id"])
    user_id = arg_uuid("user_id")
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)

    items, total = apply_pagination(query.order_by(AuditLog.created_at.desc()), page, per_page)
    return paginated([entry.to_dict() for entry in items], page, per_page, total)
