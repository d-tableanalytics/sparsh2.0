import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { getHrmsHealth, getHrmsCompanies } from '../../services/hrmsApi';
import { hasCap, canAccessHrms } from './access';

/**
 * HRMS ▸ module context.
 *
 * Fetches GET /hrms/health once when the module mounts and holds the caller's RESOLVED
 * role + capability list for the whole subtree.
 *
 * Why the capabilities come from the server rather than being computed here: the source
 * HRMS derived permissions independently on each side and consequently rendered buttons
 * the API then refused with a 403 (FRONTEND_ANALYSIS §5, §14.4 — "derive button visibility
 * from the same rules the server enforces"). Asking the server once and gating on its
 * answer makes that class of drift impossible.
 *
 * Fails CLOSED: while loading, and on any error, `can()` returns false. A user briefly
 * sees fewer controls rather than controls that do not work.
 */
const HrmsContext = createContext(null);

export const HrmsProvider = ({ children }) => {
  const { user } = useAuth();
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Company scope. Client-side users are pinned by the server and this simply mirrors it;
  // internal staff pick one, because every employee endpoint needs a company.
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState(null);

  const load = useCallback(async () => {
    if (!canAccessHrms(user)) {
      setHealth(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getHrmsHealth();
      setHealth(data);
      try {
        const { data: list } = await getHrmsCompanies();
        const rows = list?.companies || [];
        setCompanies(rows);
        // Pin to the server's answer for a client user; otherwise default internal staff to
        // the first company so the module is never in a blank, unusable state.
        setCompanyId((prev) => data.company_id || prev || rows[0]?.id || null);
      } catch {
        setCompanies([]);
        setCompanyId(data.company_id || null);
      }
    } catch (err) {
      // A 403 here means the company toggle was switched off mid-session. The route guard
      // handles the redirect; we just make sure nothing renders as permitted.
      setHealth(null);
      setError(err?.response?.data?.detail || 'Could not load the HRMS module.');
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { load(); }, [load]);

  const value = {
    loading,
    error,
    role: health?.role || null,
    capabilities: health?.capabilities || [],
    isInternal: !!health?.is_internal,
    /** THE capability check for every HRMS component. */
    can: (capability) => hasCap(health?.capabilities, capability),
    reload: load,

    // Company scope
    companyId,
    companies,
    // Client users cannot switch scope — the server pins them regardless, so the UI must
    // not pretend otherwise.
    setCompanyId: health?.is_internal ? setCompanyId : () => {},
    canSwitchCompany: !!health?.is_internal && companies.length > 1,
    /** Query params for every scoped HRMS call. */
    scope: companyId ? { company_id: companyId } : {},

    // ── Client scope ──
    // The SERVER's answer, resolved from the engagement records and returned by
    // /hrms/health. The frontend renders from it and never derives it.
    //
    // What this is NOT: a security control. A `client_id` sent on any later request is a
    // FILTER, reconciled server-side against this same scope (hrms_access.assert_client_
    // allowed). Hiding a selector prevents a mistake; it does not prevent an attack.
    isClientUser: !!health?.is_client_user,
    /** null  -> not client-scoped (a Sparsh user); no client narrowing applies.
     *  []    -> client-scoped with no valid membership; everything must show nothing.
     *  [..]  -> the clients this user may work on.
     *  Undefined while loading, which every consumer must treat as "not yet known"
     *  rather than as "unrestricted" — the same fail-closed rule `can()` follows. */
    allowedClientIds: health?.allowed_client_ids ?? null,
    /** The single client a client-scoped user is pinned to, or null.
     *  With exactly one membership there is nothing to choose, so the UI shows a label
     *  rather than a selector. With several, a later phase adds a picker bounded BY THIS
     *  LIST — never by an arbitrary value. */
    clientScope: (health?.is_client_user && (health?.allowed_client_ids || []).length === 1)
      ? health.allowed_client_ids[0]
      : null,
  };

  return <HrmsContext.Provider value={value}>{children}</HrmsContext.Provider>;
};

// Provider + hook deliberately live together (same pattern as context/AuthContext.jsx),
// so the fast-refresh rule is waived here rather than splitting a 3-line hook into its
// own module.
// eslint-disable-next-line react-refresh/only-export-components
export const useHrms = () => {
  const ctx = useContext(HrmsContext);
  if (!ctx) {
    throw new Error('useHrms must be used inside an <HrmsProvider> (see HrmsGate.jsx)');
  }
  return ctx;
};

export default HrmsContext;
