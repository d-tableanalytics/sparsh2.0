/**
 * HRMS ▸ the words behind <ProcessGuide> and <NextStep>.
 *
 * Written for somebody with no HR-system background: short sentences, no document section
 * numbers, no abbreviations without the full term, and every step names the button to press.
 *
 * Each `…NextStep(record)` returns { tone, text, step }:
 *   tone  'action' (you do something) | 'waiting' (someone else does) | 'done'
 *   text  one sentence
 *   step  index into that guide's `steps`, so the guide can highlight "You are here"
 *         (steps.length means every step is finished).
 */

// ── Exit ──────────────────────────────────────────────────────────────────────────────

export const EXIT_GUIDE = {
  id: 'exit',
  title: 'How an exit works',
  intro: 'From the day someone resigns to their final payment. Open a case to see exactly what is left.',
  steps: [
    { title: 'Start the exit', text: 'Click Initiate Exit and pick the employee. The notice period is worked out for you.' },
    { title: 'Agree the last day', text: 'Confirm the last working day, or change it. A change needs approval.' },
    { title: 'Hand over work', text: 'List the work they must pass on, and who accepts it.' },
    { title: 'Clearance', text: 'Each department signs off, company items are returned and system access is removed.' },
    { title: 'Exit interview', text: 'Talk to them about why they are leaving and record it.' },
    { title: 'Final settlement', text: 'Prepare the final payment (F&F). Finance approves it, then you mark it paid.' },
    { title: 'Close the case', text: 'Once everything above is done, click Close Case.' },
  ],
};

const EXIT_STAGE_FALLBACK = {
  Initiated: { tone: 'action', text: 'Open the case and confirm the last working day.', step: 1 },
  'Notice in Progress': { tone: 'action', text: 'Notice period running — open the case to start the handover.', step: 2 },
  'Handover & Clearance': { tone: 'action', text: 'Open the case to finish handover and department sign-offs.', step: 3 },
  'F&F Pending': { tone: 'waiting', text: 'The final settlement is being prepared or approved.', step: 5 },
  'F&F Approved': { tone: 'action', text: 'Settlement approved — pay it and mark it paid.', step: 5 },
  Settled: { tone: 'action', text: 'Paid — open the case and click Close Case.', step: 6 },
};

export const separationNextStep = (sep) => {
  if (!sep) return null;
  const all = EXIT_GUIDE.steps.length;
  if (sep.stage === 'Closed') return { tone: 'done', text: 'This exit is complete. Nothing more to do.', step: all };
  if (sep.stage === 'Withdrawn') return { tone: 'done', text: 'Withdrawn — the employee is staying. Nothing more to do.', step: null };

  if (!sep.final_lwd && !sep.recommended_lwd) {
    return { tone: 'action', text: 'Confirm the last working day — click Record Decision.', step: 1 };
  }
  if (sep.recommended_lwd && !sep.final_lwd) {
    return { tone: 'waiting', text: 'A changed last working day is waiting for approval.', step: 1 };
  }

  const p = sep.progress;
  if (!p) return EXIT_STAGE_FALLBACK[sep.stage] || null;

  if (p.handover.done < p.handover.total) {
    return { tone: 'action', text: `Finish the handover — ${p.handover.done} of ${p.handover.total} tasks accepted.`, step: 2 };
  }
  if (p.clearance.done < p.clearance.total) {
    return { tone: 'action', text: `Get department sign-offs — ${p.clearance.done} of ${p.clearance.total} done.`, step: 3 };
  }
  if (p.asset_returns.pending) {
    return { tone: 'action', text: `Collect company items — ${p.asset_returns.pending} not returned yet.`, step: 3 };
  }
  if (p.access_clearances.pending) {
    return { tone: 'action', text: `Remove system access — ${p.access_clearances.pending} still open.`, step: 3 };
  }
  if (!p.exit_interview_done) {
    return { tone: 'action', text: 'Record the exit interview.', step: 4 };
  }
  switch (p.fnf_status) {
    case 'Prepared':
      return { tone: 'waiting', text: 'Finance needs to approve the final settlement.', step: 5 };
    case 'Approved':
      return { tone: 'action', text: 'Pay the final settlement, then click Mark Paid.', step: 5 };
    case 'Paid':
      return { tone: 'action', text: 'Everything is done — click Close Case.', step: 6 };
    case 'Rejected':
      return { tone: 'action', text: 'Finance sent the settlement back — correct it and prepare it again.', step: 5 };
    default:
      return { tone: 'action', text: 'Prepare the final settlement (F&F) — click Prepare.', step: 5 };
  }
};

// ── Onboarding ────────────────────────────────────────────────────────────────────────

export const ONBOARDING_GUIDE = {
  id: 'onboarding',
  title: 'How onboarding works',
  intro: 'From a sent appointment letter to a new employee who is ready on day one. Click a card to work on it.',
  steps: [
    { title: 'Appointment letter first', text: 'After the offer is accepted, send the appointment letter. Onboarding opens automatically once it is sent.' },
    { title: 'Start onboarding', text: 'If it did not open by itself, click Start onboarding — only candidates whose letter was sent are listed.' },
    { title: 'Joining form', text: 'Send them the form link. They fill in personal, bank and ID details and upload documents.' },
    { title: 'Check documents', text: 'Look at each document and mark their details verified.' },
    { title: 'First day', text: 'On the day they join, confirm the date they actually reported.' },
    { title: 'Employee ID', text: 'Issue the Employee ID. They now appear as an employee.' },
    { title: 'Joining checklist', text: 'Tick off laptop, email, induction and the rest. Onboarding finishes when all are ticked.' },
  ],
};

const today = () => new Date().toLocaleDateString('en-CA');
const niceDate = (iso) => {
  if (!iso) return '';
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
};

/** `inCase`: shown inside the open case, where the form link is right there on screen. */
export const onboardingNextStep = (r, { inCase = false } = {}) => {
  if (!r) return null;
  const all = ONBOARDING_GUIDE.steps.length;
  if (r.status === 'Completed') return { tone: 'done', text: 'Onboarding finished — they are now an employee.', step: all };

  if (r.employee_id) {
    const p = r.progress;
    return {
      tone: 'action',
      text: p?.total ? `Tick off the joining checklist — ${p.done} of ${p.total} done.` : 'Tick off the joining checklist.',
      step: 5,
    };
  }
  if (!r.pre_status || r.pre_status === 'Pending') {
    return {
      tone: 'waiting',
      text: inCase
        ? 'Waiting for them to fill in the joining form. Copy the form link below and send it to them.'
        : 'Waiting for them to fill in the joining form. Open the card to copy the form link and send it.',
      step: 1,
    };
  }
  if (r.pre_status === 'Submitted') {
    return { tone: 'action', text: 'They sent the form — check their details and documents, then mark them verified.', step: 2 };
  }
  if (r.bg_verification === 'Flagged') {
    return { tone: 'action', text: 'The background check is flagged — sort it out before issuing an Employee ID.', step: 2 };
  }
  if (!r.joining_date) {
    return { tone: 'action', text: 'Set their joining date.', step: 3 };
  }
  if (!r.actual_doj) {
    return r.joining_date > today()
      ? { tone: 'waiting', text: `Joining on ${niceDate(r.joining_date)}. On that day, confirm they joined.`, step: 3 }
      : { tone: 'action', text: 'Confirm they joined — record the date they actually reported.', step: 3 };
  }
  return { tone: 'action', text: 'Issue their Employee ID.', step: 4 };
};

// ── Pre-joiners ───────────────────────────────────────────────────────────────────────

export const PREBOARDING_GUIDE = {
  id: 'preboarding',
  title: 'Why keep in touch before day one',
  intro: 'People who accept an offer sometimes change their mind. A regular call keeps them warm.',
  steps: [
    { title: 'Call or message', text: 'Check in with each person who has accepted but not yet joined.' },
    { title: 'Log it', text: 'Click Log contact and note how it went — and if they mentioned another offer.' },
    { title: 'Watch the list', text: 'Anyone not contacted for 7 days is flagged here so nobody is forgotten.' },
  ],
};

// ── Attendance ────────────────────────────────────────────────────────────────────────

export const ATTENDANCE_GUIDE = {
  id: 'attendance',
  title: 'How attendance works',
  intro: 'Record each day, fix mistakes, then lock the month so pay can be worked out from it.',
  steps: [
    { title: 'Record each day', text: 'Staff Check in / Check out at the office (location checked), HR imports the biometric file, or HR marks the day.' },
    { title: 'Fix mistakes', text: 'Forgot to punch in? Request Regularisation. The manager, then HR, approves it.' },
    { title: 'Away or different hours', text: 'Field work goes under Outdoor Duty; different working hours under Flexible Timing (manager approves).' },
    { title: 'Check late arrivals', text: 'Late Coming shows who came in late, within or beyond the monthly buffer. Timing, grace and buffer are in Settings.' },
    { title: 'Lock the month', text: 'In Monthly Closure, lock the month once it is final. Payroll uses these days.' },
  ],
};

// ── Leave ─────────────────────────────────────────────────────────────────────────────

export const LEAVE_GUIDE = {
  id: 'leave',
  title: 'How leave works',
  intro: 'An employee asks, the manager and then HR approve, and the days come off their balance.',
  steps: [
    { title: 'Apply', text: 'Click Apply Leave, pick the type and the dates. The balance is checked straight away.' },
    { title: 'Manager approves', text: 'Their manager clicks Act to approve or reject.' },
    { title: 'HR approves', text: 'HR gives the final approval. The days are taken off the balance.' },
    { title: 'Check balances', text: 'The Balances tab shows how much leave everyone has left.' },
  ],
};

export const leaveNextStep = (r, canApprove) => {
  switch (r?.status) {
    case 'Pending':
      return canApprove
        ? { tone: 'action', text: 'Waiting for the manager — click Act to approve or reject.' }
        : { tone: 'waiting', text: 'Waiting for the manager to approve.' };
    case 'Manager Approved':
      return canApprove
        ? { tone: 'action', text: 'Manager approved — click Act to give HR’s final approval.' }
        : { tone: 'waiting', text: 'Manager approved — waiting for HR’s final approval.' };
    case 'Approved': return { tone: 'done', text: 'Approved. The days are off their balance.' };
    case 'Rejected': return { tone: 'done', text: 'Rejected. Nothing was taken off the balance.' };
    case 'Returned': return { tone: 'action', text: 'Sent back — the employee should correct it and apply again.' };
    case 'Cancelled': return { tone: 'done', text: 'Cancelled. Any days taken were given back.' };
    default: return null;
  }
};

// ── Movements & Discipline ────────────────────────────────────────────────────────

export const MOVEMENT_GUIDES = {
  Movements: {
    id: 'movements',
    title: 'How a promotion, transfer or pay change works',
    intro: 'Changes to an existing employee\'s job, with a permanent history of what changed and when.',
    steps: [
      { title: 'Propose', text: 'Click Propose Movement, pick the employee and the change. Their current value is filled in for you.' },
      { title: 'Approve', text: 'Someone other than the person who proposed it approves or rejects it.' },
      { title: 'It takes effect', text: 'On the effective date the change is applied. A pay change becomes their new salary in payroll.' },
    ],
  },
  Discipline: {
    id: 'discipline',
    title: 'How a discipline case works',
    intro: 'For misconduct, attendance problems, harassment and similar. Harassment/POSH cases are kept private.',
    steps: [
      { title: 'Report', text: 'Create the case: who it is about, who raised it, and what happened.' },
      { title: 'Investigate', text: 'Add notes as you speak to the people involved.' },
      { title: 'Recommend', text: 'Record what you recommend should happen.' },
      { title: 'Decide', text: 'The MD decides the outcome — a warning, show cause, no action and so on.' },
      { title: 'Close', text: 'Close the case. Anyone named in a case never sees or handles it.' },
    ],
  },
  Absconding: {
    id: 'absconding',
    title: 'What to do when someone stops coming to work',
    intro: 'For an employee absent without telling anyone. The waiting times are in Policy.',
    steps: [
      { title: 'Flag', text: 'Flag them from the first day of unexplained absence (never a future date).' },
      { title: 'Try to reach them', text: 'Log every call, email or letter.' },
      { title: 'Warn', text: 'Send a first warning, then a second after the waiting days.' },
      { title: 'Decide', text: 'They return to work, or the case becomes an exit in Exit Management.' },
    ],
  },
  'Retirement Alerts': {
    id: 'retirement',
    title: 'Retirement alerts',
    intro: 'A reminder list worked out from dates of birth. Nothing happens here automatically.',
    steps: [
      { title: 'Watch the list', text: 'Anyone retiring within the alert window appears here, and anyone already past the age shows as Overdue.' },
      { title: 'Start their exit', text: 'In Exit Management, click Initiate Exit and choose Retirement.' },
    ],
  },
};

// ── Payroll ───────────────────────────────────────────────────────────────────────────

export const PAYROLL_GUIDE = {
  id: 'payroll',
  title: 'How a month’s payroll works',
  intro: 'Set salaries once, then each month: create, calculate, check, approve.',
  steps: [
    { title: 'Set salaries', text: 'Each employee needs a salary in the Salary Structure tab — without one, their pay shows as 0.' },
    { title: 'Lock attendance', text: 'In Attendance → Monthly Closure, lock the month so the days cannot change.' },
    { title: 'Create the run', text: 'Click Create Run and choose the month.' },
    { title: 'Calculate', text: 'Open the run and click Calculate. Pay is worked out for everyone.' },
    { title: 'Check and adjust', text: 'Look through each person. Use Adjust for a one-off bonus or deduction.' },
    { title: 'Approve and lock', text: 'An approver clicks Approve & Lock. Payslips become final.' },
  ],
};

export const payrollNextStep = (run) => {
  switch (run?.status) {
    case 'Draft': return { tone: 'action', text: 'Open it and click Calculate.', step: 3 };
    case 'Calculated': return { tone: 'action', text: 'Check the figures. An approver then clicks Approve & Lock.', step: 4 };
    case 'Rejected': return { tone: 'action', text: 'Sent back by the approver — fix the figures and click Calculate again.', step: 4 };
    case 'Approved':
    case 'Locked': return { tone: 'done', text: 'Final. Payslips are ready.', step: PAYROLL_GUIDE.steps.length };
    default: return null;
  }
};
