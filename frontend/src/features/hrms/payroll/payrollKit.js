import { useState } from 'react';

/**
 * HRMS ▸ Payroll — shared constants, pure helpers and the one submit hook.
 *
 * A .js file, not .jsx, for the reason internalKit.js gives: a module that exports both
 * components and plain values breaks React Fast Refresh. The payroll screens are split over
 * several files (the board, the run detail, disbursal, the component editor) and they all
 * need the same status lists and the same error wording, so those live here once.
 */

/** FRD §12 — the run lifecycle, in the order a month walks through it. */
/** FRD §12 stages 5-13. Check (stage 8) and Approve (stage 9) are SEPARATE authorities —
 *  the Payroll/HR Checker verifies, Finance approves — so they are two steps, not one. */
export const RUN_STAGES = ['Calculate', 'Submit', 'Check', 'Approve', 'Lock', 'Pay', 'Close'];

/** Inputs (Calculate, Adjust) are accepted only while the run is with the maker. */
export const EDITABLE_RUN_STATUSES = ['Draft', 'Calculated', 'Returned', 'Rejected'];
/** Locked onwards: payslips are final, the bank file can be made, corrections are post-lock. */
export const FINAL_RUN_STATUSES = ['Locked', 'Paid', 'Closed'];

/** Which RUN_STAGES entry a status is waiting on (RUN_STAGES.length = all done). */
export const stageIndex = (status) => ({
  Draft: 0, Returned: 0, Rejected: 0, Calculated: 1, Submitted: 2,
  Checked: 3, Approved: 4, Locked: 5, Paid: 6, Closed: 7,
}[status] ?? 0);

export const PAYMENT_MODES = ['NEFT', 'RTGS', 'IMPS', 'Bank Transfer', 'Cheque', 'Cash', 'Manual Advice'];
export const PAYMENT_STATUSES = ['Pending', 'Processed', 'Failed', 'Rejected'];

/** Payment and batch statuses are not in the shared toneFor map — 'Processed' would fall to
 *  neutral there, and a payment the bank confirmed is the good news on this screen. */
export const paymentTone = (status) => ({
  Processed: 'good', Pending: 'warn', Generated: 'warn', 'Partially Processed': 'warn',
  Failed: 'bad', Rejected: 'bad', 'Partially Failed': 'bad',
  Applied: 'good', Included: 'accent',
}[status] || 'neutral');

/** Run statuses on this board. 'Returned' means "back with the maker" (warn), not the
 *  asset-return green toneFor gives it; 'Submitted' is someone being waited on. */
export const runTone = (status) => ({
  Draft: 'neutral', Calculated: 'warn', Submitted: 'warn', Approved: 'accent',
  Returned: 'warn', Rejected: 'bad', Locked: 'good', Paid: 'good', Closed: 'good',
}[status] || 'neutral');

/** FastAPI error detail as one readable sentence — a 422 from pydantic is an array. */
export const errText = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => d?.msg || String(d)).join('; ');
  }
  return fallback;
};

/** The same for a `responseType: 'blob'` call: on an error the body is a Blob too, so the
 *  JSON detail has to be read out of it before it can be shown. */
export const blobErrText = async (err, fallback) => {
  const data = err?.response?.data;
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text());
      return typeof parsed?.detail === 'string' ? parsed.detail : fallback;
    } catch {
      return fallback;
    }
  }
  return errText(err, fallback);
};

/** Hand a downloaded Blob to the browser as a file. */
export const saveBlob = (data, filename) => {
  const blob = data instanceof Blob ? data : new Blob([data], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

/** A date and time, or an em dash — for the approval trail and payment timestamps. */
export const when = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—'
    : d.toLocaleString(undefined, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
};

/** A signed figure for a variance: "+1,200" / "−300". */
export const signed = (value) => {
  if (value == null) return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return '—';
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toLocaleString()}`;
};

/** The month after a YYYY-MM period — the default landing month of a post-lock correction. */
export const nextPeriod = (period) => {
  const [y, m] = String(period || '').split('-').map(Number);
  if (!y || !m) return '';
  return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
};

/**
 * The bank's response pasted as CSV — `employee_code,status,utr,payment_date,failure_reason`
 * per line — turned into the rows importPaymentStatuses takes. A header line is skipped, a
 * blank cell becomes undefined, and quoting is stripped. Validation is the server's: each bad
 * row comes back with its own error, which is more useful than a client guess.
 */
export const parseBankResponse = (text) => String(text || '')
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter(Boolean)
  .map((line) => line.split(',').map((cell) => cell.trim().replace(/^"(.*)"$/, '$1').trim()))
  .filter((cells) => cells[0] && cells[0].toLowerCase() !== 'employee_code')
  .map(([code, status, utr, paymentDate, ...reason]) => ({
    employee_code: code,
    status: status || undefined,
    utr: utr || undefined,
    payment_date: paymentDate || undefined,
    // A failure reason may itself contain commas — everything after the date is the reason.
    failure_reason: reason.join(', ').trim() || undefined,
  }));

// ── Salary component master (FRD §24) ──
export const COMPONENT_TYPES = [
  'Earning', 'Deduction', 'Employer Contribution', 'Reimbursement', 'Recovery', 'Informational',
];
export const METHODS = ['Fixed', 'Percentage', 'Formula', 'Slab', 'Manual Input'];
export const SECTIONS = ['Regular Earnings', 'Other Earnings', 'Deductions', 'Employer Contribution', 'Hidden'];
export const ROUNDING = ['None', 'Nearest', 'Floor', 'Ceiling'];
export const FREQUENCIES = ['Monthly', 'One-time', 'Quarterly', 'Annual', 'Ad hoc'];
/** Types that come OFF take-home pay. */
export const DEDUCTING_TYPES = ['Deduction', 'Recovery'];

export const COMPONENT_TYPE_TONE = {
  Earning: 'good', Reimbursement: 'good', Deduction: 'warn', Recovery: 'warn',
  'Employer Contribution': 'accent', Informational: 'neutral',
};

/** "40% of BASIC", "Fixed", "Typed in monthly" — how a component's amount is reached. */
export const methodText = (c) => {
  if (c.calculation_method === 'Percentage') {
    return `${c.percentage ?? '?'}% of ${c.calculation_base || '?'}`;
  }
  if (c.calculation_method === 'Manual Input') return 'Typed in monthly';
  if (c.calculation_method === 'Formula') return `= ${c.formula || '?'}`;
  if (c.calculation_method === 'Slab') return `Slab on ${c.calculation_base || '?'}`;
  return 'Fixed';
};

/** Formula and Slab amounts are worked out by the server when a salary is saved. */
export const isComputedMethod = (c) => ['Formula', 'Slab'].includes(c?.calculation_method);

/** The full payload a component save needs. Built field by field so a list row's extras
 *  (history, version, ids) never travel back, and blanks go as null (= the type's default). */
export const componentPayload = (c) => {
  const num = (v) => (v === '' || v == null ? null : Number(v));
  const pct = c.calculation_method === 'Percentage';
  const slab = c.calculation_method === 'Slab';
  return {
    code: c.code, name: c.name, component_type: c.component_type,
    statutory: !!c.statutory, active: c.active !== false,
    calculation_method: c.calculation_method || 'Fixed',
    calculation_base: pct || slab ? (c.calculation_base || null) : null,
    formula: c.calculation_method === 'Formula' ? (c.formula || '').trim() : null,
    slabs: slab ? (c.slabs || []).map((s) => ({
      upto: s.upto === '' || s.upto == null ? null : Number(s.upto),
      ...(s.kind === 'percent' ? { percent: Number(s.value) || 0 } : { amount: Number(s.value) || 0 }),
    })) : null,
    change_reason: (c.change_reason || '').trim() || null,
    percentage: pct ? num(c.percentage) : null,
    proration: c.proration || null,
    rounding: c.rounding || 'None',
    min_amount: num(c.min_amount), max_amount: num(c.max_amount),
    sequence: num(c.sequence),
    payslip_section: c.payslip_section || null,
    frequency: c.frequency || null,
    accounting_code: (c.accounting_code || '').trim() || null,
    description: (c.description || '').trim() || null,
  };
};

/** Busy flag + a runner that toasts success / the server's own error. */
export const useSubmit = (showSuccess, showError, onDone) => {
  const [busy, setBusy] = useState(false);
  const run = async (fn, successMsg) => {
    setBusy(true);
    try {
      await fn();
      if (successMsg) showSuccess(successMsg);
      onDone();
    } catch (err) {
      showError(errText(err, 'That action could not be completed.'));
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
};
