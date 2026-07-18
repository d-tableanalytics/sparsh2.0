import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { canAccessTpms, isTpmsAdmin, tpmsHome } from './access';

/**
 * Single dynamic entry point for /tpms.
 * Auto-routes the user to the correct panel based on role:
 *   superadmin/admin → /tpms/admin,  everyone else (internal) → /tpms/smops.
 * Non-internal users are bounced back to the main app.
 */
export const TpmsGate = () => {
  const { user } = useAuth();
  if (!canAccessTpms(user)) return <Navigate to="/" replace />;
  return <Navigate to={tpmsHome(user)} replace />;
};

/**
 * Route guard for the TPMS panels.
 *  - Blocks non-internal users entirely (→ main app).
 *  - `admin` panels additionally require superadmin/admin; a default SMOPS user
 *    who reaches an /tpms/admin URL is redirected to their own panel.
 */
export const RequireTpms = ({ admin = false, children }) => {
  const { user } = useAuth();
  if (!canAccessTpms(user)) return <Navigate to="/" replace />;
  if (admin && !isTpmsAdmin(user)) return <Navigate to="/tpms/smops" replace />;
  return children;
};

export default TpmsGate;
