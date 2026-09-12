"""SQLAlchemy models.

Every tenant-owned entity inherits ``TenantModel`` and is therefore scoped
automatically. Platform-tier entities inherit ``PlatformModel`` and must never
carry ``school_id``.
"""

from .academic import (  # noqa: F401
    AcademicYear,
    ClassSubject,
    ClassSubjectTeacher,
    SchoolClass,
    Subject,
    Term,
)
from .assessment import (  # noqa: F401
    AssessmentComponent,
    AssessmentScore,
    AssessmentSettings,
    GradeBand,
    GradeScale,
    Result,
    ResultRemark,
    TermResult,
)
from .attendance import AttendanceRecord, AttendanceSettings, AttendanceStatus  # noqa: F401
from .audit import AuditLog  # noqa: F401
from .base import PlatformModel, TenantModel  # noqa: F401
from .enrollment import Enrollment, EnrollmentHistory, PromotionBatch  # noqa: F401
from .identity import (  # noqa: F401
    LoginAttempt,
    PasswordReset,
    Permission,
    RefreshSession,
    Role,
    RolePermission,
    User,
    UserRole,
)
from .people import Guardian, ImportJob, Staff, Student, StudentGuardian  # noqa: F401
from .platform import (  # noqa: F401
    CurriculumTemplate,
    OnboardingProgress,
    PlatformUser,
    School,
)
from .reportcard import (  # noqa: F401
    GeneratedReportCard,
    ReportCardJob,
    ReportCardTemplate,
)

__all__ = [
    "AcademicYear",
    "AssessmentComponent",
    "AssessmentScore",
    "AssessmentSettings",
    "AttendanceRecord",
    "AttendanceSettings",
    "AttendanceStatus",
    "AuditLog",
    "ClassSubject",
    "ClassSubjectTeacher",
    "CurriculumTemplate",
    "Enrollment",
    "EnrollmentHistory",
    "GeneratedReportCard",
    "GradeBand",
    "GradeScale",
    "Guardian",
    "ImportJob",
    "LoginAttempt",
    "OnboardingProgress",
    "PasswordReset",
    "Permission",
    "PlatformModel",
    "PlatformUser",
    "PromotionBatch",
    "RefreshSession",
    "ReportCardJob",
    "ReportCardTemplate",
    "Result",
    "ResultRemark",
    "Role",
    "RolePermission",
    "School",
    "SchoolClass",
    "Staff",
    "Student",
    "StudentGuardian",
    "Subject",
    "TenantModel",
    "Term",
    "TermResult",
    "User",
    "UserRole",
]
