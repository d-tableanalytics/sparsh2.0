import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  ArrowLeft, Check, CircleDot, Circle, Users, Clock, ShieldCheck, Megaphone,
  AlertTriangle,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getRequisition, getRequisitionSla, getScorecards, getCandidates, actOnRequisition,
} from '../../../services/hrmsApi';
import { useNotification } from '../../../context/NotificationContext';
import ApprovalDialog from '../recruitment/ApprovalDialog';
import { CARD, day, money } from './internalKit';
import { Btn, Chip, Facts } from './internalKit.jsx';
import { REQUISITION_SOP_LABEL, sopLabelFor } from './sopLabels';

/**
 * HRMS ▸ internal hiring ▸ one position, end to end (spec §29).
 *
 * The queue shows what can be done to a requisition right now; the tracker shows every
 * requisition at once. Neither answers "tell me about THIS role" — which is what somebody
 * asks when they are about to approve it, staff it, or explain to a hiring manager why it
 * has not moved.
 *
 * -- The approval timeline ------------------------------------------------------------------
 * The centrepiece, because the internal track's whole shape is a sequence of gates and the
 * common question is which one it is sitting behind. It is derived from `approval_status`
 * and a few dated facts, NOT stored: a second copy of the state would be one more thing that
 * can disagree with the state machine in hrms_requisition_service.
 *
 * Steps after approval (recruitment, offer, joining, probation) are shown as progress rather
 * than as gates, because they are — nothing blocks on them in the way HR verification blocks
 * on HR.
 *
 * -- Composed from existing endpoints -------------------------------------------------------
 * Four reads that already exist, none of them new: the requisition, its SLA, its scorecard
 * and its candidates. There is no `/requisitions/{no}/everything`, deliberately — each of
 * these is already the authority on its own part, and a fifth endpoint stitching them
 * together would be a fifth thing to keep in step.
 */

/** Gates, in SOP order, each with the status that means "waiting here". */
const GATES = [
  { key: 'hr', label: 'HR verification', waiting: 'Pending HR Verification',
    who: 'HR checks the role and its justification.' },
  { key: 'budget', label: 'Budget approval', waiting: 'Pending Budget Approval',
    who: 'Management or Finance approve the headcount and the salary band.' },
  { key: 'escalation', label: 'Escalation', waiting: 'Pending Escalation',
    who: 'Raised above the sanctioned headcount, so it routes up the reporting line.',
    // Only ever shown when it actually happened -- most requisitions never escalate.
    conditional: true },
  { key: 'scorecard', label: 'Scorecard approval', waiting: 'Pending Scorecard Approval',
    who: 'The hiring manager approves the criteria candidates will be scored against.' },
];

const AFTER = [
  { key: 'recruitment', label: 'Recruitment' },
  { key: 'offer', label: 'Offer' },
  { key: 'joining', label: 'Joining' },
  { key: 'probation', label: 'Probation' },
];

const Step = ({ state, label, note }) => {
  const Icon = state === 'done' ? Check : state === 'current' ? CircleDot : Circle;
  const tone = state === 'done' ? 'text-[var(--accent-green)]'
    : state === 'current' ? 'text-[var(--accent-indigo)]'
      : 'text-[var(--text-muted)]';
  return (
    <li className="flex gap-2.5">
      <Icon size={15} className={`${tone} shrink-0 mt-0.5`} />
      <div className="min-w-0 pb-2.5">
        <p className={`text-[12.5px] font-semibold ${
          state === 'todo' ? 'text-[var(--text-muted)]' : 'text-[var(--text-main)]'}`}>
          {label}
        </p>
        {note && <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">{note}</p>}
      </div>
    </li>
  );
};

const InternalRequisitionDetail = () => {
  const { requestNo } = useParams();
  const navigate = useNavigate();
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [gateOpen, setGateOpen] = useState(false);
  const [gateBusy, setGateBusy] = useState(false);
  const [req, setReq] = useState(null);
  const [sla, setSla] = useState(null);
  const [scorecard, setScorecard] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!companyId || !requestNo) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await getRequisition(requestNo, scope);
      setReq(data);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load this requisition.');
      setLoading(false);
      return;
    }
    // The rest are supporting detail: a caller without `scorecard.read` still gets the
    // page, minus the section they may not see.
    const optional = [
      [() => getRequisitionSla(requestNo, scope), (d) => setSla(d)],
      [() => getScorecards({ ...scope, request_no: requestNo }),
        (d) => setScorecard((d?.scorecards || [])[0] || null)],
      [() => getCandidates({ ...scope, request_no: requestNo, limit: 200 }),
        (d) => setCandidates(d?.candidates || [])],
    ];
    await Promise.all(optional.map(async ([call, set]) => {
      try { const { data } = await call(); set(data); } catch { /* section stays empty */ }
    }));
    setLoading(false);
    // `scope` is a fresh object literal on every HrmsContext render, so depending on it
    // here would rebuild `load` every render and re-run the effect for ever. Keyed on
    // the primitives instead, exactly as every other HRMS screen is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, requestNo]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <HrmsLoading label={`Loading ${requestNo}…`} />;
  if (error) return <HrmsError message={error} onRetry={load} />;
  if (!req) return <HrmsEmpty title="Not found" hint={`No requisition ${requestNo}.`} />;

  const status = req.approval_status;
  // The server refuses the gate unless an APPROVED scorecard exists (assert_scorecard_approved),
  // so the screen reads the same condition rather than offering a button that 422s.
  const scorecardReady = scorecard?.status === 'Approved';

  const clearGate = async (action, remarks) => {
    setGateBusy(true);
    try {
      await actOnRequisition(requestNo, { action, remarks }, scope);
      showSuccess(action === 'scorecard-approve'
        ? `${requestNo} approved — ${req.jd_no || 'its JD'} is now publishable.`
        : `${requestNo} sent back.`);
      setGateOpen(false);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the decision.');
    } finally {
      setGateBusy(false);
    }
  };
  const approved = status === 'Approved';
  const rejected = status === 'Rejected';

  // A gate is DONE if the requisition has moved past the point of waiting for it. The order
  // in GATES is the order they fall due, so "past" is simply "earlier in the list".
  const waitingAt = GATES.findIndex((g) => g.waiting === status);
  const gateState = (i) => {
    if (rejected) return waitingAt === i ? 'current' : i < waitingAt ? 'done' : 'todo';
    if (approved) return 'done';
    if (waitingAt === -1) return 'todo';
    return i < waitingAt ? 'done' : i === waitingAt ? 'current' : 'todo';
  };

  const joined = candidates.filter(
    (c) => ['Joined', 'Employee Created', 'Probation Confirmed']
      .includes(c.application_status)).length;
  const offered = candidates.filter(
    (c) => ['Offer Generated', 'Offer Accepted', 'Appointment Letter Sent']
      .includes(c.application_status)).length;
  const confirmed = candidates.filter(
    (c) => c.application_status === 'Probation Confirmed').length;

  const afterState = (key) => {
    if (!approved) return 'todo';
    if (key === 'recruitment') {
      return candidates.length === 0 ? 'current' : offered || joined ? 'done' : 'current';
    }
    if (key === 'offer') return joined ? 'done' : offered ? 'current' : 'todo';
    if (key === 'joining') return joined ? 'done' : offered ? 'current' : 'todo';
    if (key === 'probation') {
      return confirmed ? 'done' : joined ? 'current' : 'todo';
    }
    return 'todo';
  };

  const band = req.approved_salary_band_min != null
    ? `${money(req.approved_salary_band_min)} – ${money(req.approved_salary_band_max)}`
    : null;

  return (
    <div className="space-y-4">
      <button type="button" onClick={() => navigate('/hrms/internal-requisitions')}
              className="inline-flex items-center gap-1.5 text-[12px] font-bold
                         text-[var(--text-muted)] hover:text-[var(--text-main)]">
        <ArrowLeft size={14} /> Internal requisitions
      </button>

      {/* Position header */}
      <div className={`${CARD} p-4`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-[19px] font-bold tracking-tight text-[var(--text-main)]">
              {req.designation_name || req.job_title || requestNo}
            </h1>
            <p className="mt-0.5 text-[12.5px] text-[var(--text-muted)]">
              {[req.department_name,
                `${req.approved_headcount ?? req.vacancy ?? 1} position`
                  + ((req.approved_headcount ?? req.vacancy ?? 1) === 1 ? '' : 's'),
                band].filter(Boolean).join(' · ')}
            </p>
            <p className="mt-0.5 font-mono text-[11px] text-[var(--text-muted)]">
              {requestNo}
            </p>
          </div>
          <div className="text-right">
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              <Chip tone="accent">Internal hiring</Chip>
              <Chip tone={approved ? 'good' : rejected ? 'bad' : 'warn'}>{status}</Chip>
              {req.closing_status && req.closing_status !== 'Open' && (
                <Chip tone="neutral">{req.closing_status}</Chip>
              )}
            </div>
            {sopLabelFor(status, REQUISITION_SOP_LABEL) && (
              <p className="mt-1 text-[10.5px] text-[var(--text-muted)] italic">
                SOP: {sopLabelFor(status, REQUISITION_SOP_LABEL)}
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          {/* Overview */}
          <section className={`${CARD} p-4`}>
            <h2 className="text-[10.5px] font-bold uppercase tracking-widest
                           text-[var(--text-muted)] mb-2.5">Overview</h2>
            <Facts items={[
              { label: 'Raised by', value: req.created_by_name },
              { label: 'Raised on', value: req.created_at ? day(req.created_at) : null },
              { label: 'HR owner', value: req.assignee_name },
              { label: 'Needed by',
                value: req.required_date ? day(req.required_date) : null },
              { label: 'Employment type', value: req.employment_type },
              { label: 'Location', value: req.location },
              { label: 'Experience', value: req.experience },
              { label: 'Priority', value: req.priority },
              { label: 'Approved headcount', value: req.approved_headcount },
              { label: 'Approved band', value: band },
              { label: 'Budget approved by', value: req.budget_approved_by_name },
              { label: 'Budget approved on',
                value: req.budget_approved_at ? day(req.budget_approved_at) : null },
            ]} />
            {req.justification && (
              <div className="mt-3 pt-3 border-t border-[var(--border)]">
                <p className="text-[10.5px] font-bold uppercase tracking-widest
                              text-[var(--text-muted)]">Hiring justification</p>
                <p className="mt-1 text-[12.5px] text-[var(--text-main)]">
                  {req.justification}
                </p>
              </div>
            )}
          </section>

          {/* Over sanction, and what happened about it. The snapshot is stored at each
              approval so the approver sees the figures the decision rested on; the note is
              written only when the ladder could NOT be built, which is the case most worth
              surfacing — an escalation that was skipped for want of a reporting line. */}
          {(req.escalation_note || req.sanction_snapshot?.is_over_sanction) && (
            <section className={`${CARD} p-4 border-[var(--accent-orange)]`}>
              <h2 className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase
                             tracking-widest text-[var(--accent-orange)] mb-2">
                <AlertTriangle size={13} /> Over sanctioned strength
              </h2>
              {req.sanction_snapshot && (
                <p className="text-[12.5px] text-[var(--text-main)]">
                  {req.sanction_snapshot.actual} filled
                  {' '}· {req.sanction_snapshot.open_requisitions} committed
                  {' '}· {req.sanction_snapshot.requested} requested
                  {' '}against {req.sanction_snapshot.sanctioned == null
                    ? 'no sanctioned figure'
                    : `a sanctioned strength of ${req.sanction_snapshot.sanctioned}`}.
                </p>
              )}
              {req.escalation_note && (
                <p className="mt-1.5 text-[12.5px] text-[var(--accent-orange)]">
                  {req.escalation_note}
                </p>
              )}
              {req.escalation_note && (
                <p className="mt-1.5 text-[11.5px] text-[var(--text-muted)]">
                  Give the raiser a reporting manager if this should have gone up a line —
                  the ladder is built from it, and an escalation cannot be rebuilt after the
                  budget gate has been cleared.
                </p>
              )}
            </section>
          )}

          {/* Scorecard */}
          {can(CAP.SCORECARD_READ) && (
            <section className={`${CARD} p-4`}>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <h2 className="text-[10.5px] font-bold uppercase tracking-widest
                               text-[var(--text-muted)]">Position scorecard</h2>
                {scorecard && (
                  <Chip tone={scorecard.status === 'Approved' ? 'good' : 'warn'}>
                    {scorecard.status}
                  </Chip>
                )}
              </div>
              {!scorecard ? (
                <p className="text-[12px] text-[var(--text-muted)]">
                  None yet. Candidates cannot be scored against this role until HR writes
                  the criteria and the hiring manager approves them.{' '}
                  <Link to="/hrms/scorecards"
                        className="font-bold text-[var(--accent-indigo)]">
                    Go to Scorecards
                  </Link>
                </p>
              ) : (
                <>
                  <p className="font-mono text-[11px] text-[var(--text-muted)] mb-2">
                    {scorecard.scr_no}
                  </p>
                  <ul className="space-y-2">
                    {(scorecard.criteria || []).map((c) => (
                      <li key={c.label} className="text-[12.5px]">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="text-[var(--text-main)] font-semibold">{c.label}</span>
                          <span className="text-[var(--text-muted)] whitespace-nowrap">
                            weight {c.weight}
                            {Number(c.max_score) !== 5 ? ` · out of ${c.max_score}` : ''}
                          </span>
                        </div>
                        {c.expected_level && (
                          <p className="text-[11.5px] text-[var(--text-main)]">
                            Expected: {c.expected_level}
                          </p>
                        )}
                        {c.evaluation_criteria && (
                          <p className="text-[11.5px] text-[var(--text-muted)]">{c.evaluation_criteria}</p>
                        )}
                        {c.remarks && (
                          <p className="text-[11px] italic text-[var(--text-muted)]">Remarks: {c.remarks}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          )}

          {/* ── The final scorecard GATE ──
              Deliberately its own section, below the scorecard it depends on. The two were
              being read as one thing: signing SCR-xxxx sets the bar, and this approves the
              REQUISITION and publishes its JD. Same word, different object, different
              screen — so this says which is which, shows whether the precondition is met,
              and is the only place on this page that can move the requisition. */}
          {can(CAP.SCORECARD_APPROVE) && status === 'Pending Scorecard Approval' && (
            <section className={`${CARD} p-4 border-[var(--accent-indigo)]`}>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <h2 className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase
                               tracking-widest text-[var(--accent-indigo)]">
                  <ShieldCheck size={13} /> Final scorecard gate
                </h2>
                <Chip tone={scorecardReady ? 'good' : 'warn'}>
                  {scorecardReady ? 'Ready to approve' : 'Blocked'}
                </Chip>
              </div>

              {/* What this action does, as three facts rather than a sentence people skim. */}
              <ol className="space-y-1.5 text-[12.5px] mb-3">
                <li className="flex items-start gap-2">
                  <Check size={14} className={scorecardReady
                    ? 'mt-0.5 shrink-0 text-[var(--accent-green)]'
                    : 'mt-0.5 shrink-0 text-[var(--text-muted)]'} />
                  <span>
                    <b>Scorecard {scorecardReady ? 'approved' : 'not approved yet'}</b>
                    {scorecard ? ` — ${scorecard.scr_no}` : ''}
                    <span className="block text-[11.5px] text-[var(--text-muted)]">
                      Signed on the Scorecards page. That approval sets the bar; it does not
                      approve this requisition.
                    </span>
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <CircleDot size={14} className="mt-0.5 shrink-0 text-[var(--accent-indigo)]" />
                  <span>
                    <b>Approve the requisition</b> — this action
                    <span className="block text-[11.5px] text-[var(--text-muted)]">
                      The last gate in the chain. HR verified it, Finance or Management paid
                      for it; you are agreeing this is the right bar to hire against.
                    </span>
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <Megaphone size={14} className="mt-0.5 shrink-0 text-[var(--text-muted)]" />
                  <span>
                    <b>The JD becomes publishable</b>
                    <span className="block text-[11.5px] text-[var(--text-muted)]">
                      {req.jd_no ? `${req.jd_no} is approved automatically in the same step` : 'Its JD is approved automatically in the same step'}
                      {' '}— there is no separate JD approval — and it then appears in
                      &ldquo;Create a job posting&rdquo;.
                    </span>
                  </span>
                </li>
              </ol>

              {scorecardReady ? (
                <Btn tone="primary" onClick={() => setGateOpen(true)} disabled={gateBusy}>
                  <ShieldCheck size={14} /> {gateBusy ? 'Working…' : 'Approve requisition'}
                </Btn>
              ) : (
                <p className="text-[12px] text-[var(--text-muted)]">
                  {scorecard
                    ? 'The scorecard is drafted but not approved yet, so this gate is refused.'
                    : 'No position scorecard exists for this requisition yet, so this gate is refused.'}{' '}
                  <Link to="/hrms/scorecards" className="font-bold text-[var(--accent-indigo)]">
                    Go to Scorecards
                  </Link>
                </p>
              )}
            </section>
          )}

          {/* The other half of the same story: once the gate is cleared, say so, and say
              what it produced. "Approved" on its own left people wondering whether the JD
              needed approving too — it does not, and this is where that is answered. */}
          {status === 'Approved' && (
            <section className={`${CARD} p-4`}>
              <div className="flex items-center justify-between gap-2 mb-2">
                <h2 className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase
                               tracking-widest text-[var(--text-muted)]">
                  <ShieldCheck size={13} /> Final scorecard gate
                </h2>
                <Chip tone="good">Cleared</Chip>
              </div>
              <p className="text-[12.5px] text-[var(--text-main)]">
                The requisition is approved{req.approved_by_name ? ` by ${req.approved_by_name}` : ''}
                {req.scorecard_approved_at || req.approved_at
                  ? ` on ${day(req.scorecard_approved_at || req.approved_at)}` : ''}.
                {' '}{req.jd_no ? `${req.jd_no} was approved` : 'Its JD was approved'} in the
                same step — no separate JD approval — so the role can be advertised.
              </p>
              {can(CAP.POSTING_READ) && (
                <Link to="/hrms/postings"
                      className="inline-flex items-center gap-1.5 mt-2 text-[12px] font-bold
                                 text-[var(--accent-indigo)]">
                  <Megaphone size={13} /> Create a job posting
                </Link>
              )}
            </section>
          )}

          {/* Candidates */}
          <section className={`${CARD} p-4`}>
            <div className="flex items-center justify-between gap-2 mb-2.5">
              <h2 className="text-[10.5px] font-bold uppercase tracking-widest
                             text-[var(--text-muted)]">Candidates</h2>
              <Chip tone="neutral">{candidates.length}</Chip>
            </div>
            {candidates.length === 0 ? (
              <p className="text-[12px] text-[var(--text-muted)]">
                {approved
                  ? 'None sourced yet.'
                  : 'None — and none can be added until this requisition is approved. '
                    + 'The budget gate is enforced on the server, not by hiding a button.'}
              </p>
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {candidates.map((c) => (
                  <li key={c.uk} className="py-2 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[12.5px] font-semibold text-[var(--text-main)]
                                    truncate">
                        {c.candidate_name}
                      </p>
                      <p className="font-mono text-[11px] text-[var(--text-muted)]">
                        {c.uk}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {c.scorecard_score != null && (
                        <Chip tone={c.scorecard_score >= 4 ? 'good'
                          : c.scorecard_score >= 3 ? 'warn' : 'bad'}>
                          {c.scorecard_score} / 5
                        </Chip>
                      )}
                      <Chip tone="neutral">{c.application_status}</Chip>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* Right rail: the timeline and the SLA */}
        <div className="space-y-3">
          <section className={`${CARD} p-4`}>
            <h2 className="text-[10.5px] font-bold uppercase tracking-widest
                           text-[var(--text-muted)] mb-3">Approval timeline</h2>
            <ol>
              {GATES.map((g, i) => {
                const state = gateState(i);
                // An escalation that never happened is noise on the timeline.
                if (g.conditional && state === 'todo' && status !== g.waiting) return null;
                return (
                  <Step key={g.key} state={state} label={g.label}
                        note={state === 'current' ? g.who : null} />
                );
              })}
              {AFTER.map((a) => (
                <Step key={a.key} state={afterState(a.key)} label={a.label} />
              ))}
            </ol>
            {rejected && (
              <p className="mt-1 text-[11.5px] text-[var(--accent-red)]">
                This requisition was rejected{req.rejection_reason
                  ? `: ${req.rejection_reason}` : '.'}
              </p>
            )}
          </section>

          <section className={`${CARD} p-4`}>
            <h2 className="text-[10.5px] font-bold uppercase tracking-widest
                           text-[var(--text-muted)] mb-2.5 flex items-center gap-1.5">
              <Clock size={12} /> SLA
            </h2>
            {!sla?.milestones?.length ? (
              <p className="text-[12px] text-[var(--text-muted)]">
                No milestones measured yet.
              </p>
            ) : (
              <>
                <ul className="space-y-2">
                  {sla.milestones.map((m) => (
                    <li key={m.key} className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[12px] text-[var(--text-main)]">{m.label}</p>
                        {m.due_on && (
                          <p className="text-[11px] text-[var(--text-muted)]">
                            due {day(m.due_on)}
                            {m.target_working_days != null
                              ? ` · ${m.target_working_days} working days` : ''}
                          </p>
                        )}
                      </div>
                      <Chip tone={m.status === 'breached' || m.status === 'overdue' ? 'bad'
                        : m.status === 'met' ? 'good' : 'neutral'}>
                        {m.status === 'breached' || m.status === 'overdue'
                          ? `${m.working_days_over || 0}d over`
                          : m.status === 'met' ? 'Met'
                            : m.status === 'pending' ? 'Running' : 'Not started'}
                      </Chip>
                    </li>
                  ))}
                </ul>
                {sla.basis && (
                  <p className="mt-2.5 pt-2.5 border-t border-[var(--border)]
                                text-[11px] text-[var(--text-muted)]">
                    {sla.basis}
                  </p>
                )}
              </>
            )}
          </section>

          <section className={`${CARD} p-4`}>
            <h2 className="text-[10.5px] font-bold uppercase tracking-widest
                           text-[var(--text-muted)] mb-2.5 flex items-center gap-1.5">
              <Users size={12} /> Pipeline
            </h2>
            <Facts items={[
              { label: 'Candidates', value: candidates.length },
              { label: 'Offered', value: offered },
              { label: 'Joined', value: joined },
              { label: 'Confirmed', value: confirmed },
            ]} />
          </section>
        </div>
      </div>

      {/* The same dialog the queue board uses for this gate — one approval dialog, so the
          two entry points cannot ask for different things or word the decision differently. */}
      {gateOpen && (
        <ApprovalDialog
          title={`Approve requisition — ${requestNo}`}
          subtitle={'The final scorecard gate. The position scorecard is already signed off; '
            + 'this approves the requisition itself and makes its JD publishable.'}
          approveLabel="Approve requisition"
          rejectLabel="Send back"
          busy={gateBusy}
          requisition={req}
          onApprove={(remarks) => clearGate('scorecard-approve', remarks)}
          onReject={(remarks) => clearGate('scorecard-reject', remarks)}
          onClose={() => setGateOpen(false)}
        />
      )}
    </div>
  );
};

export default InternalRequisitionDetail;
