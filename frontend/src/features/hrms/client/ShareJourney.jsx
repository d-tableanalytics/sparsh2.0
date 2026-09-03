import React from 'react';
import { Check, Circle, Dot, Lock, X } from 'lucide-react';
import { day } from '../internal/internalKit';

/**
 * HRMS ▸ the hiring ladder for ONE candidate at ONE client.
 *
 * Answers the question a status chip cannot: where is this, what is done, what is next, and
 * if something is locked — why.
 *
 * -- Two audiences, two ladders, and that is the point -------------------------------------
 * Sparsh and the client see different rungs, because the stages between Selected and an
 * offer are OURS. Background verification and HR approval are Sparsh's process; a client
 * seeing "HR approval pending" would learn that we are mid-way through an internal control
 * on a candidate they are one of several bidders for.
 *
 * So the client's ladder ends the client-facing journey at Selected and shows one honest
 * summary rung — "with the Sparsh team" — where our internals would be. The isolation rule
 * that governs the data governs the progress indicator too; a ladder that leaked the shape
 * of our process would defeat the snapshot it sits next to.
 *
 * -- Locked is not the same as pending -----------------------------------------------------
 * A pending stage is simply not reached yet. A LOCKED stage is reached and refused, and the
 * reason is the useful part: "identity and education checks outstanding" tells a recruiter
 * what to do, where a greyed-out button tells them to ask somebody.
 *
 * Every state shown here is derived from the server's own answer — the share's `history`
 * and, for Sparsh, `cleared_for_offer` / `outstanding` from the verification endpoint.
 * Nothing about a lock is decided in the browser; this renders a decision already made.
 */

// The client-facing rungs, in order. These are the ShareStatus values a client's process
// actually moves through — Withdrawn is an exit, not a rung, so it is not on the ladder.
const CLIENT_RUNGS = [
  'CV Shared', 'Under Review', 'Shortlisted', 'Interview Scheduled', 'Selected',
];
// What follows selection, on Sparsh's side only.
const SPARSH_TAIL = ['Offer in Progress', 'Hired'];

const RANK = [...CLIENT_RUNGS, ...SPARSH_TAIL];

const Marker = ({ state }) => {
  const base = 'shrink-0 w-[18px] h-[18px] rounded-full grid place-items-center';
  if (state === 'done') {
    return (
      <span className={`${base} bg-[var(--accent-green,#1b7a4b)] text-white`}>
        <Check size={11} strokeWidth={3} />
      </span>
    );
  }
  if (state === 'current') {
    return (
      <span className={`${base} bg-[var(--accent-indigo)] text-white`}>
        <Dot size={16} strokeWidth={4} />
      </span>
    );
  }
  if (state === 'locked') {
    return (
      <span className={`${base} bg-[var(--danger,#b3261e)] text-white`}>
        <Lock size={10} strokeWidth={2.5} />
      </span>
    );
  }
  if (state === 'stopped') {
    return (
      <span className={`${base} bg-[var(--danger,#b3261e)] text-white`}>
        <X size={11} strokeWidth={3} />
      </span>
    );
  }
  return (
    <span className={`${base} border border-[var(--border)] text-[var(--text-muted)]`}>
      <Circle size={7} strokeWidth={3} />
    </span>
  );
};

const Rung = ({ label, state, when, who, reason, last }) => (
  <li className="flex gap-2.5">
    <div className="flex flex-col items-center">
      <Marker state={state} />
      {!last && (
        <span
          className={`w-px flex-1 min-h-[14px] ${
            state === 'done' ? 'bg-[var(--accent-green,#1b7a4b)]' : 'bg-[var(--border)]'}`}
        />
      )}
    </div>
    <div className={`pb-3 min-w-0 ${last ? 'pb-0' : ''}`}>
      <p className={`text-[12.5px] leading-tight ${
        state === 'pending'
          ? 'text-[var(--text-muted)]'
          : 'text-[var(--text-main)] font-semibold'}`}>
        {label}
      </p>
      {when && (
        <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
          {day(when)}{who ? ` · ${who}` : ''}
        </p>
      )}
      {reason && (
        <p className="text-[11.5px] text-[var(--danger,#b3261e)] mt-0.5">{reason}</p>
      )}
    </div>
  </li>
);

/**
 * @param share        the share row (its `history` drives the completed rungs)
 * @param variant      'sparsh' — the full ladder including our gates
 *                     'client' — the client-facing rungs only
 * @param verification the verification state from GET /candidates/{uk}/verification.
 *                     Sparsh only, and optional: until it is loaded the gate rungs read as
 *                     pending rather than pretending to know they are clear.
 */
const ShareJourney = ({ share, variant = 'sparsh', verification = null }) => {
  const status = share?.status;
  const history = share?.history || [];
  const reached = new Set(history.map((h) => h.status));
  // A share the client rejected, or one Sparsh pulled back, stops where it stopped — the
  // remaining rungs are not "pending", they are not going to happen.
  const halted = status === 'Rejected' || status === 'Withdrawn';
  const at = RANK.indexOf(status);

  const entry = (name) => history.find((h) => h.status === name);
  const stateFor = (name, index) => {
    if (name === status) return halted ? 'stopped' : 'current';
    if (reached.has(name) || (at > -1 && index < at)) return 'done';
    return 'pending';
  };

  const rungs = [];
  CLIENT_RUNGS.forEach((name, i) => {
    const e = entry(name);
    rungs.push({
      label: name,
      state: stateFor(name, i),
      when: e?.at,
      who: variant === 'sparsh' ? e?.by_name : undefined,
    });
  });

  if (halted) {
    rungs.push({
      label: status === 'Rejected' ? 'Not taken forward' : 'Withdrawn by Sparsh',
      state: 'stopped',
      when: entry(status)?.at,
      who: variant === 'sparsh' ? entry(status)?.by_name : undefined,
      reason: variant === 'sparsh' && status === 'Rejected'
        ? 'This client passed. The candidate can still go to another.'
        : undefined,
    });
  } else if (variant === 'client') {
    // One honest rung where our internals would be. It says what is true — the file is with
    // us — without naming the checks, the approval or who is waiting on whom.
    const past = RANK.indexOf(status) >= RANK.indexOf('Selected');
    rungs.push({
      label: 'With the Sparsh team',
      state: status === 'Hired' ? 'done' : past ? 'current' : 'pending',
      reason: undefined,
    });
    rungs.push({
      label: 'Hired',
      state: status === 'Hired' ? 'done' : 'pending',
      when: entry('Hired')?.at,
    });
  } else {
    // Sparsh's tail: the two gates, then the offer, then the placement. Each gate's state
    // comes from the server's verification answer, never from a guess here.
    const selected = RANK.indexOf(status) >= RANK.indexOf('Selected');
    const v = verification;
    const checksDone = !!v?.checks_complete;
    const approved = v?.approval?.status === 'Approved';
    const cleared = !!v?.cleared_for_offer;

    rungs.push({
      label: 'Background verification',
      state: !selected ? 'pending'
        : checksDone ? 'done'
          : v ? 'locked' : 'pending',
      reason: selected && v && !checksDone
        ? (v.flagged?.length
          ? `Flagged: ${v.flagged.join(', ')}`
          : `Outstanding: ${(v.outstanding || []).join(', ')}`)
        : undefined,
    });
    rungs.push({
      label: 'HR approval',
      state: !selected || !checksDone ? 'pending' : approved ? 'done' : 'locked',
      when: v?.approval?.decided_at,
      who: v?.approval?.decided_by_name,
      reason: selected && checksDone && !approved
        ? 'Checks are complete. HR must sign the file before an offer can be raised.'
        : undefined,
    });
    rungs.push({
      label: 'Offer',
      state: RANK.indexOf(status) >= RANK.indexOf('Offer in Progress') ? 'done'
        : cleared ? 'current' : 'locked',
      when: entry('Offer in Progress')?.at,
      reason: !cleared && selected
        ? 'Locked until verification is complete and approved.'
        : undefined,
    });
    rungs.push({
      label: 'Hired',
      state: status === 'Hired' ? 'done' : 'pending',
      when: entry('Hired')?.at,
    });
  }

  return (
    <ol className="grid" aria-label="Hiring stages">
      {rungs.map((r, i) => (
        <Rung key={r.label} {...r} last={i === rungs.length - 1} />
      ))}
    </ol>
  );
};

export default ShareJourney;
