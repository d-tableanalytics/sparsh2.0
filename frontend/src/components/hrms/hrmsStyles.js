// Non-component shared pieces for the HRMS screens: field styles, initials, date formatting.
//
// Kept out of hrmsUi.jsx deliberately — a module that exports both components and plain values
// breaks React Fast Refresh (react-refresh/only-export-components), so components live in the
// .jsx and everything else lives here.
//
// All colour references are CSS variables from index.css, so light and dark themes are handled
// without a second palette.

// One definition, so every HRMS input matches the rest of the app.
export const inputCls =
  'w-full px-3.5 py-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-semibold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] transition-colors';

export const labelCls =
  'text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]';

// Lifecycle states map onto the app's existing semantic accents rather than a new palette:
// active = green, in-transition = yellow/orange, exited = red, retired = indigo.
export const STATUS_TONE = {
  Active:      { text: 'var(--status-active-text)', bg: 'var(--status-active-bg)', border: 'var(--status-active-border)' },
  Probation:   { text: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', border: 'var(--accent-yellow-border)' },
  'On Notice': { text: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', border: 'var(--accent-orange-border)' },
  Resigned:    { text: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
  Terminated:  { text: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
  Absconded:   { text: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
  Retired:     { text: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', border: 'var(--accent-indigo-border)' },
};

export const initials = (name) =>
  String(name || '')
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase() || '?';

// HR dates are stored as plain ISO "YYYY-MM-DD" (no time, no zone) so a date of joining can't
// shift a day for a reader in another timezone. Anchor bare dates at local midnight rather than
// letting Date parse them as UTC.
export const fmtDate = (value) => {
  if (!value) return '—';
  const d = new Date(String(value).length <= 10 ? `${value}T00:00:00` : value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
};

export const fmtDateTime = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
};
