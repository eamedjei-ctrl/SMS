// Mock data layer for the School Management System UI prototype.
// In a real system this would be replaced by API calls to the backend described
// in the specification (Node/Python API + PostgreSQL/MySQL).

const DB = {
  schools: [
    { id: 1, name: "Greenfield High School", address: "12 Lake Road, Accra", status: "Active", students: 842, staff: 61 },
    { id: 2, name: "Riverside Academy", address: "9 Palm Street, Kumasi", status: "Active", staff: 34, students: 410 },
    { id: 3, name: "Northgate College", address: "4 Hilltop Ave, Tamale", status: "Suspended", staff: 20, students: 190 },
  ],
  admins: [
    { id: 1, name: "Grace Owusu", email: "g.owusu@greenfield.edu", school: "Greenfield High School", status: "Active" },
    { id: 2, name: "Kwame Asare", email: "k.asare@riverside.edu", school: "Riverside Academy", status: "Active" },
    { id: 3, name: "Linda Boateng", email: "l.boateng@northgate.edu", school: "Northgate College", status: "Suspended" },
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
};

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
