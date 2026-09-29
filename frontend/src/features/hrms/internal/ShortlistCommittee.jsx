import React, { useCallback, useEffect, useState } from 'react';
import { Users2, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import { useAuth } from '../../../context/AuthContext';
import {
  getShortlistReviews, getShortlistReview, createShortlistReview, updateShortlistReview,
  getShortlistAwaiting, getCommitteeOptions, recordShortlistVerdict,
  getRequisitions, getCandidates,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from './internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from './internalKit.jsx';

/**
 * HRMS ▸ internal track — the shortlisting committee (SOP §5).
 *
 * "HR and the Department Head shall jointly finalise the shortlist before the final
 * interview."
 *
 * The screen leads with what is PENDING, for the same reason the exception log does: a
 * sitting that was convened and never decided is a hire stalled and a control in limbo at
 * the same time.
 *
 * -- The two rules are shown, not just enforced --------------------------------------
 * A committee needs HR AND the Department Head, and two DIFFERENT people. The server
 * refuses a finalisation that does not meet both; this screen says which is outstanding
 * while the record is being assembled, so nobody meets the rule for the first time as a 422.
 *
 * -- The score is beside the name ------------------------------------------------------
 * Each candidate carries their weighted scorecard result and its band, so the committee
 * decides on the evidence rather than on who is remembered most vividly. The band is
 * advice: nothing here moves anybody, and finalising a candidate the guide bands as Reject
 * is a decision the committee is allowed to make and is recorded making.
 */

// Filter values only. 'Finalised' and 'Deferred' are how sittings were recorded before
// Final Commit; they can still be searched for, but never chosen (see DecideModal).
const OUTCOMES = ['Pending', 'Selected', 'Rejected', 'Final Interview Required',
  'Finalised', 'Deferred'];

const GOOD_OUTCOMES = ['Selected', 'Finalised'];

const outcomeTone = (outcome) => (GOOD_OUTCOMES.includes(outcome) ? 'good'
  : outcome === 'Rejected' ? 'bad'
    : outcome === 'Pending' ? 'warn' : 'neutral');

const ShortlistCommittee = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [pending, setPending] = useState(0);
  const [awaitingMe, setAwaitingMe] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [outcome, setOutcome] = useState('');
  const [convening, setConvening] = useState(false);
  const [deciding, setDeciding] = useState(null);
  // Interviewed and not yet decided -- who this page exists to move forward.
  const [awaiting, setAwaiting] = useState([]);
  // Senior / managerial candidates the committee put forward: the MD decides after the
  // Management interview.
  const [forMd, setForMd] = useState([]);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.SHORTLIST_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getShortlistReviews({
        ...scope, outcome: outcome || undefined,
      });
      setRows(data?.shortlist_reviews || []);
      setPending(data?.pending ?? 0);
      setAwaitingMe(data?.awaiting_me ?? 0);
      const waiting = await getShortlistAwaiting(scope).catch(() => null);
      setAwaiting(waiting?.data?.candidates || []);
      setForMd(waiting?.data?.final_commit || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the committee record.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, outcome]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    {
      key: 'slr',
      label: 'Sitting',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.slr_no}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.request_no}
          </span>
        </>
      ),
    },
    {
      key: 'candidates',
      label: 'Candidates',
      render: (r) => (
        <span className="text-[var(--text-main)]">
          {(r.candidate_uks || []).length}
        </span>
      ),
    },
    {
      key: 'committee',
      label: 'Committee',
      render: (r) => {
        const state = r.committee_state || {};
        return state.complete
          ? <Chip tone="good">{state.covered_roles?.join(' + ')}</Chip>
          : (
            <Chip tone="warn" title="SOP section 5 needs HR and the Department Head, and two different people.">
              needs {state.outstanding_roles?.join(', ') || 'a committee'}
            </Chip>
          );
      },
    },
    {
      key: 'mine',
      label: 'Your part',
      render: (r) => (r.my_verdict === 'Pending' ? <Chip tone="warn">Your approval needed</Chip>
        : r.my_verdict === 'Agree' ? <Chip tone="good">You approved</Chip>
          : r.my_verdict === 'Object' ? <Chip tone="bad">You did not approve</Chip>
            : <span className="text-[11.5px] text-[var(--text-muted)]">{r.i_convened ? 'You convened it' : '—'}</span>),
    },
    {
      key: 'outcome',
      label: 'Outcome',
      render: (r) => (
        <Chip tone={outcomeTone(r.outcome)}>{r.outcome}</Chip>
      ),
    },
    { key: 'decided', label: 'Decided', render: (r) => day(r.decided_at) },
    {
      key: 'act',
      label: '',
      align: 'right',
      render: (r) => (
        <Btn tone={r.outcome === 'Pending' && r.my_verdict === 'Pending' ? 'primary' : 'ghost'}
          onClick={() => setDeciding(r)}>
          {r.outcome === 'Pending' && r.my_verdict === 'Pending' ? 'Give your verdict' : 'Open'}
        </Btn>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Users2}
        title="Shortlisting committee"
        subtitle="Junior / mid roles: after the panel interview, HR and the HOD decide together. Senior / managerial roles skip the committee — the MD decides after the Management interview."
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setConvening(true)}>
            <Plus size={14} /> Convene
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {awaitingMe > 0 && (
        <div className="rounded-xl border border-[var(--accent-indigo)]/30 bg-[var(--accent-indigo-bg)] px-4 py-3">
          <p className="text-[12.5px] font-semibold text-[var(--accent-indigo)]">
            {awaitingMe} sitting{awaitingMe === 1 ? ' is' : 's are'} waiting for your approval.
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            Open it with “Give your verdict” below. Only you can approve for yourself; the decision
            records once every member has answered.
          </p>
        </div>
      )}
      {pending > awaitingMe && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          {pending - awaitingMe} other sitting{pending - awaitingMe === 1 ? ' is' : 's are'} still waiting for another member’s verdict.
        </p>
      )}

      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
        <div className="px-4 py-3 border-b border-[var(--border)]">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            Waiting for the committee{awaiting.length ? ` (${awaiting.length})` : ''}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            Candidates who passed their panel interview. HR and the HOD decide on them together,
            using the scoring guide: 4.0+ strong · 3.0–3.99 consider / hold · below 3.0 reject.
          </p>
        </div>
        {!awaiting.length ? (
          <p className="px-4 py-3 text-[12px] text-[var(--text-muted)]">
            Nobody is waiting — candidates appear here once their panel interview is recorded as a Pass.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {awaiting.map((c) => (
              <li key={c.uk} className="px-4 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold text-[var(--text-main)]">
                    {c.candidate_name} <span className="text-[11px] font-normal text-[var(--text-muted)]">{c.uk}</span>
                  </p>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    {c.designation_name || c.request_no} · {c.request_no}
                    {c.designation_level ? ` · ${c.designation_level}` : ''}
                    {' · '}{c.round} {c.interview_no} — {c.outcome}
                  </p>
                </div>
                <Chip tone={c.band === 'Strong' ? 'good' : c.band === 'Reject' ? 'bad' : 'warn'}
                  title="Interview score (average of the panel's ratings) and its band in the scoring guide">
                  {c.average_score != null ? `${c.average_score} · ${c.band}` : 'not scored'}
                </Chip>
                {c.pending_slr_no ? (
                  <Chip tone="warn" title="A sitting naming this candidate is convened and not yet decided">
                    in {c.pending_slr_no} — decide it below
                  </Chip>
                ) : canWrite && (
                  <Btn tone="primary" onClick={() => setConvening({ requestNo: c.request_no, uks: [c.uk] })}>
                    Convene committee
                  </Btn>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {forMd.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
          <div className="px-4 py-3 border-b border-[var(--border)]">
            <p className="text-[13px] font-bold text-[var(--text-main)]">
              Waiting for the MD&apos;s final decision ({forMd.length})
            </p>
            <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
              Senior / managerial roles. They passed the Panel Interview, so the MD interviews them
              (Management interview) and records the final decision on the Interviews page —
              Approve makes them Selected. No committee is needed for these roles.
            </p>
          </div>
          <ul className="divide-y divide-[var(--border)]">
            {forMd.map((c) => (
              <li key={c.uk} className="px-4 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold text-[var(--text-main)]">
                    {c.candidate_name} <span className="text-[11px] font-normal text-[var(--text-muted)]">{c.uk}</span>
                  </p>
                  <p className="text-[11px] text-[var(--text-muted)]">{c.designation_name || c.request_no} · {c.request_no}</p>
                </div>
                <Chip tone={c.interview_no ? (c.interview_status === 'Completed' ? 'good' : 'neutral') : 'warn'}>
                  {!c.interview_no
                    ? 'Management interview not booked yet'
                    : c.interview_status === 'Completed'
                      ? `${c.interview_no} done — ${c.outcome || 'MD to record the decision'}`
                      : `${c.interview_no} booked for ${day(c.scheduled_at)}`}
                </Chip>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <label className={LABEL} htmlFor="slr-outcome">Outcome</label>
        <select id="slr-outcome" className={`${FIELD} w-auto`} value={outcome}
          onChange={(e) => setOutcome(e.target.value)}>
          <option value="">All</option>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>

      {loading && <HrmsLoading label="Loading committee sittings…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty
          icon={Users2}
          title="No committee sittings yet"
          hint="Convene one to record who agreed which candidates go to the final interview."
        />
      )}
      {!loading && !error && !!rows.length && (
        <RecordList
          rows={rows}
          columns={columns}
          keyOf={(r) => r.slr_no}
          renderCard={(r) => (
            <div className="space-y-2.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-[13px] text-[var(--text-main)]">
                    {r.slr_no}
                  </p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">{r.request_no}</p>
                </div>
                <Chip tone={outcomeTone(r.outcome)}>{r.outcome}</Chip>
              </div>
              <Facts items={[
                { label: 'Candidates', value: (r.candidate_uks || []).length },
                { label: 'Members', value: r.committee_state?.member_count },
                { label: 'Decided', value: day(r.decided_at) },
              ]} />
              <Btn tone={r.outcome === 'Pending' && r.my_verdict === 'Pending' ? 'primary' : 'ghost'}
                onClick={() => setDeciding(r)}>
                {r.outcome === 'Pending' && r.my_verdict === 'Pending' ? 'Give your verdict' : 'Open'}
              </Btn>
            </div>
          )}
        />
      )}

      {convening && (
        <ConveneModal
          initial={typeof convening === 'object' ? convening : null}
          scope={scope}
          busy={busy}
          setBusy={setBusy}
          onClose={() => setConvening(false)}
          onDone={() => { setConvening(false); load(); showSuccess('Sitting convened — each member has been asked for their approval.'); }}
          onError={(m) => showError(m)}
        />
      )}

      {deciding && (
        <DecideModal
          review={deciding}
          scope={scope}
          busy={busy}
          onError={showError}
          onVerdict={(doc) => {
            if (doc?.outcome && doc.outcome !== 'Pending') {
              showSuccess(`Everyone has answered — ${deciding.slr_no} is ${doc.outcome}.`);
              setDeciding(null);
            } else {
              showSuccess('Your verdict is recorded. Waiting for the other members.');
            }
            load();
          }}
          onClose={() => { setDeciding(null); load(); }}
          onSubmit={async (value) => {
            setBusy(true);
            try {
              await updateShortlistReview(deciding.slr_no, { outcome: value }, scope);
              showSuccess(`${deciding.slr_no} recorded as ${value}.`);
              setDeciding(null);
              load();
            } catch (err) {
              showError(err?.response?.data?.detail
                || 'The decision could not be recorded.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
    </div>
  );
};

/** One numbered block of the convene form (module-level so inputs keep focus). */
const Step = ({ n, title, hint, right, children }) => (
  <section className="space-y-2">
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-[12.5px] font-bold text-[var(--text-main)]">
          <span className="h-5 w-5 grid place-items-center rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[10.5px]">{n}</span>
          {title}
        </p>
        {hint && <p className="mt-0.5 ml-7 text-[11px] text-[var(--text-muted)]">{hint}</p>}
      </div>
      {right}
    </div>
    <div className="ml-7">{children}</div>
  </section>
);

const COMMITTEE_SEATS = [['hr', 'HR'], ['manager', 'HOD / Manager']];

/** Convene a sitting: pick the vacancy, the candidates on it and who sits. */
const ConveneModal = ({ initial, scope, busy, setBusy, onClose, onDone, onError }) => {
  const [reqs, setReqs] = useState([]);
  const [people, setPeople] = useState([]);
  const [candidates, setCandidates] = useState([]);
  // The panel's result per candidate (from "Waiting for the committee").
  const [evidence, setEvidence] = useState({});
  // Opened from "Waiting for the committee": the vacancy and the candidate come pre-filled.
  const [requestNo, setRequestNo] = useState(initial?.requestNo || '');
  const [picked, setPicked] = useState(initial?.uks || []);
  const [members, setMembers] = useState([]);
  const [notes, setNotes] = useState('');

  useEffect(() => {
    getRequisitions({ ...scope })
      // A committee sits on the INTERNAL track only.
      .then(({ data }) => setReqs((data?.requisitions || [])
        .filter((r) => !r.requisition_track || r.requisition_track === 'internal')))
      .catch(() => setReqs([]));
    // Only the people who can sit: HR and HOD / Managers, by name.
    getCommitteeOptions(scope)
      .then(({ data }) => setPeople(data?.people || []))
      .catch(() => setPeople([]));
    getShortlistAwaiting(scope)
      .then(({ data }) => setEvidence(Object.fromEntries(
        (data?.candidates || []).map((c) => [c.uk, c]))))
      .catch(() => setEvidence({}));
  }, [scope]);

  useEffect(() => {
    if (!requestNo) { setCandidates([]); setPicked([]); return; }
    const prefilled = initial?.requestNo;
    setPicked((p) => (prefilled === requestNo ? p : []));
    getCandidates({ ...scope, request_no: requestNo })
      .then(({ data }) => setCandidates(data?.candidates || []))
      .catch(() => setCandidates([]));
  }, [requestNo, scope, initial?.requestNo]);

  const toggle = (list, setList, value) =>
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const byId = Object.fromEntries(people.map((p) => [p.user_id, p]));
  const seated = new Set(members.map((id) => byId[id]?.role).filter(Boolean));
  const seatsMissing = COMMITTEE_SEATS.filter(([r]) => !seated.has(r)).map(([, l]) => l);
  const interviewed = candidates.filter((c) => evidence[c.uk]);
  const req = reqs.find((r) => r.request_no === requestNo);

  const blockers = [
    !requestNo && 'choose the vacancy',
    requestNo && !picked.length && 'tick at least one candidate',
    seatsMissing.length > 0 && `add ${seatsMissing.join(' and ')} to the committee`,
  ].filter(Boolean);

  const submit = async () => {
    setBusy(true);
    try {
      await createShortlistReview({
        request_no: requestNo,
        candidate_uks: picked,
        // Nobody is pre-approved: each member gives their own verdict afterwards.
        committee_members: members.map((user_id) => ({ user_id, decision: 'Pending' })),
        outcome: 'Pending',
        notes,
      }, scope);
      onDone();
    } catch (err) {
      onError(err?.response?.data?.detail || 'The sitting could not be convened.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      wide
      title="Convene a shortlisting committee"
      subtitle="Each member you add is asked for their own approval. Nothing is decided until every member has answered."
      labelledBy="slr-convene"
      onClose={onClose}
      footer={(
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <p className="text-[11.5px] text-[var(--text-muted)] min-w-0">
            {blockers.length
              ? <>To convene: {blockers.join(', ')}.</>
              : <span className="font-semibold text-[var(--accent-green,#16a34a)]">
                Ready — {picked.length} candidate{picked.length === 1 ? '' : 's'}, {members.length} member{members.length === 1 ? '' : 's'}.
              </span>}
          </p>
          <div className="flex gap-2 ml-auto">
            <Btn onClick={onClose}>Cancel</Btn>
            <Btn tone="primary" disabled={busy || blockers.length > 0} onClick={submit}>
              {busy ? 'Convening…' : 'Convene'}
            </Btn>
          </div>
        </div>
      )}
    >
      <Step n="1" title="Vacancy">
        <select id="slr-req" className={FIELD} value={requestNo}
          onChange={(e) => setRequestNo(e.target.value)}>
          <option value="">Choose an internal vacancy…</option>
          {reqs.map((r) => (
            <option key={r.request_no} value={r.request_no}>
              {r.designation_name || 'Untitled role'} — {r.request_no}
            </option>
          ))}
        </select>
        {req?.department_name && (
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">{req.department_name}</p>
        )}
      </Step>

      <Step n="2" title="Candidates to decide on"
        hint="The panel's interview score is beside each name — 4.0+ strong · 3.0–3.99 consider / hold · below 3.0 reject. It is advice; the committee decides."
        right={interviewed.length > 1 && (
          <button type="button" onClick={() => setPicked(interviewed.map((c) => c.uk))}
            className="shrink-0 text-[11px] font-bold text-[var(--accent-indigo)]">
            Tick all interviewed
          </button>
        )}>
        {!requestNo ? (
          <p className="text-[12px] text-[var(--text-muted)]">Choose the vacancy first.</p>
        ) : !candidates.length ? (
          <p className="text-[12px] text-[var(--text-muted)]">No candidates on this vacancy.</p>
        ) : (
          <div className="rounded-xl border border-[var(--border)] divide-y divide-[var(--border)] max-h-56 overflow-y-auto">
            {candidates.map((c) => {
              const ev = evidence[c.uk];
              const on = picked.includes(c.uk);
              return (
                <label key={c.uk}
                  className={`flex items-center gap-3 px-3 py-2 cursor-pointer ${on ? 'bg-[var(--accent-indigo-bg)]' : ''}`}>
                  <input type="checkbox" checked={on} onChange={() => toggle(picked, setPicked, c.uk)} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-semibold text-[var(--text-main)]">{c.candidate_name}</span>
                    <span className="block text-[11px] text-[var(--text-muted)]">
                      {c.uk} · {c.application_status}
                      {ev ? ` · ${ev.round} ${ev.interview_no} — ${ev.outcome}` : ''}
                    </span>
                  </span>
                  {ev ? (
                    <Chip tone={ev.band === 'Strong' ? 'good' : ev.band === 'Reject' ? 'bad' : 'warn'}
                      title="Interview score and its band in the scoring guide">
                      {ev.average_score != null ? `${ev.average_score} · ${ev.band}` : 'not scored'}
                    </Chip>
                  ) : c.scorecard_band ? (
                    <Chip tone={toneFor(c.scorecard_band)} title="Scoring decision guide">
                      {c.scorecard_score} · {c.scorecard_band}
                    </Chip>
                  ) : (
                    <span className="text-[11px] text-[var(--text-muted)]">not interviewed yet</span>
                  )}
                </label>
              );
            })}
          </div>
        )}
      </Step>

      <Step n="3" title="Committee members"
        hint="One from HR and one HOD / Manager — two different people. The server checks the roles."
        right={(
          <span className={`shrink-0 text-[11px] font-bold px-2 py-0.5 rounded-full ${seatsMissing.length
            ? 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]'
            : 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,#16a34a)]'}`}>
            {seatsMissing.length ? `Needed: ${seatsMissing.join(', ')}` : 'Committee complete'}
          </span>
        )}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {COMMITTEE_SEATS.map(([role, title]) => {
            const inSeat = people.filter((p) => p.role === role);
            return (
              <div key={role} className="rounded-lg bg-[var(--input-bg)] p-2 space-y-1.5">
                <p className="flex items-center justify-between text-[10.5px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                  {title}
                  <span className={seated.has(role) ? 'text-[var(--accent-green,#16a34a)]' : 'text-[var(--accent-orange)]'}>
                    {seated.has(role) ? '✓ set' : 'needed'}
                  </span>
                </p>
                {!inSeat.length && <p className="text-[11px] text-[var(--text-muted)]">Nobody with this role</p>}
                {inSeat.map((p) => (
                  <label key={p.user_id}
                    className={`flex items-center gap-2 rounded-md border px-2 py-1.5 text-[12.5px] cursor-pointer bg-[var(--bg-card)] ${
                      members.includes(p.user_id) ? 'border-[var(--accent-indigo)]' : 'border-transparent'}`}>
                    <input type="checkbox" checked={members.includes(p.user_id)}
                      onChange={() => toggle(members, setMembers, p.user_id)} />
                    <span className="font-semibold text-[var(--text-main)] break-words">{p.name}</span>
                  </label>
                ))}
              </div>
            );
          })}
        </div>
      </Step>

      <Step n="4" title="Notes (optional)">
        <textarea id="slr-notes" rows={2} className={TEXTAREA} value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What the committee weighed up — strengths, concerns, comparisons." />
      </Step>
    </Modal>
  );
};

/**
 * Final Commit — record each member's verdict; the outcome follows from them.
 *
 * There is deliberately no outcome dropdown. Selected, Rejected and Final Interview Required
 * are CONSEQUENCES, not choices: they follow from what each approver said and how senior the
 * role is. Offering a menu asked the committee for a conclusion instead of the facts behind
 * it, which is how a sitting could once be recorded as agreed over a Head's objection.
 *
 * What the menu HID, and what this modal now exposes, is the input. Convening stamped every
 * member as agreeing and there was nowhere at all to say otherwise, so "Rejected" was
 * unreachable through the interface however the backend behaved. The verdict controls below
 * are that missing input, and the member picker is how an inquorate sitting gets fixed
 * without abandoning it.
 *
 * Changes are saved as they are made and the preview is then re-read FROM THE SERVER. The
 * rule is never re-implemented here: a predicted outcome that disagreed with the recorded
 * one would be worse than no prediction at all.
 */
const VERDICT_CHIP = {
  Agree: ['good', 'Approved'], Object: ['bad', 'Did not approve'], Pending: ['warn', 'Waiting'],
};

const DecideModal = ({ review, scope, busy, onClose, onSubmit, onError, onVerdict }) => {
  const { user } = useAuth();
  const me = String(user?._id || '');
  const [full, setFull] = useState(null);
  const [people, setPeople] = useState([]);
  const [adding, setAdding] = useState('');
  const [saving, setSaving] = useState(false);
  const [loadErr, setLoadErr] = useState(null);
  const [reason, setReason] = useState('');
  const [objecting, setObjecting] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await getShortlistReview(review.slr_no, scope);
      setFull(data || null);
      setLoadErr(null);
    } catch (err) {
      setLoadErr(err?.response?.data?.detail || 'Could not load this sitting.');
    }
  }, [review.slr_no, scope]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    getCommitteeOptions(scope)
      .then(({ data }) => setPeople(data?.people || []))
      .catch(() => setPeople([]));
  }, [scope]);

  const members = full?.committee_members || [];
  const state = full?.committee_state || review.committee_state || {};
  const preview = full?.commit_preview || null;
  const uks = full?.candidate_uks || review.candidate_uks || [];
  const decided = (full?.outcome || review.outcome) !== 'Pending';
  const iConvened = String(full?.convened_by || review.convened_by || '') === me;
  const waitingIds = state.awaiting_ids || [];
  // A member's own answer counts; a verdict stamped by whoever convened (old sittings) does not.
  const verdictOf = (m) => (waitingIds.includes(String(m.user_id)) ? 'Pending' : m.decision);
  const mine = members.find((m) => String(m.user_id) === me);
  const myTurn = !decided && mine && !mine.recused && verdictOf(mine) === 'Pending';

  const give = async (decision) => {
    setSaving(true);
    try {
      const { data } = await recordShortlistVerdict(review.slr_no,
        { decision, remarks: decision === 'Object' ? reason.trim() : undefined }, scope);
      setFull(data);
      setObjecting(false);
      setReason('');
      onVerdict?.(data);
    } catch (err) {
      onError(err?.response?.data?.detail || 'Your verdict could not be recorded.');
    } finally {
      setSaving(false);
    }
  };

  /** Convener only: change who sits. Existing answers are kept by the server. */
  const saveMembers = async (next) => {
    setSaving(true);
    try {
      await updateShortlistReview(review.slr_no, {
        committee_members: next.map((m) => ({ user_id: m.user_id, decision: 'Pending', recused: !!m.recused })),
      }, scope);
      await load();
    } catch (err) {
      onError(err?.response?.data?.detail || 'Could not update the committee.');
    } finally {
      setSaving(false);
    }
  };

  const unpicked = people.filter((p) => !members.some((m) => String(m.user_id) === String(p.user_id)));
  const working = busy || saving;
  const everyoneAnswered = !waitingIds.length && state.complete;

  return (
    <Modal
      title={`Committee approval — ${review.slr_no}`}
      subtitle={decided
        ? `Decided: ${full?.outcome || review.outcome}. A decided sitting is frozen.`
        : 'Each member approves for themselves. The decision records once everyone has answered.'}
      labelledBy="slr-decide"
      onClose={onClose}
      footer={(
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {decided ? 'This sitting is closed.'
              : waitingIds.length ? `Waiting for: ${(state.awaiting || []).join(', ')}.`
                : !state.complete ? `Still needed on the committee: ${(state.outstanding_roles || []).join(', ')}.`
                  : 'Everyone has answered.'}
          </p>
          <div className="flex gap-2 ml-auto">
            <Btn onClick={onClose} disabled={working}>Close</Btn>
            {/* Only when everyone has answered but it was not recorded (e.g. an older sitting). */}
            {!decided && everyoneAnswered && preview?.outcome && mine && (
              <Btn tone={preview.outcome === 'Rejected' ? 'danger' : 'primary'} disabled={working}
                onClick={() => onSubmit(preview.outcome)}>
                Record {preview.outcome}
              </Btn>
            )}
          </div>
        </div>
      )}
    >
      <Facts items={[
        { label: 'Requisition', value: review.request_no },
        { label: 'Candidates', value: uks.join(', ') || '—' },
        { label: 'Role level', value: preview?.designation_level || '—' },
      ]} />

      {myTurn && (
        <div className="rounded-xl border border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] p-3 space-y-2">
          <p className="text-[13px] font-bold text-[var(--accent-indigo)]">Your verdict is needed</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            Do you approve {uks.length === 1 ? 'this candidate' : 'these candidates'} going forward?
            Only you can answer for yourself.
          </p>
          {objecting ? (
            <>
              <textarea rows={2} className={TEXTAREA} value={reason} autoFocus
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why not? This goes on record (required)." />
              <div className="flex gap-2">
                <Btn tone="danger" disabled={working || !reason.trim()} onClick={() => give('Object')}>
                  Confirm: do not approve
                </Btn>
                <Btn disabled={working} onClick={() => setObjecting(false)}>Back</Btn>
              </div>
            </>
          ) : (
            <div className="flex gap-2">
              <Btn tone="primary" disabled={working} onClick={() => give('Agree')}>Approve</Btn>
              <Btn disabled={working} onClick={() => setObjecting(true)}>Do not approve</Btn>
            </div>
          )}
        </div>
      )}

      <div>
        <p className={LABEL}>Committee members</p>
        <div className="mt-1.5 space-y-1.5">
          {members.map((m) => {
            const v = verdictOf(m);
            const [tone, text] = VERDICT_CHIP[v] || ['neutral', v];
            const isMe = String(m.user_id) === me;
            return (
              <div key={m.user_id}
                className={`flex items-start justify-between gap-3 rounded-lg border px-3 py-2 ${isMe ? 'border-[var(--accent-indigo)]' : 'border-[var(--border)]'}`}>
                <div className="min-w-0">
                  <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                    {m.name || m.user_id}{isMe ? ' (you)' : ''}
                  </p>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    {m.role === 'hr' ? 'HR' : m.role === 'manager' ? 'HOD / Manager' : (m.role || 'no HRMS role')}
                    {m.recused ? ' · recused' : ''}
                  </p>
                  {v === 'Object' && m.remarks && (
                    <p className="mt-1 text-[11.5px] text-[var(--text-main)]">“{m.remarks}”</p>
                  )}
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <Chip tone={tone}>{text}</Chip>
                  {iConvened && !decided && !isMe && (
                    <Btn disabled={working} onClick={() => saveMembers(members.filter((x) => x.user_id !== m.user_id))}>
                      Remove
                    </Btn>
                  )}
                </div>
              </div>
            );
          })}
          {!members.length && (
            <p className="text-[12px] text-[var(--text-muted)]">Nobody is on this committee yet.</p>
          )}
        </div>

        {iConvened && !decided && (
          <div className="mt-2 flex items-center gap-2">
            <select className={FIELD} value={adding} aria-label="Add a committee member"
              onChange={(e) => setAdding(e.target.value)}>
              <option value="">Add a member (they will be asked)…</option>
              {unpicked.map((p) => (
                <option key={p.user_id} value={p.user_id}>{p.name} — {p.role_label}</option>
              ))}
            </select>
            <Btn disabled={working || !adding}
              onClick={() => { saveMembers([...members, { user_id: adding }]); setAdding(''); }}>
              Add
            </Btn>
          </div>
        )}
      </div>

      {loadErr && <p className="text-[12px] text-[var(--accent-red,var(--accent-orange))]">{loadErr}</p>}

      {preview?.outcome && !decided && (
        <div>
          <p className={LABEL}>{everyoneAnswered ? 'This sitting decides' : 'If everyone keeps their current answer'}</p>
          <div className="flex items-center gap-2 mt-1">
            <Chip tone={outcomeTone(preview.outcome)}>{preview.outcome}</Chip>
            <span className="text-[12px] text-[var(--text-muted)]">{preview.because}</span>
          </div>
        </div>
      )}
    </Modal>
  );
};

export default ShortlistCommittee;
