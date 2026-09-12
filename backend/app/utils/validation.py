"""Server-side validation helpers.

Frontend validation is a convenience, not a control. Every write endpoint
validates here, and field errors come back keyed by field name so the client can
map them onto inputs (spec 6.3 / 7.5).
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .errors import validation_error

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")
RESERVED_SUBDOMAINS = {"www", "api", "admin", "app", "staging", "mail", "docs", "status"}


class Validator:
    """Collects every field error, then raises once with all of them."""

    def __init__(self, payload: dict):
        self.payload = payload or {}
        self.errors: dict[str, list[str]] = {}
        self.data: dict = {}

    def _fail(self, field: str, message: str):
        self.errors.setdefault(field, []).append(message)

    def _present(self, field: str, required: bool, default=None):
        if field not in self.payload or self.payload[field] is None:
            if required:
                self._fail(field, "This field is required.")
            return False, default
        return True, self.payload[field]

    def string(
        self,
        field: str,
        required: bool = False,
        default=None,
        max_length: int | None = None,
        min_length: int | None = None,
        choices: tuple | list | None = None,
        lower: bool = False,
    ):
        present, value = self._present(field, required, default)
        if not present:
            self.data[field] = default
            return default
        value = str(value).strip()
        if lower:
            value = value.lower()
        if required and not value:
            self._fail(field, "This field is required.")
        if min_length and len(value) < min_length:
            self._fail(field, f"Must be at least {min_length} characters.")
        if max_length and len(value) > max_length:
            self._fail(field, f"Must be at most {max_length} characters.")
        if choices and value and value not in choices:
            self._fail(field, f"Must be one of: {', '.join(choices)}.")
        self.data[field] = value
        return value

    def email(self, field: str, required: bool = False, default=None):
        value = self.string(field, required=required, default=default, lower=True)
        if value and not EMAIL_RE.match(value):
            self._fail(field, "Enter a valid email address.")
        return value

    def subdomain(self, field: str, required: bool = True):
        value = self.string(field, required=required, lower=True, max_length=63)
        if value:
            if not SUBDOMAIN_RE.match(value):
                self._fail(field, "Use lowercase letters, numbers and hyphens only.")
            elif value in RESERVED_SUBDOMAINS:
                self._fail(field, "That subdomain is reserved.")
        return value

    def boolean(self, field: str, required: bool = False, default=None):
        present, value = self._present(field, required, default)
        if not present:
            self.data[field] = default
            return default
        if isinstance(value, bool):
            self.data[field] = value
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            parsed = value.lower() == "true"
            self.data[field] = parsed
            return parsed
        self._fail(field, "Must be true or false.")
        return default

    def integer(
        self,
        field: str,
        required: bool = False,
        default=None,
        minimum: int | None = None,
        maximum: int | None = None,
    ):
        present, value = self._present(field, required, default)
        if not present:
            self.data[field] = default
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            self._fail(field, "Must be a whole number.")
            return default
        if minimum is not None and parsed < minimum:
            self._fail(field, f"Must be at least {minimum}.")
        if maximum is not None and parsed > maximum:
            self._fail(field, f"Must be at most {maximum}.")
        self.data[field] = parsed
        return parsed

    def decimal(
        self,
        field: str,
        required: bool = False,
        default=None,
        minimum: float | None = None,
        maximum: float | None = None,
    ):
        present, value = self._present(field, required, default)
        if not present:
            self.data[field] = default
            return default
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            self._fail(field, "Must be a number.")
            return default
        if minimum is not None and parsed < Decimal(str(minimum)):
            self._fail(field, f"Must be at least {minimum}.")
        if maximum is not None and parsed > Decimal(str(maximum)):
            self._fail(field, f"Must be at most {maximum}.")
        self.data[field] = parsed
        return parsed

    def date(self, field: str, required: bool = False, default=None):
        present, value = self._present(field, required, default)
        if not present:
            self.data[field] = default
            return default
        if isinstance(value, date):
            self.data[field] = value
            return value
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except (TypeError, ValueError):
            self._fail(field, "Use an ISO 8601 date, e.g. 2026-09-04.")
            return default
        self.data[field] = parsed
        return parsed

    def uuid(self, field: str, required: bool = False, default=None):
        present, value = self._present(field, required, default)
        if not present:
            self.data[field] = default
            return default
        try:
            parsed = uuid.UUID(str(value))
        except (TypeError, ValueError):
            self._fail(field, "Must be a valid id.")
            return default
        self.data[field] = parsed
        return parsed

    def mapping(self, field: str, required: bool = False, default=None):
        present, value = self._present(field, required, default)
        if not present:
            self.data[field] = default if default is not None else {}
            return self.data[field]
        if not isinstance(value, dict):
            self._fail(field, "Must be an object.")
            return default or {}
        self.data[field] = value
        return value

    def sequence(self, field: str, required: bool = False, default=None):
        present, value = self._present(field, required, default)
        if not present:
            self.data[field] = default if default is not None else []
            return self.data[field]
        if not isinstance(value, list):
            self._fail(field, "Must be a list.")
            return default or []
        self.data[field] = value
        return value

    def add_error(self, field: str, message: str):
        self._fail(field, message)

    def raise_if_invalid(self) -> dict:
        if self.errors:
            raise validation_error(self.errors)
        return self.data


def parse_uuid_or_404(value: str, resource: str = "Resource"):
    from .errors import not_found

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise not_found(resource)


def arg_uuid(name: str, default=None, required: bool = False):
    """Read a UUID from the query string.

    Query parameters arrive as strings; UUID columns will not compare against
    them, so every id filter goes through here.
    """
    from flask import request

    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            raise validation_error({name: ["This parameter is required."]})
        return default
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        raise validation_error({name: ["Must be a valid id."]})
