// Shared shell: configuration, API client, auth guard, sidebar nav, topbar.

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
// The API is multi-tenant: every request must say which school it is for. In
// production that comes from the subdomain the app is served on; locally it is
// set here or with ?school=<subdomain> on the login page.
const API_BASE = window.SMS_API_BASE || "http://127.0.0.1:5000/api/v1";
const DEFAULT_SUBDOMAIN = window.SMS_SCHOOL_SUBDOMAIN || "demo";

const SESSION_KEY = "sms_session";
const SCHOOL_KEY = "sms_school";

// The portal names in this UI predate the API's role keys. One map, one place.
const ROLE_TO_API = {
  superadmin: "platform_admin",
  admin: "school_admin",
  teacher: "teacher",
  student: "student",
  parent: "guardian",
};

const API_TO_ROLE = {
  platform_admin: "superadmin",
  platform_support: "superadmin",
  school_admin: "admin",
  head_teacher: "admin",
  teacher: "teacher",
  student: "student",
  guardian: "parent",
};

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

const LOGIN_PAGE = {
  superadmin: "superadmin-login.html",
  admin: "admin-login.html",
  teacher: "teacher-login.html",
  student: "student-login.html",
  parent: "parent-login.html",
};

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------
function getSession(){
  try { return JSON.parse(sessionStorage.getItem(SESSION_KEY)); } catch(e){ return null; }
}

function setSession(session){
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

function clearSession(){
  sessionStorage.removeItem(SESSION_KEY);
}

function getSchoolSubdomain(){
  const fromQuery = new URLSearchParams(window.location.search).get("school");
  if (fromQuery) {
    localStorage.setItem(SCHOOL_KEY, fromQuery);
    return fromQuery;
  }
  return getSession()?.school_subdomain
    || localStorage.getItem(SCHOOL_KEY)
    || DEFAULT_SUBDOMAIN;
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------
// The API answers with an envelope: {success, data, meta} or {success, error}.
// Callers get `data`; failures throw an Error carrying the machine-readable
// `code` so pages can branch on the code and never on the message text.
class ApiError extends Error {
  constructor(code, message, details, status){
    super(message);
    this.code = code;
    this.details = details || {};
    this.status = status;
  }
}

async function rawRequest(path, options = {}, token){
  const headers = {
    "Content-Type": "application/json",
    "X-School-Subdomain": getSchoolSubdomain(),
    ...(options.headers || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const body = await response.json().catch(() => ({}));

  if (!response.ok) {
    const error = body.error || {};
    throw new ApiError(
      error.code || "INTERNAL_ERROR",
      error.message || "The request could not be completed.",
      error.details,
      response.status
    );
  }
  return body;
}

async function refreshAccessToken(){
  const session = getSession();
  if (!session?.refresh_token) return null;
  try {
    const body = await rawRequest("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: session.refresh_token }),
    });
    const next = { ...session, ...sessionFromPayload(body.data, session.role) };
    setSession(next);
    return next.access_token;
  } catch (e) {
    return null;
  }
}

// Every call goes through here: one retry on an expired access token, then out.
async function apiRequest(path, options = {}){
  const session = getSession();
  try {
    const body = await rawRequest(path, options, session?.access_token);
    return body.data;
  } catch (error) {
    const expired = error.code === "TOKEN_EXPIRED"
      || (error.status === 401 && session?.refresh_token);
    if (!expired) throw error;

    const token = await refreshAccessToken();
    if (!token) {
      clearSession();
      window.location.href = LOGIN_PAGE[session?.role] || "index.html";
      throw error;
    }
    const body = await rawRequest(path, options, token);
    return body.data;
  }
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
function sessionFromPayload(data, uiRole){
  const apiRoles = data.user?.roles || data.roles || [];
  return {
    role: uiRole || API_TO_ROLE[apiRoles[0]] || "admin",
    api_roles: apiRoles,
    name: data.user?.full_name || "",
    email: data.user?.email || "",
    access_token: data.access_token,
    refresh_token: data.refresh_token || null,
    permissions: data.permissions || [],
    must_change_password: !!data.must_change_password,
    school_subdomain: getSchoolSubdomain(),
  };
}

async function loginWithApi(role, identifier, password){
  // Platform staff authenticate against the platform tier, not a tenant.
  const isPlatform = role === "superadmin";
  const path = isPlatform ? "/platform/auth/login" : "/auth/login";
  const payload = isPlatform
    ? { email: identifier, password }
    : { identifier, password, subdomain: getSchoolSubdomain() };

  const body = await rawRequest(path, { method: "POST", body: JSON.stringify(payload) });
  const session = sessionFromPayload(body.data, role);

  // The account must actually hold the role whose portal was used.
  const expected = ROLE_TO_API[role];
  if (!isPlatform && expected && !session.api_roles.includes(expected)) {
    const allowed = session.api_roles.map(r => ROLE_LABELS[API_TO_ROLE[r]] || r).join(", ");
    throw new ApiError(
      "PERMISSION_DENIED",
      `This account does not have access to the ${ROLE_LABELS[role]} portal.`
        + (allowed ? ` It is a ${allowed} account.` : ""),
      {},
      403
    );
  }

  setSession(session);
  if (!isPlatform) localStorage.setItem(SCHOOL_KEY, session.school_subdomain);
  return session;
}

function requireAuth(expectedRole){
  const session = getSession();
  if (!session || !session.access_token || (expectedRole && session.role !== expectedRole)) {
    window.location.href = LOGIN_PAGE[expectedRole] || "index.html";
    return null;
  }
  return session;
}

async function logout(){
  const session = getSession();
  if (session?.access_token && session.role !== "superadmin") {
    try {
      await rawRequest("/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: session.refresh_token }),
      }, session.access_token);
    } catch (e) { /* signing out locally matters more than the server ack */ }
  }
  clearSession();
  window.location.href = LOGIN_PAGE[session?.role] || "index.html";
}

// Permission-aware rendering. This is user experience, not security -- the API
// enforces regardless -- but a button that always 403s is bad product.
function can(permission){
  return (getSession()?.permissions || []).includes(permission);
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------
function renderShell({ role, active, title, sub }){
  const session = requireAuth(role);
  if (!session) return null;

  const items = NAV[role].map(item => `
    <a href="${item.href}" class="${item.href === active ? "active" : ""}">
      <span class="icon">${item.icon}</span><span>${item.label}</span>
    </a>`).join("");

  document.getElementById("sidebar").innerHTML = `
    <div class="brand"><span class="dot"></span> <span id="brand-name">SchoolOS</span></div>
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

  // The school's own name replaces the placeholder once the session resolves.
  if (role !== "superadmin") {
    apiRequest("/auth/me")
      .then(data => {
        if (data.school?.name) document.getElementById("brand-name").textContent = data.school.name;
      })
      .catch(() => { /* the shell stays usable without branding */ });
  }

  return session;
}

function el(html){
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstChild;
}
