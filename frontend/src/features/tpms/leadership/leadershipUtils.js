import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../../../services/api';
import { useAuth } from '../../../context/AuthContext';

/* Shared helpers for the Leadership Score screens. Plain .js (no JSX) so the
   react-refresh lint rule stays happy about the .jsx pages exporting only components. */

export const STAFF_ROLES = ['superadmin', 'admin'];
export const CLIENT_ROLES = ['clientadmin', 'clientuser'];

export const isStaff = (user) => STAFF_ROLES.includes(user?.role);

/** Whether this user's company can reach Leadership Score.
 *
 *  Leadership Score is part of TPMS and has no switch of its own, so this reads the TPMS
 *  flag — one control for both, which is why they can never disagree. Opt-in, so a
 *  missing flag means OFF. Internal staff always pass; they administer it across clients.
 *
 *  Presentation only. The backend gates every endpoint independently in
 *  utils/leadership_access.ensure_leadership_enabled. */
export const canAccessLeadership = (user) =>
  isStaff(user) || Boolean(user?.tpms_enabled);

/** The four levels a leader can be scored at. "Applicable from L4 (Asst Managers) and
 *  above" — set explicitly on the user record, never derived from their designation. */
export const LEADERSHIP_LEVELS = [
  { code: 'L4', label: 'L4 · Asst. Manager' },
  { code: 'L5', label: 'L5 · Manager' },
  { code: 'L6', label: 'L6 · Senior Manager' },
  { code: 'L7', label: 'L7 & above' },
];

/** Cycle status → tone, so chips agree everywhere. `published` is the state that matters:
 *  it is the first moment a leader can see their own score. */
export const cycleTone = (status) => ({
  draft: 'plain',
  open: 'blue',
  closed: 'yellow',
  computed: 'indigo',
  published: 'green',
}[status] || 'plain');

/** A client user's governance role — mirrors the backend's `_governance_role`. */
export const governanceRole = (user) =>
  String(user?.governance_role || user?.department || '').trim().toLowerCase();

/** A dedicated HR user: a clientuser carrying the HR governance role.
 *  Mirrors `_is_hr` in routes/leadership.py — a clientadmin is NOT HR here, even when
 *  flagged governance_role=hr, because it is the company's administrative account rather
 *  than a named person. */
export const isHr = (user) =>
  user?.role === 'clientuser' && governanceRole(user) === 'hr';

/** The company's MD. A clientadmin counts: it is the company's top-authority account and
 *  already maps to MD rank in auth_controller.client_rank, so both routes into that
 *  authority behave the same. Mirrors `_is_md` in routes/leadership.py. */
export const isMd = (user) =>
  user?.role === 'clientadmin' ||
  (user?.role === 'clientuser' && governanceRole(user) === 'md');

/** May sign off a level's question set. "All parameters should have weightages to create
 *  scoring - HR and MD", so approving a rubric is HR's and MD's call; internal staff keep
 *  access because they seed and support the module. Mirrors `_require_signoff`. */
export const canSignOff = (user) => isStaff(user) || isHr(user) || isMd(user);

/** Runs the process — cycles, enrolling leaders, reading scores.
 *  Mirrors `_can_manage` in routes/leadership.py. */
export const canManage = (user) =>
  isStaff(user) || user?.role === 'clientadmin' || isHr(user);

/** May see or change WHO gives feedback. Mirrors `_can_manage_panel` — deliberately
 *  narrower: a clientadmin runs the cycle but never sees a panel, because knowing who
 *  rates whom is enough on its own to de-anonymise a small relation group.
 *
 *  The backend enforces this independently on every panel endpoint; hiding the controls
 *  here is presentation only, never the control itself. */
export const canManagePanel = (user) => isStaff(user) || isHr(user);

/** Numbers render to 2dp with trailing zeros dropped; null → '—'. */
export const fmtNum = (v, dash = '—') => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return dash;
  return String(Math.round(Number(v) * 100) / 100);
};

export const fmtPct = (v, dash = '—') =>
  (v === null || v === undefined || Number.isNaN(Number(v)) ? dash : `${fmtNum(v)}%`);

/** Score → dashboardKit tone, so tiles, pills and bars agree. */
export const scoreTone = (score) => {
  if (score === null || score === undefined) return 'plain';
  if (score >= 85) return 'green';
  if (score >= 70) return 'blue';
  if (score >= 50) return 'yellow';
  return 'red';
};

export const scoreColor = (score) => ({
  green: 'var(--accent-green)',
  blue: 'var(--accent-indigo)',
  yellow: 'var(--accent-yellow)',
  red: 'var(--accent-red)',
  plain: 'var(--text-muted)',
}[scoreTone(score)]);

/** Link-status → tone for the panel table. */
export const linkTone = (status) => ({
  submitted: 'green',
  opened: 'blue',
  sent: 'yellow',
  expired: 'red',
}[status] || 'plain');

/** Read `detail` off an axios error, falling back to a caller-supplied message. */
export const errText = (e, fallback) => {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => String(d?.msg || '').replace(/^Value error,\s*/, '')).join(' ');
  }
  return fallback;
};

/**
 * Company selection. Internal staff pick a company (and need the list); client-side users
 * are pinned to their own by the backend, so they get no picker and no companies request.
 */
export const useLeadershipCompany = () => {
  const { user } = useAuth();
  const staff = isStaff(user);
  const [companies, setCompanies] = useState([]);
  // Only staff hold a selection; a client user's company is derived, never stored, so
  // switching accounts cannot leave a stale id behind.
  const [picked, setPicked] = useState('');

  useEffect(() => {
    if (!staff) return undefined;
    let cancelled = false;
    api.get('/companies')
      .then((res) => {
        if (cancelled) return;
        const list = (Array.isArray(res?.data) ? res.data : [])
          .map((c) => ({ id: String(c._id || c.id || ''), name: c.name || 'Untitled' }))
          .filter((c) => c.id);
        list.sort((a, b) => a.name.localeCompare(b.name));
        setCompanies(list);
        setPicked((prev) => prev || list[0]?.id || '');
      })
      .catch(() => { if (!cancelled) setCompanies([]); });
    return () => { cancelled = true; };
  }, [staff]);

  const companyId = staff ? picked : (user?.company_id || '');
  const companyOptions = useMemo(
    () => (companies.length ? companies : [{ id: '', name: 'Loading companies…' }]),
    [companies],
  );

  return { user, staff, companies, companyOptions, companyId, setCompanyId: setPicked };
};

/** An async loader with loading/error state, re-run when `deps` change. */
export const useAsync = (loader, deps, { skip = false } = {}) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(!skip);
  const [error, setError] = useState('');
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(loader, deps);

  const reload = useCallback(async () => {
    if (skip) { setLoading(false); return; }
    setLoading(true);
    setError('');
    try {
      setData(await run());
    } catch (e) {
      setError(errText(e, 'Something went wrong. Please try again.'));
    } finally {
      setLoading(false);
    }
  }, [run, skip]);

  useEffect(() => { reload(); }, [reload]);

  return useMemo(() => ({ data, setData, loading, error, setError, reload }),
    [data, loading, error, reload]);
};
