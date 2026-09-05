import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { hrmsAccessState, hrmsHome } from './access';
import { HrmsProvider } from './HrmsContext';

/** Shown while the profile (and with it the module flags) is still arriving. */
const Resolving = () => (
  <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">
    Loading…
  </div>
);

/**
 * Single dynamic entry point for /hrms.
 * Users with no HRMS access are bounced back to the main app; everyone else lands on the
 * module home. Mirrors TpmsGate.jsx.
 *
 * Phase 1 has one shell, so `hrmsHome()` is constant. Later phases route by role here
 * (recruitment workspace vs. employee self-service) without touching App.jsx.
 */
export const HrmsGate = () => {
  const { user } = useAuth();
  const state = hrmsAccessState(user);
  if (state === 'unknown') return <Resolving />;
  if (state === 'denied') return <Navigate to="/" replace />;
  return <Navigate to={hrmsHome(user)} replace />;
};

/**
 * Route guard for the HRMS panels.
 *
 * Two layers, deliberately:
 *   1. `hrmsAccessState` — a synchronous check on the company toggle, so a user without
 *      access never mounts the module or fires its requests.
 *   2. `HrmsProvider` — fetches the server's authoritative capability list for everything
 *      inside. Feature-level gating uses `useHrms().can(...)`, never a raw role check.
 *
 * The 'unknown' branch matters: AuthProvider seeds `user` from the JWT and merges the full
 * profile asynchronously, and the module flags live only on the profile. Redirecting on a
 * merely-absent flag would eject an entitled user from HRMS on every hard refresh or deep
 * link. We wait for the answer instead of guessing at it. (See hrmsAccessState.)
 *
 * The backend enforces the same rules independently (routes/hrms.py router guard +
 * utils/hrms_access.py), so this is a UX affordance, not the security boundary.
 */
export const RequireHrms = ({ children }) => {
  const { user } = useAuth();
  const state = hrmsAccessState(user);

  if (state === 'unknown') return <Resolving />;
  if (state === 'denied') return <Navigate to="/" replace />;

  return <HrmsProvider>{children}</HrmsProvider>;
};

export default HrmsGate;
