import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Wallet, Target, CalendarDays, PhoneCall, FileSignature, ShieldCheck,
  ClipboardCheck, AlertTriangle, ArrowRight,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getInternalTracker } from '../../../services/hrmsApi';
import { CARD, day } from './internalKit';
import { Chip } from './internalKit.jsx';

/**
 * HRMS ▸ internal hiring ▸ what needs doing (spec §7).
 *
 * The queue screen answers "what can I do to THIS requisition". This one answers the
 * question a person actually arrives with: *where is the work*. Across every open internal
 * position, what is waiting on somebody, and on whom.
 *
 * -- Why this reads the tracker instead of a new endpoint ------------------------------------
 * `GET /internal-requisitions/tracker` already returns, per requisition, the approval state,
 * the budget, the scorecard, the pipeline counts, the offer, the probation and the SLA. That
 * is every figure on this page. A `/dashboard/counts` endpoint would be a second definition
 * of the same numbers, and the two would eventually disagree — the tracker would say four
 * interviews pending and the dashboard three, and nobody would know which was lying.
 *
 * So the counting happens here, over one payload, and the tiles and the table below them are
 * guaranteed to be about the same rows.
 *
 * -- Why every tile is a link ---------------------------------------------------------------
 * A count nobody can act on is decoration. Each tile navigates to the screen that clears it,
 * so "Budget approval required 3" is the beginning of doing the three, not a note about them.
 */

/** One pending-action definition: how to count it, where it goes, who clears it. */
const ACTIONS = [
  {
    key: 'budget',
    label: 'Budget approval required',
    icon: Wallet,
    who: 'Management or Finance',
    detail: 'Nothing can be sourced until the headcount and salary band are approved.',
    to: '/hrms/internal-requisitions',
    match: (r) => r.approval_status === 'Pending Budget Approval',
  },
  {
    key: 'hr',
    label: 'HR verification required',
    icon: ClipboardCheck,
    who: 'HR',
    detail: 'The role and its justification need checking before it goes for budget.',
    to: '/hrms/internal-requisitions',
    match: (r) => r.approval_status === 'Pending HR Verification',
  },
  {
    key: 'escalation',
    label: 'Escalation to clear',
    icon: AlertTriangle,
    who: 'the reporting line',
    detail: 'Raised above the sanctioned headcount, so it routes up the reporting line.',
    to: '/hrms/internal-requisitions',
    match: (r) => r.approval_status === 'Pending Escalation',
  },
  {
    key: 'scorecard',
    label: 'Scorecard approval required',
    icon: Target,
    who: 'the hiring manager',
    detail: 'The position scorecard is written and waiting for review.',
    to: '/hrms/scorecards',
    match: (r) => r.approval_status === 'Pending Scorecard Approval',
  },
  {
    key: 'interviews',
    label: 'Interviews pending',
    icon: CalendarDays,
    who: 'the panel',
    detail: 'Scheduled but not yet completed.',
    to: '/hrms/interviews',
    match: (r) => (r.interviews?.total || 0) > (r.interviews?.completed || 0),
    countOf: (r) => (r.interviews.total - r.interviews.completed),
  },
  {
    key: 'references',
    label: 'Reference checks pending',
    icon: PhoneCall,
    who: 'HR',
    detail: 'Somebody has been selected but no reference is on file. An internal offer is '
          + 'blocked until one is completed.',
    to: '/hrms/reference-checks',
    // Selected, but no offer has been raised yet -- the window in which the reference
    // check is the thing standing in the way.
    match: (r) => (r.candidates?.selected || 0) > 0 && !r.offer?.status,
  },
  {
    key: 'offers',
    label: 'Offers pending',
    icon: FileSignature,
    who: 'HR and the approver',
    detail: 'Raised but not yet accepted.',
    to: '/hrms/offers',
    match: (r) => r.offer?.status && !['Accepted', 'Declined', 'Withdrawn']
      .includes(r.offer.status),
  },
  {
    key: 'probation',
    label: 'Probation reviews due',
    icon: ShieldCheck,
    who: 'the hiring manager',
    detail: 'The probation period ends within 30 days and no decision is recorded.',
    to: '/hrms/probation',
    match: (r) => {
      if (!r.probation?.ends_on || r.probation.outcome !== 'Pending') return false;
      const ends = new Date(r.probation.ends_on);
      const in30 = new Date();
      in30.setDate(in30.getDate() + 30);
      return ends <= in30;
    },
  },
];

/** The tracker's own SLA vocabulary, rendered in words a reader recognises. There is no
 *  "at risk" state -- a milestone is running, met, or late -- so the chip does not invent one. */
const SLA_TONE = {
  breached: 'bad', on_track: 'good', met: 'good', not_started: 'neutral', unknown: 'neutral',
};
const SLA_LABEL = {
  breached: 'Overdue', on_track: 'On track', met: 'Met',
  not_started: 'Not started', unknown: 'Unknown',
};

const Tile = ({ label, value, tone = 'neutral' }) => (
  <div className={`${CARD} p-3.5`}>
    <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
      {label}
    </p>
    <p className={`mt-1 text-[22px] font-bold tabular-nums ${
      tone === 'bad' ? 'text-[var(--accent-red)]' : 'text-[var(--text-main)]'}`}>
      {value}
    </p>
  </div>
);

const InternalHiringDashboard = () => {
  const { scope, companyId } = useHrms();
  const navigate = useNavigate();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await getInternalTracker({ ...scope, limit: 200 });
      setRows(data?.rows || []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load internal hiring.');
    } finally {
      setLoading(false);
    }
    // `scope` is a fresh object literal on every HrmsContext render, so depending on it
    // here would rebuild `load` every render and re-run the effect for ever. Keyed on
    // the primitives instead, exactly as every other HRMS screen is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const pending = useMemo(
    () => ACTIONS.map((a) => {
      const hits = rows.filter(a.match);
      const count = a.countOf
        ? hits.reduce((sum, r) => sum + a.countOf(r), 0)
        : hits.length;
      return { ...a, count };
    }),
    [rows],
  );

  const headline = useMemo(() => {
    const open = rows.filter((r) => r.closing_status === 'Open');
    return {
      openPositions: open.length,
      seats: open.reduce((n, r) => n + (r.budget?.approved_headcount || r.vacancy || 1), 0),
      candidates: rows.reduce((n, r) => n + (r.candidates?.total || 0), 0),
      awaiting: rows.filter((r) => (r.approval_status || '').startsWith('Pending')).length,
      overdue: rows.filter((r) => r.sla?.status === 'breached').length,
    };
  }, [rows]);

  if (loading) return <HrmsLoading label="Loading internal hiring…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  const outstanding = pending.filter((p) => p.count > 0);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[19px] font-bold tracking-tight text-[var(--text-main)]">
          Internal hiring
        </h1>
        <p className="mt-0.5 text-[12.5px] text-[var(--text-muted)]">
          Sparsh Magic&rsquo;s own vacancies — no client involved.
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2.5">
        <Tile label="Open positions" value={headline.openPositions} />
        <Tile label="Seats to fill" value={headline.seats} />
        <Tile label="Awaiting approval" value={headline.awaiting} />
        <Tile label="Candidates" value={headline.candidates} />
        <Tile label="SLA overdue" value={headline.overdue}
              tone={headline.overdue ? 'bad' : 'neutral'} />
      </div>

      <section aria-labelledby="pending-heading">
        <h2 id="pending-heading"
            className="text-[10.5px] font-bold uppercase tracking-widest
                       text-[var(--text-muted)] mb-2">
          Pending actions
        </h2>
        {outstanding.length === 0 ? (
          <HrmsEmpty
            title="Nothing is waiting on anybody"
            hint="Every internal position is either approved and running, or closed."
          />
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {outstanding.map((a) => (
              <button
                key={a.key} type="button" onClick={() => navigate(a.to)}
                className={`${CARD} p-3.5 text-left flex items-start gap-3
                  hover:border-[var(--accent-indigo)] transition-colors`}
              >
                <span className="mt-0.5 h-8 w-8 shrink-0 rounded-lg bg-[var(--input-bg)]
                                 grid place-items-center">
                  <a.icon size={15} className="text-[var(--accent-indigo)]" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="text-[13px] font-bold text-[var(--text-main)]">
                      {a.label}
                    </span>
                    <Chip tone="accent">{a.count}</Chip>
                  </span>
                  <span className="block mt-0.5 text-[11.5px] text-[var(--text-muted)]">
                    {a.detail}
                  </span>
                  <span className="block mt-1 text-[11px] text-[var(--text-muted)]">
                    Cleared by {a.who}
                  </span>
                </span>
                <ArrowRight size={15} className="text-[var(--text-muted)] mt-1 shrink-0" />
              </button>
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="recent-heading">
        <h2 id="recent-heading"
            className="text-[10.5px] font-bold uppercase tracking-widest
                       text-[var(--text-muted)] mb-2">
          Internal positions
        </h2>
        {rows.length === 0 ? (
          <HrmsEmpty
            title="No internal requisitions yet"
            hint="Raise one on the Internal reqs screen. Sparsh Magic's own vacancies run
                  through HR verification, budget approval and a position scorecard before
                  sourcing begins."
          />
        ) : (
          <>
            {/* Cards on a phone, a table above it -- eight columns at 375px is unreadable
                however it is scrolled, and the fields that matter differ between the two. */}
            <ul className="md:hidden space-y-2">
              {rows.map((r) => (
                <li key={r.request_no}>
                  <button type="button"
                          onClick={() => navigate(`/hrms/internal-requisitions/${r.request_no}`)}
                          className={`${CARD} p-3.5 w-full text-left`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[13px] font-bold text-[var(--text-main)] truncate">
                          {r.designation_name || r.request_no}
                        </p>
                        <p className="text-[11px] text-[var(--text-muted)] truncate">
                          {r.department_name} · {r.request_no}
                        </p>
                      </div>
                      <Chip tone={r.sla?.status === 'breached' ? 'bad' : 'neutral'}>
                        {r.approval_status}
                      </Chip>
                    </div>
                    <p className="mt-1.5 text-[11.5px] text-[var(--text-muted)]">
                      {r.candidates?.total || 0} candidates ·
                      {' '}{r.budget?.approved ? 'budget approved' : 'budget pending'}
                      {r.required_date ? ` · needed ${day(r.required_date)}` : ''}
                    </p>
                  </button>
                </li>
              ))}
            </ul>

            <div className={`${CARD} hidden md:block overflow-hidden`}>
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="text-[10.5px] font-bold uppercase tracking-widest
                                 text-[var(--text-muted)] border-b border-[var(--border)]">
                    <th className="text-left px-3.5 py-2.5">Position</th>
                    <th className="text-left px-3.5 py-2.5">Department</th>
                    <th className="text-right px-3.5 py-2.5">Seats</th>
                    <th className="text-left px-3.5 py-2.5">Salary band</th>
                    <th className="text-left px-3.5 py-2.5">Stage</th>
                    <th className="text-right px-3.5 py-2.5">Candidates</th>
                    <th className="text-left px-3.5 py-2.5">SLA</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.request_no}
                        onClick={() => navigate(`/hrms/internal-requisitions/${r.request_no}`)}
                        className="border-b border-[var(--border)] last:border-0
                                   hover:bg-[var(--input-bg)] cursor-pointer">
                      <td className="px-3.5 py-2.5">
                        <span className="font-semibold text-[var(--text-main)]">
                          {r.designation_name || '—'}
                        </span>
                        <span className="block font-mono text-[11px] text-[var(--text-muted)]">
                          {r.request_no}
                        </span>
                      </td>
                      <td className="px-3.5 py-2.5 text-[var(--text-muted)]">
                        {r.department_name || '—'}
                      </td>
                      <td className="px-3.5 py-2.5 text-right tabular-nums">
                        {r.budget?.approved_headcount ?? r.vacancy ?? '—'}
                      </td>
                      <td className="px-3.5 py-2.5 text-[var(--text-muted)]">
                        {r.budget?.band_min != null
                          ? `${r.budget.band_min} – ${r.budget.band_max}`
                          : 'not approved'}
                      </td>
                      <td className="px-3.5 py-2.5">
                        <Chip tone={r.approval_status === 'Approved' ? 'good' : 'warn'}>
                          {r.approval_status}
                        </Chip>
                      </td>
                      <td className="px-3.5 py-2.5 text-right tabular-nums">
                        {r.candidates?.total || 0}
                      </td>
                      <td className="px-3.5 py-2.5">
                        <Chip tone={SLA_TONE[r.sla?.status] || 'neutral'}
                              title={r.sla?.status === 'breached'
                                ? (r.sla.breached_labels || []).join(', ')
                                : r.sla?.next_label
                                  ? `Next: ${r.sla.next_label}`
                                  : undefined}>
                          {SLA_LABEL[r.sla?.status] || 'Not started'}
                        </Chip>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  );
};

export default InternalHiringDashboard;
