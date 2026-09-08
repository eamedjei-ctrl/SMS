// Shared client data layer backed by the Flask API.

const DB = {
  schools: [
    { id: 1, name: "Greenfield High School", address: "12 Lake Road, Accra", status: "Active", students: 842, staff: 61 },
    { id: 2, name: "Riverside Academy", address: "9 Palm Street, Kumasi", status: "Active", staff: 34, students: 410 },
    { id: 3, name: "Northgate College", address: "4 Hilltop Ave, Tamale", status: "Suspended", staff: 20, students: 190 },
  ],
  admins: [
    { id: 1, name: "Grace Owusu", email: "g.owusu@greenfield.edu", school: "Greenfield High School", status: "Active", password: "password123", role: "admin" },
    { id: 2, name: "Kwame Asare", email: "k.asare@riverside.edu", school: "Riverside Academy", status: "Active", password: "password123", role: "admin" },
    { id: 3, name: "Linda Boateng", email: "l.boateng@northgate.edu", school: "Northgate College", status: "Suspended", password: "password123", role: "admin" },
  ],
  // Temporary development accounts used by the Flask authentication route.
  authUsers: [
    { name: "Efua Amedjei", email: "superadmin@sasuschools.com", role: "superadmin", password: "password123" },
    { name: "Grace Owusu", email: "g.owusu@greenfield.edu", role: "admin", password: "password123" },
    { name: "Kwame Asare", email: "k.asare@riverside.edu", role: "admin", password: "password123" },
    { name: "Linda Boateng", email: "l.boateng@northgate.edu", role: "admin", password: "password123" },
    { name: "Daniel Mensah", email: "teacher@greenfield.edu", role: "teacher", password: "password123" },
    { name: "Kojo Mensah", email: "student@greenfield.edu", role: "student", password: "password123" },
    { name: "Yaw Mensah", email: "parent@greenfield.edu", role: "parent", password: "password123" },
  ],
  classes: [
    { id: 1, name: "JHS 1A", teacher: "Mr. Daniel Mensah", students: 32, subject: "Homeroom" },
    { id: 2, name: "JHS 1B", teacher: "Mrs. Ama Serwaa", students: 29, subject: "Homeroom" },
    { id: 3, name: "JHS 2A", teacher: "Mr. Kofi Adjei", students: 31, subject: "Homeroom" },
    { id: 4, name: "JHS 3A", teacher: "Mrs. Efua Baidoo", students: 28, subject: "Homeroom" },
  ],
  students: [
    { id: 1, name: "Kojo Mensah", admission: "GF-2201", class: "JHS 1A", parent: "Yaw Mensah", gender: "M", attendance: 96, avg: 78, status: "Active" },
    { id: 2, name: "Abena Owusu", admission: "GF-2202", class: "JHS 1A", parent: "Comfort Owusu", gender: "F", attendance: 92, avg: 85, status: "Active" },
    { id: 3, name: "Yaw Boadi", admission: "GF-2203", class: "JHS 1B", parent: "Nana Boadi", gender: "M", attendance: 88, avg: 64, status: "Active" },
    { id: 4, name: "Efua Ansah", admission: "GF-2204", class: "JHS 2A", parent: "Kwesi Ansah", gender: "F", attendance: 99, avg: 91, status: "Active" },
    { id: 5, name: "Kwesi Appiah", admission: "GF-2205", class: "JHS 3A", parent: "Adjoa Appiah", gender: "M", attendance: 74, avg: 58, status: "Probation" },
    { id: 6, name: "Adjoa Frimpong", admission: "GF-2206", class: "JHS 1B", parent: "Yaw Frimpong", gender: "F", attendance: 95, avg: 73, status: "Active" },
  ],
  teachers: [
    { id: 1, name: "Daniel Mensah", staffNo: "T-101", dept: "Mathematics", classes: ["JHS 1A"], qualification: "B.Ed Mathematics" },
    { id: 2, name: "Ama Serwaa", staffNo: "T-102", dept: "English", classes: ["JHS 1B"], qualification: "B.A English" },
    { id: 3, name: "Kofi Adjei", staffNo: "T-103", dept: "Science", classes: ["JHS 2A"], qualification: "B.Sc Chemistry" },
  ],
  subjects: ["Mathematics", "English Language", "Integrated Science", "Social Studies", "ICT", "French"],
  attendanceToday: [
    { student: "Kojo Mensah", status: "Present" },
    { student: "Abena Owusu", status: "Present" },
    { student: "Yaw Boadi", status: "Absent" },
    { student: "Adjoa Frimpong", status: "Late" },
  ],
  assessments: [
    { student: "Kojo Mensah", subject: "Mathematics", type: "Mid-term Exam", score: 78, max: 100, term: "Term 1" },
    { student: "Abena Owusu", subject: "Mathematics", type: "Mid-term Exam", score: 85, max: 100, term: "Term 1" },
    { student: "Yaw Boadi", subject: "English Language", type: "CA Test 2", score: 64, max: 100, term: "Term 1" },
  ],
  results: [
    { student: "Kojo Mensah", class: "JHS 1A", term: "Term 1", average: 78, position: "6th", grade: "B", status: "Published" },
    { student: "Abena Owusu", class: "JHS 1A", term: "Term 1", average: 85, position: "2nd", grade: "A", status: "Published" },
    { student: "Yaw Boadi", class: "JHS 1B", term: "Term 1", average: 64, position: "18th", grade: "C", status: "Pending Approval" },
  ],
  notices: [
    { title: "Mid-term Break Schedule", body: "School will close for mid-term break from Oct 10 to Oct 17.", role: "All", date: "2026-09-01" },
    { title: "PTA Meeting - Term 1", body: "Parent-Teacher meeting holds Saturday 10am in the main hall.", role: "Parent", date: "2026-08-28" },
    { title: "Science Fair Submissions", body: "Project proposals due by end of next week.", role: "Student", date: "2026-08-25" },
  ],
  auditLogs: [
    { user: "Grace Owusu", action: "Published Term 1 results for JHS 1A", time: "2026-09-04 10:22", ip: "197.251.4.12" },
    { user: "Super Admin", action: "Reset password for Kwame Asare", time: "2026-09-03 15:03", ip: "10.0.0.4" },
    { user: "Daniel Mensah", action: "Entered attendance for JHS 1A", time: "2026-09-05 08:01", ip: "197.251.4.30" },
    { user: "Unknown", action: "Failed login attempt (admin@riverside.edu)", time: "2026-09-05 07:40", ip: "185.23.4.9" },
  ],
  timetable: [
    { time: "8:00 - 8:45", mon: "Mathematics", tue: "English", wed: "Science", thu: "ICT", fri: "Social Studies" },
    { time: "8:45 - 9:30", mon: "English", tue: "Mathematics", wed: "French", thu: "Science", fri: "Mathematics" },
    { time: "9:30 - 10:15", mon: "Science", tue: "ICT", wed: "Mathematics", thu: "English", fri: "French" },
    { time: "10:15 - 10:30", mon: "Break", tue: "Break", wed: "Break", thu: "Break", fri: "Break" },
    { time: "10:30 - 11:15", mon: "Social Studies", tue: "Science", wed: "English", thu: "Mathematics", fri: "ICT" },
  ],
  assignments: [
    { title: "Algebra worksheet Ch.4", subject: "Mathematics", due: "2026-09-08", status: "Submitted" },
    { title: "Essay: My Community", subject: "English Language", due: "2026-09-10", status: "Pending" },
    { title: "Lab report - States of Matter", subject: "Integrated Science", due: "2026-09-06", status: "Overdue" },
  ],
  fees: [],
  reports: [],
  // School store/POS catalogue — inspired by boarding-school portals that let
  // students order uniforms, books, and stationery online.
  storeItems: [
    { id: 1, name: "School Uniform (Full Set)", category: "Uniform", price: 180, stock: 24 },
    { id: 2, name: "PE Kit", category: "Uniform", price: 90, stock: 40 },
    { id: 3, name: "Mathematics Textbook", category: "Books", price: 45, stock: 15 },
    { id: 4, name: "Integrated Science Textbook", category: "Books", price: 48, stock: 12 },
    { id: 5, name: "Exercise Books (Pack of 10)", category: "Stationery", price: 20, stock: 60 },
    { id: 6, name: "Geometry Set", category: "Stationery", price: 15, stock: 33 },
  ],
  studentOrders: [],
};

const API_READY = fetch(`${window.SMS_API_BASE || "http://127.0.0.1:5000/api"}/state`)
  .then(response => {
    if (!response.ok) throw new Error("Could not load data from the Flask API.");
    return response.json();
  })
  .then(state => Object.assign(DB, state));

async function apiRequest(path, options = {}){
  const response = await fetch(`${window.SMS_API_BASE || "http://127.0.0.1:5000/api"}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || "The API request failed.");
  return body;
}

// Adds a school fees document (invoice/statement) uploaded by an admin as a file,
// stored as a data URL so it can be re-downloaded by parents.
async function addFeeDocument(document){
  const doc = await apiRequest("/fees", { method: "POST", body: JSON.stringify(document) });
  DB.fees.push(doc);
  return doc;
}

function feesForClass(className){
  return DB.fees.filter(f => f.class === "All Classes" || f.class === className);
}

// Adds a student report (report card / progress report) uploaded by an admin as a
// file for a specific student, stored as a data URL for parents to download.
async function addReportDocument(document){
  const doc = await apiRequest("/reports", { method: "POST", body: JSON.stringify(document) });
  DB.reports.push(doc);
  return doc;
}

function reportsForStudent(studentName){
  return DB.reports.filter(r => r.student === studentName);
}

// Places a school-store order for a student: validates stock, decrements it,
// and records the order for the student's order history.
async function placeStoreOrder(studentName, cart){
  const order = await apiRequest("/orders", { method: "POST", body: JSON.stringify({ student: studentName, cart }) });
  const orderedIds = new Set(order.items.map(item => item.id));
  DB.storeItems.forEach(item => {
    if (orderedIds.has(item.id)) item.stock -= order.items.find(entry => entry.id === item.id).qty;
  });
  DB.studentOrders.push(order);
  return order;
}

function ordersForStudent(studentName){
  return DB.studentOrders.filter(o => o.student === studentName);
}

// Adds a student to the shared DB and persists it, so it survives reloads
// and shows up for admins as well as the teacher who added it.
async function addStudent(studentData){
  const student = await apiRequest("/students", { method: "POST", body: JSON.stringify(studentData) });
  DB.students.push(student);
  return student;
}

async function saveAttendance(entries){
  const saved = await apiRequest("/attendance", { method: "POST", body: JSON.stringify(entries) });
  DB.attendanceToday = saved;
  return saved;
}

async function addAssessment(assessment){
  const saved = await apiRequest("/assessments", { method: "POST", body: JSON.stringify(assessment) });
  DB.assessments.push(saved);
  return saved;
}

async function addNotice(notice){
  const saved = await apiRequest("/notices", { method: "POST", body: JSON.stringify(notice) });
  DB.notices.push(saved);
  return saved;
}

async function addSubject(subject){
  DB.subjects = await apiRequest("/subjects", { method: "POST", body: JSON.stringify({ subject }) });
  return DB.subjects;
}

function initials(name){
  return name.split(" ").map(p=>p[0]).slice(0,2).join("").toUpperCase();
}

function badgeFor(status){
  const map = {
    Active:"green", Present:"green", Published:"green", Submitted:"green",
    Suspended:"red", Absent:"red", Overdue:"red",
    Probation:"yellow", Late:"yellow", "Pending Approval":"yellow", Pending:"yellow",
  };
  return map[status] || "grey";
}

// Access-scoping helpers — enforce "who can see whose records" in the UI layer.
// Teachers only ever see students in the classes they are assigned to.
function classesForTeacher(teacherName){
  const t = DB.teachers.find(t => t.name === teacherName);
  return t ? t.classes : [];
}

function studentsForTeacher(teacherName){
  const classes = classesForTeacher(teacherName);
  return DB.students.filter(s => classes.includes(s.class));
}
