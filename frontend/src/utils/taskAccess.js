// Task Management is internal-Sparsh-only. This mirrors the backend gate
// (auth_controller.is_internal_user): internal = staff-collection users (tag "staff",
// roles superadmin/admin and any future staff-side role); client-side users
// (clientadmin/clientuser, tag "learner") are blocked unless explicitly granted the
// permissions.tasks.access_task_management override. Super Admin is always allowed.
const INTERNAL_ROLES = new Set(['superadmin', 'admin', 'coach', 'staff']);

export const canAccessTaskManagement = (user) => {
  if (!user) return false;
  if (user.role === 'superadmin') return true;
  if (user.permissions?.tasks?.access_task_management) return true; // explicit client override
  if (user.tag === 'staff') return true;
  if (user.tag === 'learner') return false;
  return INTERNAL_ROLES.has(user.role);
};

// Managing task settings (categories/tags/holidays) additionally requires an internal admin.
const MANAGE_ROLES = new Set(['superadmin', 'admin', 'coach', 'staff']);
export const canManageTaskSettings = (user) =>
  canAccessTaskManagement(user) && (user?.role === 'superadmin' || MANAGE_ROLES.has(user?.role));

export const TASK_ACCESS_DENIED_MESSAGE = 'Task Management is only available for Sparsh internal teams.';
