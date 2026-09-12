"""Appendix C -- the Redis key registry, as code.

Every key namespace the platform uses is built here, so "a key not in the
registry is a defect" is something the test suite can actually enforce. Every
tenant-owned key carries ``:t:{school_id}:``. No exceptions.

The ``{version}`` segment lets a deployment that changes a cached shape
invalidate everything at once by bumping it.
"""

from __future__ import annotations

from flask import current_app

from ..tenancy import current_school_id

VERSION = "v1"

# TTLs in seconds, from the caching strategy table (spec 3.5).
TTL = {
    "school_by_subdomain": 24 * 3600,
    "config": 3600,
    "permissions": 15 * 60,
    "class_roster": 30 * 60,
    "results": 30 * 60,
    "report_card": 30 * 60,
    "timetable": 6 * 3600,
    "dashboard": 10 * 60,
    "attendance_summary": 3600,
}


def _env() -> str:
    return current_app.config["ENV_NAME"]


def _tenant(school_id=None) -> str:
    resolved = school_id or current_school_id()
    if resolved is None:
        raise RuntimeError("Refusing to build a tenant cache key with no active school.")
    return f"{_env()}:{VERSION}:t:{resolved}"


# ---- global (platform tier) -------------------------------------------------
def school_by_subdomain_key(subdomain: str) -> str:
    return f"{_env()}:{VERSION}:global:school:by-subdomain:{subdomain}"


# ---- tenant-owned -----------------------------------------------------------
def school_config_key(section: str, school_id=None) -> str:
    """section: academic | grading | components | report_card"""
    return f"{_tenant(school_id)}:config:{section}"


def user_permissions_key(user_id, school_id=None) -> str:
    return f"{_tenant(school_id)}:user:{user_id}:permissions"


def class_roster_key(class_id, school_id=None) -> str:
    return f"{_tenant(school_id)}:class:{class_id}:roster"


def class_results_key(class_id, term_id, school_id=None) -> str:
    return f"{_tenant(school_id)}:results:class:{class_id}:term:{term_id}"


def student_results_key(student_id, term_id, school_id=None) -> str:
    return f"{_tenant(school_id)}:results:student:{student_id}:term:{term_id}"


def report_card_key(student_id, term_id, school_id=None) -> str:
    return f"{_tenant(school_id)}:reportcard:{student_id}:{term_id}"


def timetable_key(class_id, school_id=None) -> str:
    return f"{_tenant(school_id)}:timetable:class:{class_id}"


def dashboard_key(role: str, user_id, school_id=None) -> str:
    return f"{_tenant(school_id)}:dashboard:{role}:{user_id}"


def attendance_summary_key(class_id, term_id, school_id=None) -> str:
    return f"{_tenant(school_id)}:attendance:summary:{class_id}:{term_id}"


# ---- invalidation matrix ----------------------------------------------------
# Which write clears which key patterns. Designed alongside the cache, not after
# the first bug report: a stale report card shown to a parent after a correction
# is a serious defect.
INVALIDATION_MATRIX: dict[str, list[str]] = {
    "assessment_config_write": ["config:components", "config:grading", "results:*", "reportcard:*"],
    "academic_config_write": ["config:academic", "class:*:roster"],
    "score_write": ["results:class:{class_id}:term:{term_id}", "reportcard:*", "dashboard:*"],
    "results_recompute": ["results:*", "reportcard:*", "dashboard:*"],
    "results_approval": ["results:*", "reportcard:*"],
    "enrollment_write": ["class:{class_id}:roster", "results:class:{class_id}:*"],
    "attendance_write": ["attendance:summary:{class_id}:*", "reportcard:*", "dashboard:*"],
    "role_or_permission_write": ["user:*:permissions"],
    "school_status_write": ["global:school:by-subdomain:{subdomain}"],
    "timetable_write": ["timetable:class:{class_id}"],
}


def tenant_pattern(pattern: str, school_id=None) -> str:
    return f"{_tenant(school_id)}:{pattern}"
