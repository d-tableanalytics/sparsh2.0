// Mirrors the backend gate (auth_controller.has_hrms_access): the HRMS manages Sparsh's OWN
// workforce, so it is internal-staff-only. Unlike Task & Delegation there is no per-company
// toggle and no client-side path in at all — a clientadmin/clientuser never sees it, by design,
// so employee records, payroll and KYC stay inside Sparsh.
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
  if (isClientSideUser(user)) return false;
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
