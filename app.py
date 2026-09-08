from __future__ import annotations

import copy
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=False)

DATA_FILE = Path(os.environ.get("SMS_DATA_FILE", Path(__file__).with_name("sms-data.json")))
DEFAULT_PASSWORD = "password123"

DEFAULT_ACCOUNTS = [
    {"name": "Efua Amedjei", "email": "superadmin@sasuschools.com", "role": "superadmin"},
    {"name": "Grace Owusu", "email": "g.owusu@greenfield.edu", "role": "admin"},
    {"name": "Kwame Asare", "email": "k.asare@riverside.edu", "role": "admin"},
    {"name": "Linda Boateng", "email": "l.boateng@northgate.edu", "role": "admin"},
    {"name": "Daniel Mensah", "email": "teacher@greenfield.edu", "role": "teacher"},
    {"name": "Kojo Mensah", "email": "student@greenfield.edu", "role": "student"},
    {"name": "Yaw Mensah", "email": "parent@greenfield.edu", "role": "parent"},
]

SEED_DATA: dict[str, Any] = {
    "schools": [
        {"id": 1, "name": "Greenfield High School", "address": "12 Lake Road, Accra", "status": "Active", "students": 842, "staff": 61},
        {"id": 2, "name": "Riverside Academy", "address": "9 Palm Street, Kumasi", "status": "Active", "staff": 34, "students": 410},
        {"id": 3, "name": "Northgate College", "address": "4 Hilltop Ave, Tamale", "status": "Suspended", "staff": 20, "students": 190},
    ],
    "admins": [
        {"id": 1, "name": "Grace Owusu", "email": "g.owusu@greenfield.edu", "school": "Greenfield High School", "status": "Active", "password": "password123", "role": "admin"},
        {"id": 2, "name": "Kwame Asare", "email": "k.asare@riverside.edu", "school": "Riverside Academy", "status": "Active", "password": "password123", "role": "admin"},
        {"id": 3, "name": "Linda Boateng", "email": "l.boateng@northgate.edu", "school": "Northgate College", "status": "Suspended", "password": "password123", "role": "admin"},
    ],
    "users": [
        {"id": 1, "name": "Efua Amedjei", "email": "superadmin@sasuschools.com", "role": "superadmin", "password": "password123"},
        {"id": 2, "name": "Daniel Mensah", "email": "teacher@greenfield.edu", "role": "teacher", "password": "password123"},
        {"id": 3, "name": "Kojo Mensah", "email": "student@greenfield.edu", "role": "student", "password": "password123"},
        {"id": 4, "name": "Yaw Mensah", "email": "parent@greenfield.edu", "role": "parent", "password": "password123"},
    ],
    "classes": [
        {"id": 1, "name": "JHS 1A", "teacher": "Mr. Daniel Mensah", "students": 32, "subject": "Homeroom"},
        {"id": 2, "name": "JHS 1B", "teacher": "Mrs. Ama Serwaa", "students": 29, "subject": "Homeroom"},
        {"id": 3, "name": "JHS 2A", "teacher": "Mr. Kofi Adjei", "students": 31, "subject": "Homeroom"},
        {"id": 4, "name": "JHS 3A", "teacher": "Mrs. Efua Baidoo", "students": 28, "subject": "Homeroom"},
    ],
    "students": [
        {"id": 1, "name": "Kojo Mensah", "admission": "GF-2201", "class": "JHS 1A", "parent": "Yaw Mensah", "gender": "M", "attendance": 96, "avg": 78, "status": "Active"},
        {"id": 2, "name": "Abena Owusu", "admission": "GF-2202", "class": "JHS 1A", "parent": "Comfort Owusu", "gender": "F", "attendance": 92, "avg": 85, "status": "Active"},
        {"id": 3, "name": "Yaw Boadi", "admission": "GF-2203", "class": "JHS 1B", "parent": "Nana Boadi", "gender": "M", "attendance": 88, "avg": 64, "status": "Active"},
        {"id": 4, "name": "Efua Ansah", "admission": "GF-2204", "class": "JHS 2A", "parent": "Kwesi Ansah", "gender": "F", "attendance": 99, "avg": 91, "status": "Active"},
        {"id": 5, "name": "Kwesi Appiah", "admission": "GF-2205", "class": "JHS 3A", "parent": "Adjoa Appiah", "gender": "M", "attendance": 74, "avg": 58, "status": "Probation"},
        {"id": 6, "name": "Adjoa Frimpong", "admission": "GF-2206", "class": "JHS 1B", "parent": "Yaw Frimpong", "gender": "F", "attendance": 95, "avg": 73, "status": "Active"},
    ],
    "teachers": [
        {"id": 1, "name": "Daniel Mensah", "staffNo": "T-101", "dept": "Mathematics", "classes": ["JHS 1A"], "qualification": "B.Ed Mathematics"},
        {"id": 2, "name": "Ama Serwaa", "staffNo": "T-102", "dept": "English", "classes": ["JHS 1B"], "qualification": "B.A English"},
        {"id": 3, "name": "Kofi Adjei", "staffNo": "T-103", "dept": "Science", "classes": ["JHS 2A"], "qualification": "B.Sc Chemistry"},
    ],
    "subjects": ["Mathematics", "English Language", "Integrated Science", "Social Studies", "ICT", "French"],
    "attendanceToday": [{"student": "Kojo Mensah", "status": "Present"}, {"student": "Abena Owusu", "status": "Present"}, {"student": "Yaw Boadi", "status": "Absent"}, {"student": "Adjoa Frimpong", "status": "Late"}],
    "assessments": [{"student": "Kojo Mensah", "subject": "Mathematics", "type": "Mid-term Exam", "score": 78, "max": 100, "term": "Term 1"}, {"student": "Abena Owusu", "subject": "Mathematics", "type": "Mid-term Exam", "score": 85, "max": 100, "term": "Term 1"}, {"student": "Yaw Boadi", "subject": "English Language", "type": "CA Test 2", "score": 64, "max": 100, "term": "Term 1"}],
    "results": [{"student": "Kojo Mensah", "class": "JHS 1A", "term": "Term 1", "average": 78, "position": "6th", "grade": "B", "status": "Published"}, {"student": "Abena Owusu", "class": "JHS 1A", "term": "Term 1", "average": 85, "position": "2nd", "grade": "A", "status": "Published"}, {"student": "Yaw Boadi", "class": "JHS 1B", "term": "Term 1", "average": 64, "position": "18th", "grade": "C", "status": "Pending Approval"}],
    "notices": [{"title": "Mid-term Break Schedule", "body": "School will close for mid-term break from Oct 10 to Oct 17.", "role": "All", "date": "2026-09-01"}, {"title": "PTA Meeting - Term 1", "body": "Parent-Teacher meeting holds Saturday 10am in the main hall.", "role": "Parent", "date": "2026-08-28"}, {"title": "Science Fair Submissions", "body": "Project proposals due by end of next week.", "role": "Student", "date": "2026-08-25"}],
    "auditLogs": [{"user": "Grace Owusu", "action": "Published Term 1 results for JHS 1A", "time": "2026-09-04 10:22", "ip": "197.251.4.12"}, {"user": "Super Admin", "action": "Reset password for Kwame Asare", "time": "2026-09-03 15:03", "ip": "10.0.0.4"}, {"user": "Daniel Mensah", "action": "Entered attendance for JHS 1A", "time": "2026-09-05 08:01", "ip": "197.251.4.30"}, {"user": "Unknown", "action": "Failed login attempt (admin@riverside.edu)", "time": "2026-09-05 07:40", "ip": "185.23.4.9"}],
    "timetable": [{"time": "8:00 - 8:45", "mon": "Mathematics", "tue": "English", "wed": "Science", "thu": "ICT", "fri": "Social Studies"}, {"time": "8:45 - 9:30", "mon": "English", "tue": "Mathematics", "wed": "French", "thu": "Science", "fri": "Mathematics"}, {"time": "9:30 - 10:15", "mon": "Science", "tue": "ICT", "wed": "Mathematics", "thu": "English", "fri": "French"}, {"time": "10:15 - 10:30", "mon": "Break", "tue": "Break", "wed": "Break", "thu": "Break", "fri": "Break"}, {"time": "10:30 - 11:15", "mon": "Social Studies", "tue": "Science", "wed": "English", "thu": "Mathematics", "fri": "ICT"}],
    "assignments": [{"title": "Algebra worksheet Ch.4", "subject": "Mathematics", "due": "2026-09-08", "status": "Submitted"}, {"title": "Essay: My Community", "subject": "English Language", "due": "2026-09-10", "status": "Pending"}, {"title": "Lab report - States of Matter", "subject": "Integrated Science", "due": "2026-09-06", "status": "Overdue"}],
    "fees": [], "reports": [], "storeItems": [{"id": 1, "name": "School Uniform (Full Set)", "category": "Uniform", "price": 180, "stock": 24}, {"id": 2, "name": "PE Kit", "category": "Uniform", "price": 90, "stock": 40}, {"id": 3, "name": "Mathematics Textbook", "category": "Books", "price": 45, "stock": 15}, {"id": 4, "name": "Integrated Science Textbook", "category": "Books", "price": 48, "stock": 12}, {"id": 5, "name": "Exercise Books (Pack of 10)", "category": "Stationery", "price": 20, "stock": 60}, {"id": 6, "name": "Geometry Set", "category": "Stationery", "price": 15, "stock": 33}], "studentOrders": [],
}


def load_data() -> dict[str, Any]:
    if not DATA_FILE.exists():
        save_data(SEED_DATA)
    with DATA_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    changed = False
    users = data.setdefault("users", [])
    admins = data.setdefault("admins", [])
    accounts_by_email = {account["email"]: account for account in users + admins}
    for account in DEFAULT_ACCOUNTS:
        existing = accounts_by_email.get(account["email"])
        if existing is None:
            users.append({"id": next_id(users), **account, "password": DEFAULT_PASSWORD})
            changed = True
            continue
        if not existing.get("password") or existing["password"] != DEFAULT_PASSWORD:
            existing["password"] = DEFAULT_PASSWORD
            changed = True
        if not existing.get("role"):
            existing["role"] = account["role"]
            changed = True

    for admin in admins:
        if not admin.get("password"):
            admin["password"] = DEFAULT_PASSWORD
            changed = True
        if not admin.get("role"):
            admin["role"] = "admin"
            changed = True

    if changed:
        save_data(data)
    return data


def save_data(data: dict[str, Any]) -> None:
    temp_file = DATA_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
    temp_file.replace(DATA_FILE)


def next_id(items: list[dict[str, Any]]) -> int:
    return max((item.get("id", 0) for item in items), default=0) + 1


@app.get("/")
def home():
    return "Backend is Live"


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "sms-api"})


@app.get("/api/state")
def state():
    data = load_data()
    public_data = copy.deepcopy(data)
    for user in public_data.get("users", []):
        user.pop("password", None)
    for admin in public_data.get("admins", []):
        admin.pop("password", None)
    return jsonify(public_data)


@app.post("/api/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    role = payload.get("role")
    data = load_data()
    candidates = data.get("users", []) + data.get("admins", [])
    user = next((item for item in candidates if item.get("email", "").lower() == email and item.get("password") == password), None)
    if role and user and user.get("role", "admin") != role:
        user = None
    if not user:
        return jsonify({"error": "Invalid email or password."}), 401
    return jsonify({"role": user.get("role", "admin"), "name": user["name"], "email": user["email"]})


@app.post("/api/auth/signup")
def signup():
    payload = request.get_json(silent=True) or {}
    data = load_data()
    user = {"id": next_id(data["users"]), "name": payload.get("name", "").strip(), "email": payload.get("email", "").strip().lower(), "role": "superadmin", "password": payload.get("password", "")}
    if not user["name"] or not user["email"] or not user["password"]:
        return jsonify({"error": "Name, email and password are required."}), 400
    if any(item.get("email") == user["email"] for item in data["users"] + data["admins"]):
        return jsonify({"error": "An account with that email already exists."}), 409
    data["users"].append(user)
    save_data(data)
    user.pop("password")
    return jsonify(user), 201


@app.post("/api/students")
def add_student():
    data = load_data()
    payload = request.get_json(silent=True) or {}
    student = {"id": next_id(data["students"]), "name": payload.get("name", ""), "admission": payload.get("admission", ""), "class": payload.get("class", ""), "parent": payload.get("parent", ""), "gender": payload.get("gender", ""), "attendance": 100, "avg": 0, "status": "Active"}
    if not student["name"] or not student["admission"]:
        return jsonify({"error": "Name and admission number are required."}), 400
    if any(s["admission"].lower() == student["admission"].lower() for s in data["students"]):
        return jsonify({"error": "Admission number already exists."}), 409
    data["students"].append(student)
    save_data(data)
    return jsonify(student), 201


@app.post("/api/attendance")
def attendance():
    data = load_data()
    for entry in request.get_json(silent=True) or []:
        existing = next((item for item in data["attendanceToday"] if item["student"] == entry.get("student")), None)
        if existing:
            existing["status"] = entry.get("status", "Present")
        else:
            data["attendanceToday"].append({"student": entry.get("student"), "status": entry.get("status", "Present")})
    save_data(data)
    return jsonify(data["attendanceToday"])


@app.post("/api/assessments")
def assessment():
    data = load_data()
    item = request.get_json(silent=True) or {}
    data["assessments"].append(item)
    save_data(data)
    return jsonify(item), 201


@app.patch("/api/results/<int:index>")
def update_result(index: int):
    data = load_data()
    if index < 0 or index >= len(data["results"]):
        return jsonify({"error": "Result not found."}), 404
    data["results"][index].update(request.get_json(silent=True) or {})
    save_data(data)
    return jsonify(data["results"][index])


@app.post("/api/fees")
def add_fee():
    return _add_document("fees")


@app.post("/api/reports")
def add_report():
    return _add_document("reports")


def _add_document(collection: str):
    data = load_data()
    document = request.get_json(silent=True) or {}
    document["id"] = next_id(data[collection])
    document["uploadedAt"] = date.today().isoformat()
    data[collection].append(document)
    save_data(data)
    return jsonify(document), 201


@app.post("/api/notices")
def add_notice():
    data = load_data()
    notice = request.get_json(silent=True) or {}
    notice.setdefault("date", date.today().isoformat())
    data["notices"].append(notice)
    save_data(data)
    return jsonify(notice), 201


@app.post("/api/subjects")
def add_subject():
    data = load_data()
    subject = str((request.get_json(silent=True) or {}).get("subject", "")).strip()
    if subject and subject not in data["subjects"]:
        data["subjects"].append(subject)
        save_data(data)
    return jsonify(data["subjects"])


@app.post("/api/orders")
def add_order():
    data = load_data()
    payload = request.get_json(silent=True) or {}
    items = []
    for requested in payload.get("cart", []):
        item = next((entry for entry in data["storeItems"] if entry["id"] == int(requested["id"])), None)
        quantity = int(requested.get("qty", 0))
        if not item or quantity < 1 or quantity > item["stock"]:
            return jsonify({"error": "Invalid item quantity or insufficient stock."}), 400
        items.append({"id": item["id"], "name": item["name"], "price": item["price"], "qty": quantity})
    if not items:
        return jsonify({"error": "Cart is empty."}), 400
    for ordered in items:
        item = next(entry for entry in data["storeItems"] if entry["id"] == ordered["id"])
        item["stock"] -= ordered["qty"]
    order = {"id": next_id(data["studentOrders"]), "student": payload.get("student", ""), "items": items, "total": sum(i["price"] * i["qty"] for i in items), "status": "Pending Pickup", "date": date.today().isoformat()}
    data["studentOrders"].append(order)
    save_data(data)
    return jsonify(order), 201


@app.post("/api/state/replace")
def replace_state():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a state object."}), 400
    data = load_data()
    for key in ("schools", "admins", "classes", "students", "teachers", "subjects", "attendanceToday", "assessments", "results", "notices", "auditLogs", "timetable", "assignments", "fees", "reports", "storeItems", "studentOrders"):
        if key in payload:
            data[key] = payload[key]
    save_data(data)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
