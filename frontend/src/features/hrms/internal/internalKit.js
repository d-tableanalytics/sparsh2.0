/**
 * HRMS ▸ internal recruitment track — shared constants and pure helpers.
 *
 * Split from internalKit.jsx for the same reason analyticsKit is split: a module that
 * exports both components and plain values breaks React Fast Refresh, so the values live
 * here and the components next door. Same rule, same pair of filenames.
 */

export const CARD =
  'rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 sm:p-5';
export const FIELD =
  'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] '
  + 'text-[13px] text-[var(--text-main)]';
export const TEXTAREA =
  'w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] '
  + 'text-[13px] text-[var(--text-main)] resize-none';
export const LABEL =
  'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';
export const SECTION_TITLE =
  'text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]';

/**
 * Which tone a status name earns.
 *
 * TONE IS MEANING. Green only where the news is good, red only where something failed,
 * amber only where somebody is being waited on. An unknown value falls back to neutral
 * rather than throwing — a status added server-side must render, not break the screen.
 */
export const toneFor = (status) => ({
  Approved: 'good', Confirmed: 'good', Positive: 'good', met: 'good', Met: 'good',
  // Phase INT-4 — telephonic outcomes. "No Answer" is warn, not bad: a call nobody picked
  // up is unfinished work, not a verdict on the candidate.
  Passed: 'good', 'No Answer': 'warn',
  Strong: 'good', Consider: 'warn', Hold: 'warn', Reject: 'bad',
  Rejected: 'bad', Terminated: 'bad', Negative: 'bad', breached: 'bad', Breached: 'bad',
  overdue: 'bad', Overdue: 'bad',
  Pending: 'warn', 'Pending Approval': 'warn', 'Pending HR Verification': 'warn',
  'Pending Budget Approval': 'warn', 'Pending Scorecard Approval': 'warn',
  'Pending Escalation': 'warn', 'Unable to Verify': 'warn', Extended: 'warn',
  Draft: 'neutral', not_started: 'neutral',
}[status] || 'neutral');

/** A date, or an em dash. Never "Invalid Date", which reads as a bug in the data. */
export const day = (value) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? '—'
    : parsed.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
};
