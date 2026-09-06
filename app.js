// Shared shell: sidebar nav, topbar, auth guard. Uses sessionStorage for the demo "session".

const NAV = {
  superadmin: [
    { href:"superadmin.html", icon:"◆", label:"Overview" },
    { href:"superadmin-schools.html", icon:"🏫", label:"Schools" },
    { href:"superadmin-users.html", icon:"👤", label:"Admins & Users" },
    { href:"superadmin-logs.html", icon:"🛡", label:"Audit Logs" },
    { href:"superadmin-settings.html", icon:"⚙", label:"Settings & Backups" },
  ],
  admin: [
    { href:"admin.html", icon:"◆", label:"Overview" },
    { href:"admin-students.html", icon:"🎓", label:"Students" },
    { href:"admin-teachers.html", icon:"🧑‍🏫", label:"Teachers" },
    { href:"admin-classes.html", icon:"🏷", label:"Classes & Subjects" },
    { href:"admin-results.html", icon:"📊", label:"Results" },
    { href:"admin-fees.html", icon:"💳", label:"School Fees" },
    { href:"admin-reports.html", icon:"📄", label:"Student Reports" },
    { href:"admin-notices.html", icon:"📣", label:"Notices" },
  ],
  teacher: [
    { href:"teacher.html", icon:"◆", label:"Overview" },
    { href:"teacher-attendance.html", icon:"🗓", label:"Attendance" },
    { href:"teacher-marks.html", icon:"✏️", label:"Marks Entry" },
    { href:"teacher-assignments.html", icon:"📚", label:"Assignments" },
    { href:"teacher-students.html", icon:"🎓", label:"My Students" },
  ],
  student: [
    { href:"student.html", icon:"◆", label:"Overview" },
    { href:"student-results.html", icon:"📊", label:"Results" },
    { href:"student-timetable.html", icon:"🗓", label:"Timetable" },
    { href:"student-assignments.html", icon:"📚", label:"Assignments" },
    { href:"student-fees.html", icon:"💳", label:"School Fees" },
    { href:"student-reports.html", icon:"📄", label:"Report Cards" },
    { href:"student-store.html", icon:"🛒", label:"School Store" },
    { href:"student-notices.html", icon:"📣", label:"Notices" },
  ],
  parent: [
    { href:"parent.html", icon:"◆", label:"Overview" },
    { href:"parent-results.html", icon:"📊", label:"Ward Results" },
    { href:"parent-attendance.html", icon:"🗓", label:"Ward Attendance" },
    { href:"parent-timetable.html", icon:"🕘", label:"Ward Timetable" },
    { href:"parent-assignments.html", icon:"📚", label:"Ward Assignments" },
    { href:"parent-fees.html", icon:"💳", label:"School Fees" },
    { href:"parent-reports.html", icon:"📄", label:"Student Reports" },
    { href:"parent-notices.html", icon:"📣", label:"Notices & Messages" },
  ],
};

const ROLE_LABELS = {
  superadmin: "Super Admin",
  admin: "School Admin",
  teacher: "Teacher",
  student: "Student",
  parent: "Parent",
};

function getSession(){
  try { return JSON.parse(sessionStorage.getItem("sms_session")); } catch(e){ return null; }
}

const LOGIN_PAGE = {
  superadmin: "superadmin-login.html",
  admin: "admin-login.html",
  teacher: "teacher-login.html",
  student: "student-login.html",
  parent: "parent-login.html",
};

function requireAuth(expectedRole){
  const s = getSession();
  if (!s || (expectedRole && s.role !== expectedRole)) {
    window.location.href = LOGIN_PAGE[expectedRole] || "index.html";
    return null;
  }
  return s;
}

function logout(){
  const session = getSession();
  sessionStorage.removeItem("sms_session");
  window.location.href = LOGIN_PAGE[session?.role] || "index.html";
}

function renderShell({ role, active, title, sub }){
  const session = requireAuth(role);
  if (!session) return null;

  const items = NAV[role].map(item => `
    <a href="${item.href}" class="${item.href === active ? "active" : ""}">
      <span class="icon">${item.icon}</span><span>${item.label}</span>
    </a>`).join("");

  document.getElementById("sidebar").innerHTML = `
    <div class="brand"><span class="dot"></span> Greenfield SMS</div>
    <nav>${items}</nav>
    <div class="userbox">
      <div class="name">${session.name}</div>
      <div class="role">${ROLE_LABELS[role]}</div>
      <button class="btn ghost small block" onclick="logout()">Sign out</button>
    </div>
  `;

  document.getElementById("topbar-title").textContent = title;
  document.getElementById("topbar-sub").textContent = sub || "";

  document.getElementById("menu-btn")?.addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("open");
  });

  return session;
}

function el(html){
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstChild;
}
