"""Blueprint registration. One blueprint per module, all under /api/v1."""

from __future__ import annotations

from flask import Flask

API_PREFIX = "/api/v1"


def register_blueprints(app: Flask) -> None:
    from . import (
        academic,
        assessment,
        attendance,
        auth,
        enrollment,
        meta,
        onboarding,
        people,
        platform,
        reportcards,
        results,
        users,
    )

    for blueprint in (
        meta.bp,
        platform.auth_bp,
        platform.bp,
        auth.bp,
        onboarding.bp,
        users.bp,
        people.bp,
        academic.bp,
        enrollment.bp,
        attendance.bp,
        assessment.bp,
        results.bp,
        reportcards.bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
