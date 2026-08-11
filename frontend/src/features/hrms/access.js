// HRMS ▸ client-side access rules.
//
// MUST stay in lockstep with backend/app/utils/hrms_access.py. Where the two disagree the
// server wins — that is exactly the failure the source HRMS shipped, "rendering actions
// unconditionally that the API will 403 for" (FRONTEND_ANALYSIS §5). To make divergence
// structurally unlikely, the authoritative capability list is not re-derived here: it is
// fetched from GET /hrms/health and cached on the user (see HrmsGate). The helpers below
// exist only for the pre-fetch decisions the shell has to make synchronously — sidebar
// visibility and route guarding.
//
// HRMS is a CLIENT-COMPANY module (like TPMS): a client's HR team hires and pays their own
// staff. Sparsh internal staff get cross-company admin/support visibility. Opt-in per
// company — an absent `hrms_enabled` flag means OFF.

const INTERNAL_OWNER_ROLES = new Set(['superadmin']);
const INTERNAL_STAFF_ROLES = new Set(['admin', 'coach', 'staff']);
const CLIENT_ROLES = new Set(['clientadmin', 'clientuser']);

// Mirrors models/hrms.py HrmsRole.
export const HRMS_ROLE = {
  ADMIN: 'admin',
  INTERNAL: 'internal',
  MD: 'md',
  HR: 'hr',
  MANAGER: 'manager',
  EMPLOYEE: 'employee',
};

// Mirrors models/hrms.py Cap. Grows one phase at a time, alongside the backend.
export const CAP = {
  MODULE_ACCESS: 'module.access',
  MODULE_ADMIN: 'module.admin',
  AUDIT_READ: 'audit.read',

  // Phase 2
  EMPLOYEE_READ: 'employee.read',
  EMPLOYEE_WRITE: 'employee.write',
  EMPLOYEE_SALARY_READ: 'employee.salary.read',
  EMPLOYEE_SALARY_WRITE: 'employee.salary.write',
  DEPARTMENT_READ: 'department.read',
  DEPARTMENT_WRITE: 'department.write',
  DESIGNATION_READ: 'designation.read',
  DESIGNATION_WRITE: 'designation.write',

  // Phase 3
  REQUISITION_READ: 'requisition.read',
  REQUISITION_CREATE: 'requisition.create',
  REQUISITION_WRITE: 'requisition.write',
  REQUISITION_REVIEW_HR: 'requisition.review_hr',
  REQUISITION_APPROVE_MD: 'requisition.approve_md',
  REQUISITION_CLOSE: 'requisition.close',
  JD_READ: 'jd.read',
  JD_WRITE: 'jd.write',

  // Phase 4
  POSTING_READ: 'posting.read',
  POSTING_WRITE: 'posting.write',

  // Phase 5
  CANDIDATE_READ: 'candidate.read',
  CANDIDATE_WRITE: 'candidate.write',
  CANDIDATE_SCREEN: 'candidate.screen',

  // Phase 6
  ASSESSMENT_READ: 'assessment.read',
  ASSESSMENT_SEND: 'assessment.send',
  ASSESSMENT_REVIEW: 'assessment.review',

  // Phase 7
  INTERVIEW_READ: 'interview.read',
  INTERVIEW_SCHEDULE: 'interview.schedule',
  INTERVIEW_EVALUATE: 'interview.evaluate',
  INTERVIEW_DECIDE_MD: 'interview.decide_md',

  // Phase 8
  OFFER_READ: 'offer.read',
  OFFER_WRITE: 'offer.write',
  OFFER_SEND: 'offer.send',

  // Phase 9
  ONBOARDING_READ: 'onboarding.read',
  ONBOARDING_WRITE: 'onboarding.write',
  // Separate from write on purpose: this is the irreversible step that creates an employee.
  ONBOARDING_GENERATE_ID: 'onboarding.generate_id',

  // Phase 10 — read-only analytics
  ANALYTICS_READ: 'analytics.read',
  REPORT_READ: 'report.read',
  // Separate from read on purpose: reading figures on screen and taking a file of personal
  // data off the system are different acts. A hiring manager has read, not export.
  REPORT_EXPORT: 'report.export',

  // Phase 11-R — recruitment review enhancements
  // Item 1: the public-link registry.
  LINK_READ: 'link.read',
  // Separate from read on purpose: revoking kills a live credential a candidate is holding.
  LINK_MANAGE: 'link.manage',

  // Item 2: documentation.
  DOCUMENT_READ: 'document.read',
  DOCUMENT_WRITE: 'document.write',
  // Separate from write on purpose: collecting paperwork and ATTESTING to it are different
  // acts. Sparsh support staff hold write and deliberately not verify.
  DOCUMENT_VERIFY: 'document.verify',

  // Item 3: appointment letters. Mirrors the offer capabilities exactly.
  APPOINTMENT_READ: 'appointment.read',
  APPOINTMENT_WRITE: 'appointment.write',
  // Separate from write: issuing the letter commits the company to employing somebody.
  APPOINTMENT_SEND: 'appointment.send',

  // Item 4: the client master (recruitment-agency model — a client is NOT a tenant).
  CLIENT_READ: 'client.read',
  CLIENT_WRITE: 'client.write',

  // Item 7: sanctioned strength + the over-sanction escalation ladder.
  SANCTION_READ: 'sanction.read',
  SANCTION_WRITE: 'sanction.write',
  REQUISITION_ESCALATE: 'requisition.escalate',
};

/** Sparsh internal user rather than a client-side one. Same precedence the backend uses
 *  (source collection → tag → role), so the two never disagree. */
export const isInternalUser = (user) => {
  if (!user) return false;
  if (user.tag === 'staff') return true;
  if (user.tag === 'learner') return false;
  const role = (user.role || '').toLowerCase();
  return INTERNAL_OWNER_ROLES.has(role) || INTERNAL_STAFF_ROLES.has(role);
};

export const isClientSideUser = (user) => !!user && !isInternalUser(user);

/** Resolve an ERP user to their HRMS role. Mirrors hrms_access.hrms_role exactly. */
export const hrmsRole = (user) => {
  if (!user) return null;
  const role = (user.role || '').trim().toLowerCase();

  if (isInternalUser(user)) {
    return INTERNAL_OWNER_ROLES.has(role) ? HRMS_ROLE.ADMIN : HRMS_ROLE.INTERNAL;
  }
  if (role === 'clientadmin') return HRMS_ROLE.MD;
  if (CLIENT_ROLES.has(role)) {
    const governance = (user.governance_role || '').trim().toUpperCase();
    if (governance === 'MD') return HRMS_ROLE.MD;
    if (governance === 'HR') return HRMS_ROLE.HR;
    if (governance === 'HOD') return HRMS_ROLE.MANAGER;
    return HRMS_ROLE.EMPLOYEE;
  }
  return null;
};

/** Can this user open HRMS at all?
 *  Internal staff always (they administer across clients); client-side users only while
 *  their company's HRMS toggle is ON. An absent flag means OFF — the module is opt-in,
 *  so a company stays dark until explicitly enabled.
 *
 *  Use this for SIDEBAR visibility, where failing closed is correct: a nav item that
 *  appears and then vanishes is worse than one that appears a moment late. For ROUTE
 *  guarding use hrmsAccessState() instead — see the note there. */
export const canAccessHrms = (user) => {
  if (!user) return false;
  if (isInternalUser(user)) return true;
  return user.hrms_enabled === true;
};

/** Tri-state access, for ROUTE guarding: 'allowed' | 'denied' | 'unknown'.
 *
 *  Why this exists. AuthProvider sets `user` from the JWT immediately and then merges the
 *  full profile from /users/me in the BACKGROUND. The module flags (`hrms_enabled`) live
 *  only on the profile, not in the token — so for the first moments after a hard refresh
 *  or a deep link, a perfectly entitled client user has `hrms_enabled === undefined`.
 *
 *  A boolean guard reads that as "denied" and redirects them out of the module before the
 *  profile ever arrives, i.e. the module appears broken on every refresh. Distinguishing
 *  "not allowed" (flag is explicitly false) from "not known yet" (flag absent) lets the
 *  route guard WAIT instead of bouncing.
 *
 *  Internal users are decided from the token alone, so they are never 'unknown'. */
export const hrmsAccessState = (user) => {
  if (!user) return 'denied';
  if (isInternalUser(user)) return 'allowed';
  if (user.hrms_enabled === true) return 'allowed';
  if (user.hrms_enabled === false) return 'denied';
  return 'unknown';
};

/** Does this user administer HRMS configuration? Used for the settings surfaces (Phase 11).
 *  Deliberately NOT a raw role check anywhere else — feature gating uses `hasCap`. */
export const isHrmsAdmin = (user) => {
  const role = hrmsRole(user);
  return role === HRMS_ROLE.ADMIN || role === HRMS_ROLE.INTERNAL || role === HRMS_ROLE.MD;
};

/** Only Admin / Super Admin may switch the module on or off for a company.
 *  Matches routes/company.py update_company_hrms_access. */
export const canToggleHrms = (user) =>
  ['superadmin', 'admin'].includes((user?.role || '').toLowerCase());

/** THE capability check. `caps` comes from GET /hrms/health — the server's own answer —
 *  so the UI shows exactly what the API will allow. Falls back to false when the health
 *  payload has not loaded, which fails CLOSED rather than flashing forbidden controls. */
export const hasCap = (caps, capability) =>
  Array.isArray(caps) && caps.includes(capability);

/** Landing route for a user entering /hrms. Phase 1 has a single shell; later phases
 *  route by role here (recruitment vs. self-service), mirroring tpmsHome(). */
export const hrmsHome = () => '/hrms';

export const HRMS_DISABLED_MESSAGE =
  'The HRMS module is not enabled for your company. Please contact your administrator.';
