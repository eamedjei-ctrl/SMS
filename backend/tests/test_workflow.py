"""End-to-end journeys (spec 10.3) and the auth lifecycle (M2).

These run through the API exactly as a client would: onboard, populate, mark,
score, compute, approve, print.
"""

from __future__ import annotations

from app.extensions import db


# ==========================================================================
# Journey 1 -- a school signs up, completes the wizard, becomes active
# ==========================================================================
def test_platform_can_onboard_a_school_end_to_end(client, app, templates):
    from app.models import PlatformUser
    from app.security import hash_password
    from app.tenancy import unscoped

    with unscoped():
        db.session.add(
            PlatformUser(
                email="ops@schoolos.test",
                full_name="Platform Ops",
                password_hash=hash_password("Passw0rd!ops"),
                role="platform_admin",
            )
        )
        db.session.commit()

    login = client.post(
        "/api/v1/platform/auth/login",
        json={"email": "ops@schoolos.test", "password": "Passw0rd!ops"},
    )
    assert login.status_code == 200
    platform_headers = {"Authorization": f"Bearer {login.get_json()['data']['access_token']}"}

    availability = client.get("/api/v1/platform/subdomains/accra-high")
    assert availability.get_json()["data"]["available"] is True

    creation = client.post(
        "/api/v1/platform/schools",
        json={
            "name": "Accra High School",
            "subdomain": "accra-high",
            "curriculum_mode": "ges",
            "admin_full_name": "Head Teacher",
            "admin_email": "head@accra-high.test",
            "admin_password": "Passw0rd!head",
        },
        headers=platform_headers,
    )
    assert creation.status_code == 201, creation.get_json()

    taken = client.get("/api/v1/platform/subdomains/accra-high")
    assert taken.get_json()["data"]["available"] is False
    assert taken.get_json()["data"]["suggestions"]

    school_headers = {"X-School-Subdomain": "accra-high"}
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "head@accra-high.test", "password": "Passw0rd!head"},
        headers=school_headers,
    )
    assert admin_login.status_code == 200
    assert admin_login.get_json()["data"]["must_change_password"] is True
    auth = {
        "Authorization": f"Bearer {admin_login.get_json()['data']['access_token']}",
        **school_headers,
    }

    # A brand new school cannot go live until it is actually configured.
    premature = client.post("/api/v1/onboarding/activate", json={}, headers=auth)
    assert premature.status_code == 409

    saved = client.put(
        "/api/v1/onboarding/steps/school_identity",
        json={"name": "Accra High School", "phone": "+233200000000"},
        headers=auth,
    )
    assert saved.status_code == 200
    assert "school_identity" in saved.get_json()["data"]["completed_steps"]

    applied = client.post(
        "/api/v1/onboarding/apply-template",
        json={"template_key": "ges-basic-v1"},
        headers=auth,
    )
    assert applied.status_code == 200
    summary = applied.get_json()["data"]["applied"]
    assert summary["levels"] == 6 and summary["subjects"] == 7 and summary["components"] == 2

    # Step 6's worked example, computed from the configuration just applied.
    preview = client.get("/api/v1/onboarding/preview", headers=auth)
    example = preview.get_json()["data"]
    assert example["available"] is True
    assert example["total_weight"] == 100.0
    assert example["total_score"] == 80.0
    assert example["grade"] == "1"

    activated = client.post("/api/v1/onboarding/activate", json={}, headers=auth)
    assert activated.status_code == 200
    assert activated.get_json()["data"]["school"]["status"] == "active"


def test_wizard_progress_is_resumable(client, school_a, login):
    headers = login(school_a, "school_admin")
    client.put(
        "/api/v1/onboarding/steps/academic_calendar",
        json={"terms_per_year": 3},
        headers=headers,
    )
    resumed = client.get("/api/v1/onboarding", headers=headers).get_json()["data"]
    assert resumed["progress"]["step_data"]["academic_calendar"]["terms_per_year"] == 3
    assert resumed["progress"]["current_step"] == 4


# ==========================================================================
# Journey 2 -- import students and enroll them
# ==========================================================================
def test_bulk_import_reports_every_bad_row_before_writing_anything(client, school_a, login):
    headers = login(school_a, "school_admin")
    rows = [
        {"student_code": "IMP-1", "first_name": "Good", "last_name": "Row"},
        {"student_code": "", "first_name": "Missing", "last_name": "Code"},
        {
            "student_code": "IMP-3",
            "first_name": "Bad",
            "last_name": "Date",
            "date_of_birth": "not-a-date",
        },
        {"student_code": "IMP-1", "first_name": "Duplicate", "last_name": "InFile"},
        {
            "student_code": school_a.students[0].student_code,
            "first_name": "Already",
            "last_name": "Exists",
        },
    ]
    dry_run = client.post("/api/v1/students/import", json=rows, headers=headers)
    assert dry_run.status_code == 200
    job = dry_run.get_json()["data"]

    assert job["total_rows"] == 5
    assert job["valid_rows"] == 1
    assert job["error_rows"] == 4
    assert {error["row"] for error in job["errors"]} == {2, 3, 4, 5}

    # Nothing was written by the dry run.
    listing = client.get("/api/v1/students?q=Good&per_page=100", headers=headers)
    assert listing.get_json()["data"] == []

    # A file with errors cannot be committed.
    blocked = client.post(f"/api/v1/students/import/{job['id']}/commit", json={}, headers=headers)
    assert blocked.status_code == 409

    clean = client.post(
        "/api/v1/students/import",
        json=[
            {
                "student_code": "IMP-10",
                "first_name": "Ama",
                "last_name": "Mensah",
                "guardian_first_name": "Yaw",
                "guardian_last_name": "Mensah",
                "guardian_phone": "+233240000001",
            },
            {
                "student_code": "IMP-11",
                "first_name": "Kojo",
                "last_name": "Mensah",
                "guardian_first_name": "Yaw",
                "guardian_last_name": "Mensah",
                "guardian_phone": "+233240000001",
            },
        ],
        headers=headers,
    )
    clean_job = clean.get_json()["data"]
    assert clean_job["error_rows"] == 0

    committed = client.post(
        f"/api/v1/students/import/{clean_job['id']}/commit", json={}, headers=headers
    )
    assert committed.status_code == 200
    data = committed.get_json()["data"]
    assert data["students_created"] == 2
    # Siblings share one guardian record, so one login shows both children.
    assert data["guardians_created"] == 1


# ==========================================================================
# Journey 3 -- attendance
# ==========================================================================
def test_teacher_marks_a_class_in_one_request(client, school_a, login):
    headers = login(school_a, "teacher")

    register = client.get(
        f"/api/v1/attendance/register?class_id={school_a.class_id}", headers=headers
    )
    assert register.status_code == 200
    assert register.get_json()["data"]["marked_count"] == 0
    assert len(register.get_json()["data"]["students"]) == len(school_a.students)

    marked = client.post(
        "/api/v1/attendance",
        json={
            "class_id": str(school_a.class_id),
            "default_status": "present",
            "apply_default_to_all": True,
            "entries": [{"student_id": str(school_a.students[1].id), "status_code": "absent"}],
        },
        headers=headers,
    )
    assert marked.status_code == 200
    assert marked.get_json()["data"]["records_written"] == len(school_a.students)

    summary = client.get(
        f"/api/v1/attendance/summary?class_id={school_a.class_id}", headers=headers
    ).get_json()["data"]
    absent = [row for row in summary["students"] if row["days_absent"] == 1]
    assert len(absent) == 1


def test_attendance_cannot_be_marked_in_the_future(client, school_a, login):
    headers = login(school_a, "teacher")
    response = client.post(
        "/api/v1/attendance",
        json={
            "class_id": str(school_a.class_id),
            "date": "2099-01-01",
            "entries": [{"student_id": str(school_a.students[0].id), "status_code": "present"}],
        },
        headers=headers,
    )
    assert response.status_code == 409


# ==========================================================================
# Journey 4-6 -- score entry, computation, approval, report cards
# ==========================================================================
def _enter_full_scores(client, school, headers, scores_by_index):
    for subject in school.subjects:
        payload = []
        for index, component_scores in scores_by_index.items():
            for component_code, raw in component_scores.items():
                component = next(c for c in school.components if c.code == component_code)
                payload.append(
                    {
                        "student_id": str(school.students[index].id),
                        "component_id": str(component.id),
                        "raw_score": raw,
                    }
                )
        response = client.post(
            "/api/v1/scores",
            json={
                "class_id": str(school.class_id),
                "subject_id": str(subject.id),
                "term_id": str(school.term_id),
                "scores": payload,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.get_json()


def test_score_entry_validates_against_the_configured_maximum(client, school_a, login):
    headers = login(school_a, "teacher")
    response = client.post(
        "/api/v1/scores",
        json={
            "class_id": str(school_a.class_id),
            "subject_id": str(school_a.subjects[0].id),
            "term_id": str(school_a.term_id),
            "scores": [
                {
                    "student_id": str(school_a.students[0].id),
                    "component_id": str(school_a.components[0].id),
                    "raw_score": 150,
                }
            ],
        },
        headers=headers,
    )
    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "maximum of 100" in error["details"]["scores[0].raw_score"][0]


def test_full_results_journey(client, school_a, login):
    teacher = login(school_a, "teacher")
    head = login(school_a, "head_teacher")

    _enter_full_scores(
        client,
        school_a,
        teacher,
        {
            0: {"CLS": 90, "EXM": 90},  # 90
            1: {"CLS": 60, "EXM": 80},  # 74
            2: {"CLS": 60, "EXM": 80},  # 74 -- tied with student 1
            3: {"CLS": 30, "EXM": 40},  # 37
        },
    )

    sheet = client.get(
        f"/api/v1/scores?class_id={school_a.class_id}&subject_id={school_a.subjects[0].id}"
        f"&term_id={school_a.term_id}",
        headers=teacher,
    ).get_json()["data"]
    assert sheet["unmarked_count"] == 0

    computed = client.post(
        "/api/v1/results/compute",
        json={"class_id": str(school_a.class_id), "term_id": str(school_a.term_id)},
        headers=head,
    )
    assert computed.status_code == 200
    assert computed.get_json()["data"]["students"] == 4

    broadsheet = client.get(
        f"/api/v1/results/broadsheet?class_id={school_a.class_id}&term_id={school_a.term_id}",
        headers=head,
    ).get_json()["data"]

    by_code = {row["student_code"]: row for row in broadsheet["students"]}
    first = by_code[school_a.students[0].student_code]
    second = by_code[school_a.students[1].student_code]
    third = by_code[school_a.students[2].student_code]
    last = by_code[school_a.students[3].student_code]

    subject_id = str(school_a.subjects[0].id)
    assert first["subjects"][subject_id]["total_score"] == 90.0
    assert first["subjects"][subject_id]["grade"] == "1"
    assert last["subjects"][subject_id]["grade"] == "6"

    # The configured tie rule: shared position, and the next position skips.
    assert (
        second["subjects"][subject_id]["position"] == third["subjects"][subject_id]["position"] == 2
    )
    assert last["subjects"][subject_id]["position"] == 4
    assert first["overall_position"] == 1

    # A family sees nothing until a head teacher has approved.
    guardian = login(school_a, "guardian")
    before = client.get("/api/v1/my/results", headers=guardian).get_json()["data"]
    assert before["children"][0]["results"] == []

    approved = client.post(
        "/api/v1/results/approve",
        json={
            "class_id": str(school_a.class_id),
            "term_id": str(school_a.term_id),
            "lock_term": True,
        },
        headers=head,
    )
    assert approved.status_code == 200
    assert approved.get_json()["data"]["term_locked"] is True

    after = client.get("/api/v1/my/results", headers=guardian).get_json()["data"]
    assert len(after["children"][0]["results"]) == len(school_a.subjects)

    # Once locked, a teacher's edit is refused with a code the UI can explain.
    locked = client.post(
        "/api/v1/scores",
        json={
            "class_id": str(school_a.class_id),
            "subject_id": str(school_a.subjects[0].id),
            "term_id": str(school_a.term_id),
            "scores": [
                {
                    "student_id": str(school_a.students[0].id),
                    "component_id": str(school_a.components[0].id),
                    "raw_score": 100,
                }
            ],
        },
        headers=teacher,
    )
    assert locked.status_code == 423
    assert locked.get_json()["error"]["code"] == "TERM_LOCKED"


def test_report_card_generation_and_download(client, school_a, login):
    teacher = login(school_a, "teacher")
    admin = login(school_a, "school_admin")

    _enter_full_scores(client, school_a, teacher, {i: {"CLS": 70, "EXM": 70} for i in range(4)})
    client.post(
        "/api/v1/results/compute",
        json={"class_id": str(school_a.class_id), "term_id": str(school_a.term_id)},
        headers=admin,
    )

    client.put(
        f"/api/v1/students/{school_a.students[0].id}/remarks",
        json={"term_id": str(school_a.term_id), "body": "A steady term of work."},
        headers=teacher,
    )

    preview = client.get(
        f"/api/v1/report-cards/preview?student_id={school_a.students[0].id}"
        f"&term_id={school_a.term_id}",
        headers=admin,
    )
    assert preview.status_code == 200
    payload = preview.get_json()["data"]
    assert len(payload["subjects"]) == len(school_a.subjects)
    assert payload["subjects"][0]["total_score"] == 70.0
    assert payload["remarks"]["teacher"] == "A steady term of work."
    assert payload["grade_key"]

    batch = client.post(
        "/api/v1/report-cards/generate",
        json={"class_id": str(school_a.class_id), "term_id": str(school_a.term_id)},
        headers=admin,
    )
    assert batch.status_code == 202
    job = batch.get_json()["data"]
    assert job["total"] == 4

    status = client.get(f"/api/v1/jobs/{job['job_id']}", headers=admin).get_json()["data"]
    assert status["status"] == "completed"
    assert status["completed"] == 4
    assert status["progress"] == 100

    cards = client.get(
        f"/api/v1/report-cards?class_id={school_a.class_id}", headers=admin
    ).get_json()["data"]
    assert len(cards) == 4

    download = client.get(f"/api/v1/report-cards/{cards[0]['id']}/download", headers=admin)
    assert download.status_code == 200
    assert download.mimetype == "application/pdf"
    assert download.data.startswith(b"%PDF")


# ==========================================================================
# Promotion
# ==========================================================================
def test_promotion_moves_the_class_and_keeps_history(client, school_a, login):
    from app.models import SchoolClass
    from app.tenancy import set_current_school, tenant_context

    headers = login(school_a, "school_admin")
    with tenant_context(school_a.school.id):
        set_current_school(school_a.school.id)
        source = SchoolClass.query.filter_by(id=school_a.class_id).first()
        target = (
            SchoolClass.query.filter(SchoolClass.level > source.level)
            .order_by(SchoolClass.level)
            .first()
        )
        target_id = target.id

    held_back = school_a.students[3]
    response = client.post(
        "/api/v1/promotions/execute",
        json={
            "source_class_id": str(school_a.class_id),
            "target_class_id": str(target_id),
            "retained_student_ids": [str(held_back.id)],
        },
        headers=headers,
    )
    assert response.status_code == 201
    batch = response.get_json()["data"]
    assert batch["promoted_count"] == 3
    assert batch["retained_count"] == 1

    promoted_roster = client.get(f"/api/v1/classes/{target_id}/roster", headers=headers).get_json()[
        "data"
    ]
    assert promoted_roster["count"] == 3

    source_roster = client.get(
        f"/api/v1/classes/{school_a.class_id}/roster", headers=headers
    ).get_json()["data"]
    assert source_roster["count"] == 1

    history = client.get(
        f"/api/v1/students/{held_back.id}/enrollments", headers=headers
    ).get_json()["data"]
    assert any(entry["action"] == "repeated" for entry in history["history"])


# ==========================================================================
# Auth lifecycle
# ==========================================================================
def test_account_locks_after_repeated_failures(client, school_a):
    headers = {"X-School-Subdomain": school_a.subdomain}
    identifier = f"teacher@{school_a.subdomain}.test"

    for _ in range(5):
        failed = client.post(
            "/api/v1/auth/login",
            json={"identifier": identifier, "password": "wrong-password"},
            headers=headers,
        )
        assert failed.status_code == 401

    # The sixth attempt is refused, and the correct password no longer helps.
    locked = client.post(
        "/api/v1/auth/login",
        json={"identifier": identifier, "password": "Passw0rd!test"},
        headers=headers,
    )
    assert locked.status_code == 403
    message = locked.get_json()["error"]["message"].lower()
    assert "locked" in message and "reset your password" in message


def test_unknown_account_and_wrong_password_are_indistinguishable(client, school_a):
    headers = {"X-School-Subdomain": school_a.subdomain}
    unknown = client.post(
        "/api/v1/auth/login",
        json={"identifier": "nobody@nowhere.test", "password": "whatever"},
        headers=headers,
    )
    wrong = client.post(
        "/api/v1/auth/login",
        json={"identifier": f"teacher@{school_a.subdomain}.test", "password": "whatever"},
        headers=headers,
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json()["error"] == wrong.get_json()["error"]


def test_refresh_rotates_and_the_old_token_stops_working(client, school_a):
    headers = {"X-School-Subdomain": school_a.subdomain}
    session = client.post(
        "/api/v1/auth/login",
        json={
            "identifier": f"school_admin@{school_a.subdomain}.test",
            "password": "Passw0rd!test",
        },
        headers=headers,
    ).get_json()["data"]

    refreshed = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": session["refresh_token"]},
        headers=headers,
    )
    assert refreshed.status_code == 200
    assert refreshed.get_json()["data"]["access_token"] != session["access_token"]

    reused = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": session["refresh_token"]},
        headers=headers,
    )
    assert reused.status_code == 401


def test_password_reset_flow(client, school_a):
    headers = {"X-School-Subdomain": school_a.subdomain}
    identifier = f"student@{school_a.subdomain}.test"

    started = client.post(
        "/api/v1/auth/password/forgot", json={"identifier": identifier}, headers=headers
    )
    assert started.status_code == 200
    token = started.get_json()["data"]["reset_token"]

    weak = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "password123"},
        headers=headers,
    )
    assert weak.status_code == 422

    reset = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "N3wPassw0rd!"},
        headers=headers,
    )
    assert reset.status_code == 200

    reused = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "AnotherPass1!"},
        headers=headers,
    )
    assert reused.status_code == 422

    signed_in = client.post(
        "/api/v1/auth/login",
        json={"identifier": identifier, "password": "N3wPassw0rd!"},
        headers=headers,
    )
    assert signed_in.status_code == 200


def test_forgot_password_does_not_reveal_whether_an_account_exists(client, school_a):
    headers = {"X-School-Subdomain": school_a.subdomain}
    known = client.post(
        "/api/v1/auth/password/forgot",
        json={"identifier": f"student@{school_a.subdomain}.test"},
        headers=headers,
    )
    unknown = client.post(
        "/api/v1/auth/password/forgot",
        json={"identifier": "nobody@nowhere.test"},
        headers=headers,
    )
    assert known.get_json()["data"]["message"] == unknown.get_json()["data"]["message"]


# ==========================================================================
# API contract
# ==========================================================================
def test_every_response_carries_the_standard_envelope(client, school_a, login):
    headers = login(school_a, "school_admin")
    response = client.get("/api/v1/students", headers=headers)
    body = response.get_json()

    assert body["success"] is True
    assert "data" in body
    assert body["meta"]["request_id"].startswith("req_")
    assert body["meta"]["pagination"]["per_page"] == 25
    assert response.headers["X-Request-Id"] == body["meta"]["request_id"]


def test_per_page_is_clamped_not_rejected(client, school_a, login):
    headers = login(school_a, "school_admin")
    response = client.get("/api/v1/students?per_page=5000", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["meta"]["pagination"]["per_page"] == 100


def test_openapi_specification_is_served_and_documents_permissions(client):
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    spec = response.get_json()
    assert spec["openapi"].startswith("3.")

    operation = spec["paths"]["/api/v1/results/approve"]["post"]
    assert "results.approve" in operation["description"]
    assert operation["security"] == [{"bearerAuth": []}]


def test_health_endpoint_reports_database_status(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.get_json()["data"]["checks"]["database"] == "ok"
