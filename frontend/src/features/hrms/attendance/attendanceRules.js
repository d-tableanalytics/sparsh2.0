/**
 * HRMS ▸ Attendance — shared constants and pure helpers for the board, the shift master and
 * the day-detail view.
 *
 * Kept in a plain .js file for the same Fast Refresh reason internalKit is split in two: a
 * module that exports both components and values stops hot-reloading cleanly.
 */

// Backend order (models/hrms.py WEEKDAYS). Saturday is edited separately: it is the one day
// companies commonly give off only on some weeks ("2nd & 4th Saturday").
export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

export const SATURDAY_CHOICES = [
  { key: 'all', label: 'Every Saturday', entries: ['Saturday'] },
  { key: '2-4', label: '2nd & 4th Saturday', entries: ['Saturday#2', 'Saturday#4'] },
  { key: '1-3', label: '1st & 3rd Saturday', entries: ['Saturday#1', 'Saturday#3'] },
  { key: 'none', label: 'Saturday is working', entries: [] },
];

// Where a punch was entered from — the backend's ATTENDANCE_SOURCES, verbatim.
export const ATTENDANCE_SOURCES = ['Manual', 'Google', 'API', 'Biometric', 'Import', 'Self'];

/** Which Saturday preset a pattern matches, or 'custom' when it matches none of them. */
export const saturdayKey = (pattern) => {
  const sat = (pattern || []).filter((s) => s.startsWith('Saturday')).sort().join(',');
  const hit = SATURDAY_CHOICES.find((c) => [...c.entries].sort().join(',') === sat);
  return hit ? hit.key : 'custom';
};

const ORDINAL = { 1: '1st', 2: '2nd', 3: '3rd', 4: '4th', 5: '5th' };

/** "Sunday, Saturday#2, Saturday#4" -> "Sun, 2nd Sat, 4th Sat". */
export const describeWeeklyOff = (pattern) => {
  if (!pattern?.length) return 'None';
  return pattern.map((s) => {
    const [name, nth] = s.split('#');
    const short = name.slice(0, 3);
    return nth ? `${ORDINAL[nth] || `#${nth}`} ${short}` : short;
  }).join(', ');
};

/** Minutes as "8h 05m" — the way a day's worked time is read. */
export const hoursLabel = (minutes) => {
  if (minutes == null) return '—';
  const m = Math.max(0, Math.round(minutes));
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
};

/** A timestamp with its time of day, for audit lines (`day()` drops the time). */
export const stamp = (value) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? '—'
    : parsed.toLocaleString(undefined, {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
};

/**
 * The server's error message. A FastAPI validation 422 carries a LIST of problems rather
 * than a sentence — flatten it so a toast never tries to render an array.
 */
export const errorDetail = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d?.msg || String(d)).join('; ') || fallback;
  }
  return (typeof detail === 'string' && detail) || fallback;
};

/** Today as YYYY-MM-DD in the viewer's own calendar (not UTC's). */
export const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

// Where a day's punches came from. Lower-case values are the engine's own; the capitalised
// ones are the sources HR picks when marking (backend ATTENDANCE_SOURCES).
export const SOURCE_LABEL = {
  biometric: 'Biometric', self: 'Self check-in', manual: 'Marked by HR',
  regularization: 'Regularised', od: 'Outdoor duty', leave: 'Leave',
  Biometric: 'Biometric', Self: 'Self check-in', Import: 'Imported', Google: 'Google', API: 'API',
};

const RULE_SOURCE_LABEL = {
  'employee shift': 'set on the employee',
  'policy applicability': 'by applicability',
  'company policy': 'company timing',
  'flexible timing': 'approved flexible timing',
};

/** "GEN (set on the employee)" / "Company timing". */
export const shiftLabel = (r) => {
  const source = RULE_SOURCE_LABEL[r.rule_source] || r.rule_source;
  // A day recorded before the shift master existed carries neither — say nothing rather
  // than claim it was judged by the company timing.
  if (!r.shift_code && !r.rule_source) return '—';
  if (!r.shift_code) return r.rule_source === 'flexible timing' ? `Flexi ${r.flexi_no || ''}`.trim() : 'Company timing';
  return source ? `${r.shift_code} (${source})` : r.shift_code;
};

/** Payable day as people say it: full / half / LOP. */
export const payableLabel = (r) => {
  if (r.payable_day == null) return '—';
  const lop = r.lop_fraction ? ` · LOP ${r.lop_fraction}` : '';
  return `${r.payable_day} day${lop}`;
};
