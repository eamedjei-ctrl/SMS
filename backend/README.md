# SchoolOS API

Multi-tenant Flask backend built to the SchoolOS Team Charter & Build
Specification v1.0. Covers modules **M1–M8**: tenancy and onboarding, identity
and access control, people, academic structure, enrollment and promotion,
attendance, the results engine, and report cards.

## The three rules this codebase is held to

1. **Nothing is hardcoded.** No grade band, weight, subject name, term name or
   remark appears in application code. Components, scales, bands, rounding, tie
   rules and aggregation are rows the school owns. A GES school and a Cambridge
   school run the same code and get different, correct results.
2. **Backend and data before pixels.** Logic, endpoints and schema first.
3. **Tenant isolation is a safety property.** Enforced centrally in
   `app/tenancy.py`, not by developers remembering to filter.

## Layout

```
app/
  __init__.py        application factory, request lifecycle, error handlers
  config.py          environment configuration (Appendix D)
  tenancy.py         the school_id guard -- read this first
  security.py        password hashing, JWTs, @requires permission decorator
  permissions.py     the permission matrix (Appendix B), as data
  openapi.py         specification generated from the live URL map
  cli.py             bootstrap / seed-templates / seed-demo
  models/            SQLAlchemy models; TenantModel vs PlatformModel
  services/          business logic -- knows nothing about HTTP
    results_engine.py    the core of the product; pure functions up top
    provisioning.py      seed template -> real rows, transactionally
    report_card_service.py
    scope_service.py     "for which class?" -- resource-level checks
    cache_keys.py        the Redis key registry (Appendix C), as code
  api/               one blueprint per module, all under /api/v1
  utils/             response envelope, error vocabulary, validation
migrations/          Alembic; every schema change lives here
seed/                curriculum templates (Appendix A)
tests/               109 tests, incl. the isolation and engine suites
```

### Layer rules (spec 3.2)

| Layer | May talk to | Must never |
|---|---|---|
| `api/` | services | contain business logic or raw queries |
| `services/` | models, cache, external services | know about HTTP requests |
| `models/` | the database | contain business rules |

## Running it locally

```bash
python -m venv .venv && .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                              # then fill in the secrets

export FLASK_APP=wsgi.py
flask db upgrade          # create the schema
flask seed-templates      # load the GES and Cambridge templates
flask seed-demo           # a working demo school in one command
flask run
```

`seed-demo` prints the accounts it created. Every tenant request needs a school:
locally, send the `X-School-Subdomain: demo` header; in production the subdomain
of the request host is used.

```bash
curl -X POST http://127.0.0.1:5000/api/v1/auth/login \
  -H 'Content-Type: application/json' -H 'X-School-Subdomain: demo' \
  -d '{"identifier":"teacher@demo.test","password":"Passw0rd!demo"}'
```

Interactive API docs (non-production only): <http://127.0.0.1:5000/api/v1/docs>

## With Docker

```bash
cp backend/.env.example .env   # repo root; set POSTGRES_PASSWORD, REDIS_PASSWORD, SECRET_KEY, JWT_SECRET_KEY
docker compose up --build
```

The container runs `flask db upgrade` before starting gunicorn, so a deploy
never serves a schema it does not have.

## Tests

```bash
pytest                                   # all 109
pytest tests/test_tenant_isolation.py    # blocks every merge (spec 8.2)
pytest tests/test_results_engine.py      # highest priority (spec 10.2)
```

The isolation suite creates two schools with identical data shapes and points
School A's session at every School B resource it can name. If any assertion in
it fails, nothing ships.

## Decisions worth knowing

- **Tenant enforcement is a `do_orm_execute` hook**, not a query subclass. It
  rewrites every ORM SELECT with `with_loader_criteria`, so joins and lazy loads
  are covered too. The only way past it is the explicit `unscoped()` context
  manager, which every call site comments and which exists for the platform tier
  (school registry, curriculum templates, platform staff).
- **No tenant bound means no rows**, not all rows. The guard fails closed.
- **Cross-tenant access returns 404, never 403.** A 403 would confirm the
  resource exists somewhere else.
- **Grade bands tolerate gaps.** Schools write "70–79" then "80–100" and mean
  "70 up to but not including 80". A total of 79.6 resolves to the lower band
  rather than printing a blank grade. A total above the highest band returns no
  grade, because that is a misconfiguration the school should see.
- **Results are materialised on write, not computed on read.** Positions need
  the whole class, and a card reprinted in two years must show what it showed
  the day it was issued.
- **Report cards freeze their payload.** The stored JSON is what the PDF was
  built from, so regeneration is reproducible after a configuration change.
- **Passwords are Argon2id**, deliberately cheap under `TESTING` only.

## Not built yet

Deferred by scope, not forgotten. Each is listed with what already anchors it:

| Gap | Status |
|---|---|
| Redis caching | Key registry and invalidation matrix exist in `services/cache_keys.py`; only the token blacklist reads Redis today. Everything else goes to PostgreSQL. |
| Celery workers | `report_card_jobs` rows, progress fields and the `202 + job_id` polling contract are in place; batch generation still runs inline. |
| M9 Timetable, M10 Fees, M11 Communication, M12 Learning, M13 AI, M14 Analytics | Not started. Permissions for them are already in the matrix. |
| SMS / email delivery | Password reset returns its token outside production instead of sending it. |
| Rate limiting | Account lockout is implemented; per-IP throttling is not. |
| MFA | Columns exist on `users`; no enrolment or verification flow. |

Seed template values in `seed/` are **placeholders**. They must be replaced with
the PM's curriculum research, with a source next to every weight and band,
before a real school is onboarded.
