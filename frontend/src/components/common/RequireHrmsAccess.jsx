import React from 'react';
import { ShieldAlert } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import {
  canAccessHrms, hasHrmsPermission,
  HRMS_ACCESS_DENIED_MESSAGE, HRMS_PERMISSION_DENIED_MESSAGE,
} from '../../utils/hrmsAccess';

// Route guard for the HRMS. Anyone without the module who reaches an /hrms URL directly gets a
// denial panel instead of the page (the backend also 403s every HRMS API, so this is the UX
// layer of a defense-in-depth gate).
//
// Two distinct walls, because they mean different things to the person hitting them:
//   * no module   — a client-side user; the HRMS is internal-only and never will be theirs.
//   * no grant    — internal staff without the section's permission; an admin can grant it.
// Pass `module`/`action` to require a specific permission on top of module access.
const RequireHrmsAccess = ({ children, module, action = 'read' }) => {
  const { user } = useAuth();

  const hasModule = canAccessHrms(user);
  const hasGrant = !module || hasHrmsPermission(user, module, action);

  if (hasModule && hasGrant) return children;

  const deniedByPermission = hasModule && !hasGrant;

  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-16 h-16 rounded-2xl bg-[var(--accent-red-bg)] flex items-center justify-center text-[var(--accent-red)] mb-4">
        <ShieldAlert size={30} />
      </div>
      <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight mb-1">
        {deniedByPermission ? 'Permission Required' : 'Access Denied'}
      </h1>
      <p className="text-[13px] font-bold text-[var(--text-muted)] max-w-md">
        {deniedByPermission ? HRMS_PERMISSION_DENIED_MESSAGE : HRMS_ACCESS_DENIED_MESSAGE}
      </p>
      <a
        href="/"
        className="mt-6 px-5 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest hover:opacity-90 transition-all"
      >
        Back to Dashboard
      </a>
    </div>
  );
};

export default RequireHrmsAccess;
