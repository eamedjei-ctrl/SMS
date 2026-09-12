"""Appendix B -- the permission matrix.

``FULL`` = full access. ``SCOPED`` = the role holds the permission but only over
resources assigned to them (own classes, own children, own record). ``READ`` =
read only. Absent = no access.

A role answers "may this person approve results?". It does not answer "for which
class?" -- that is the scope check in ``app.security``, and it is the single most
commonly forgotten control in school systems.
"""

from __future__ import annotations

FULL = "full"
SCOPED = "scoped"
READ = "read"

PLATFORM_ADMIN = "platform_admin"
PLATFORM_SUPPORT = "platform_support"
SCHOOL_ADMIN = "school_admin"
HEAD_TEACHER = "head_teacher"
TEACHER = "teacher"
STUDENT = "student"
GUARDIAN = "guardian"

SCHOOL_ROLE_KEYS = (SCHOOL_ADMIN, HEAD_TEACHER, TEACHER, STUDENT, GUARDIAN)

ROLE_LABELS = {
    PLATFORM_ADMIN: "Platform Admin",
    PLATFORM_SUPPORT: "Platform Support",
    SCHOOL_ADMIN: "School Admin",
    HEAD_TEACHER: "Head Teacher",
    TEACHER: "Teacher",
    STUDENT: "Student",
    GUARDIAN: "Guardian",
}

# permission -> {role: level}
MATRIX: dict[str, dict[str, str]] = {
    "schools.manage": {PLATFORM_ADMIN: FULL},
    "settings.view": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: READ},
    "settings.update": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "onboarding.manage": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "users.view": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "users.create": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "users.suspend": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "roles.manage": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "students.view": {
        PLATFORM_ADMIN: FULL,
        SCHOOL_ADMIN: FULL,
        HEAD_TEACHER: FULL,
        TEACHER: SCOPED,
        STUDENT: SCOPED,
        GUARDIAN: SCOPED,
    },
    "students.create": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "students.update": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: READ},
    "students.delete": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "students.import": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "students.medical.view": {SCHOOL_ADMIN: FULL, HEAD_TEACHER: FULL, GUARDIAN: SCOPED},
    "guardians.manage": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "staff.manage": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: READ},
    "classes.manage": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: READ},
    "classes.view": {
        PLATFORM_ADMIN: FULL,
        SCHOOL_ADMIN: FULL,
        HEAD_TEACHER: FULL,
        TEACHER: SCOPED,
        STUDENT: SCOPED,
        GUARDIAN: SCOPED,
    },
    "subjects.manage": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: READ},
    "enrollment.manage": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: READ},
    "enrollment.view": {
        PLATFORM_ADMIN: FULL,
        SCHOOL_ADMIN: FULL,
        HEAD_TEACHER: FULL,
        TEACHER: SCOPED,
        STUDENT: SCOPED,
        GUARDIAN: SCOPED,
    },
    "promotion.execute": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: FULL},
    "attendance.mark": {SCHOOL_ADMIN: FULL, HEAD_TEACHER: FULL, TEACHER: SCOPED},
    "attendance.view": {
        PLATFORM_ADMIN: FULL,
        SCHOOL_ADMIN: FULL,
        HEAD_TEACHER: FULL,
        TEACHER: SCOPED,
        STUDENT: SCOPED,
        GUARDIAN: SCOPED,
    },
    "assessment.configure": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: FULL},
    "results.enter": {SCHOOL_ADMIN: FULL, HEAD_TEACHER: FULL, TEACHER: SCOPED},
    "results.view": {
        PLATFORM_ADMIN: FULL,
        SCHOOL_ADMIN: FULL,
        HEAD_TEACHER: FULL,
        TEACHER: SCOPED,
        STUDENT: SCOPED,
        GUARDIAN: SCOPED,
    },
    "results.approve": {SCHOOL_ADMIN: FULL, HEAD_TEACHER: FULL},
    "results.unlock": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "results.recompute": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: FULL},
    "reportcards.generate": {SCHOOL_ADMIN: FULL, HEAD_TEACHER: FULL, TEACHER: SCOPED},
    "reportcards.download": {
        PLATFORM_ADMIN: FULL,
        SCHOOL_ADMIN: FULL,
        HEAD_TEACHER: FULL,
        TEACHER: SCOPED,
        STUDENT: SCOPED,
        GUARDIAN: SCOPED,
    },
    "reportcards.configure": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL, HEAD_TEACHER: FULL},
    "analytics.view": {
        PLATFORM_ADMIN: FULL,
        SCHOOL_ADMIN: FULL,
        HEAD_TEACHER: FULL,
        TEACHER: SCOPED,
        STUDENT: SCOPED,
        GUARDIAN: SCOPED,
    },
    "audit.view": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
    "data.export": {PLATFORM_ADMIN: FULL, SCHOOL_ADMIN: FULL},
}

ALL_PERMISSIONS = tuple(sorted(MATRIX.keys()))


def permissions_for_role(role_key: str) -> list[str]:
    return sorted(code for code, roles in MATRIX.items() if role_key in roles)


def level_for(role_key: str, permission: str) -> str | None:
    return MATRIX.get(permission, {}).get(role_key)


def module_of(permission: str) -> str:
    return permission.split(".", 1)[0]
