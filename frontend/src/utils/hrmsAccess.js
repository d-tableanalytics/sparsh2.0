// Mirrors the backend gate (auth_controller.has_hrms_access): internal Sparsh staff always have
// the HRMS; a client company user gets it only while their company's HRMS toggle is ON
// (`hrms_enabled`, surfaced on the user via /users/me) — the same opt-in per-company pattern as
// Task & Delegation. Defaults OFF, so a client never sees it until a Sparsh admin enables it.
const INTERNAL_ROLES = new Set(['superadmin', 'admin', 'coach', 'staff']);
const CLIENT_ROLES = new Set(['clientadmin', 'clientuser']);

export const isClientSideUser = (user) => {
  if (!user) return false;
  if (user.tag === 'staff') return false;
  if (user.tag === 'learner') return true;
  return CLIENT_ROLES.has(user.role);
};

export const canAccessHrms = (user) => {
  if (!user) return false;
  if (user.role === 'superadmin') return true;
  if (isClientSideUser(user)) return user.hrms_enabled === true;
  if (user.tag === 'staff') return true;
  return INTERNAL_ROLES.has(user.role);
};

// Fine-grained check WITHIN the HRMS, layered on canAccessHrms. Mirrors
// auth_controller.has_hrms_permission — module is hrms | recruitment | attendance | payroll.
// The backend enforces this too; this is the UX layer of the same gate.
export const hasHrmsPermission = (user, module, action) => {
  if (!user) return false;
  if (user.role === 'superadmin') return true;
  return !!user.permissions?.[module]?.[action];
};

// Convenience predicates for nav/section visibility.
export const canManageEmployees = (user) => hasHrmsPermission(user, 'hrms', 'read');
export const canUseRecruitment = (user) => hasHrmsPermission(user, 'recruitment', 'read');
export const canManageAttendance = (user) => hasHrmsPermission(user, 'attendance', 'read');
export const canRunPayroll = (user) => hasHrmsPermission(user, 'payroll', 'read');

export const HRMS_ACCESS_DENIED_MESSAGE = 'The HRMS is only available to Sparsh internal staff.';

// A staff user who has the module but no grant inside it needs different copy — the module is
// not the problem, the permission is.
export const HRMS_PERMISSION_DENIED_MESSAGE =
  'You do not have permission for this HRMS section. Please contact your administrator.';
