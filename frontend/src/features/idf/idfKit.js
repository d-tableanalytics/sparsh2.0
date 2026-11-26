/* Shared helpers for the Inter-Departmental Feedback pages (components live in IdfBits.jsx). */

// RAG bands (client document §6): Red < 60, Amber 60–79.9, Green >= 80.
export const BAND_STYLE = {
  Red: { c: 'var(--accent-red)', bg: 'var(--accent-red-bg)', bd: 'var(--accent-red-border, var(--accent-red))' },
  Amber: { c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)' },
  Green: { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)', bd: 'var(--accent-green-border)' },
};

export const STATUS_STYLE = {
  Completed: { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)' },
  Pending: { c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)' },
  Overdue: { c: 'var(--accent-red)', bg: 'var(--accent-red-bg)' },
  Open: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)' },
  'In Progress': { c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)' },
  Closed: { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)' },
  Cancelled: { c: 'var(--text-muted)', bg: 'var(--input-bg)' },
};

export const pctText = (v) => (v === null || v === undefined ? '—' : `${v}%`);
export const bandOf = (pct) => (pct === null || pct === undefined ? null : pct < 60 ? 'Red' : pct < 80 ? 'Amber' : 'Green');

export const monthLabel = (p) => {
  const [y, m] = String(p || '').split('-').map(Number);
  return y && m ? new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }) : (p || '—');
};

export const day = (iso) => {
  if (!iso) return '—';
  const s = String(iso);
  const d = new Date(/T/.test(s) && !/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? `${s}Z` : s);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
};

// Date AND time, in India time — e.g. a submission's "25 Nov 2026, 4:17 pm".
export const dayTime = (iso) => {
  if (!iso) return '—';
  const s = String(iso);
  const d = new Date(/T/.test(s) && !/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? `${s}Z` : s);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata',
  });
};

export const CARD = 'rounded-2xl border border-[var(--border)] bg-[var(--bg-card)]';
export const FIELD = 'px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[12.5px] text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]';
export const TH = 'text-left px-3 py-2 text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)] whitespace-nowrap';
export const TD = 'px-3 py-2 text-[12.5px] text-[var(--text-main)] align-top';

export const saveBlob = (data, name) => {
  const url = URL.createObjectURL(new Blob([data]));
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
};

/** The company the page acts on: a Sparsh Admin picks one; everyone else uses their own. */
export const isStaffAdmin = (user) => ['superadmin', 'admin'].includes(user?.role);

/** Permanent delete (cycles, issues, actions): the Super Admin, the Client Admin and the MD. */
export const canDelete = (user) => ['superadmin', 'clientadmin'].includes(user?.role)
  || (user?.governance_role || '').trim().toUpperCase() === 'MD';
