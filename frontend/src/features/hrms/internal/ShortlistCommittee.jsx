import React, { useCallback, useEffect, useState } from 'react';
import { Users2, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getShortlistReviews, createShortlistReview, updateShortlistReview,
  getRequisitions, getCandidates, getEmployees,
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

const OUTCOMES = ['Pending', 'Finalised', 'Deferred'];

const ShortlistCommittee = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [pending, setPending] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [outcome, setOutcome] = useState('');
  const [convening, setConvening] = useState(false);
  const [deciding, setDeciding] = useState(null);
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
      key: 'outcome',
      label: 'Outcome',
      render: (r) => (
        <Chip tone={r.outcome === 'Finalised' ? 'good'
          : r.outcome === 'Pending' ? 'warn' : 'neutral'}>
          {r.outcome}
        </Chip>
      ),
    },
    { key: 'decided', label: 'Decided', render: (r) => day(r.decided_at) },
    {
      key: 'act',
      label: '',
      align: 'right',
      render: (r) => (canWrite && r.outcome === 'Pending' ? (
        <Btn onClick={() => setDeciding(r)}>Decide</Btn>
      ) : null),
    },
  ];

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Users2}
        title="Shortlisting committee"
        subtitle="HR and the Department Head jointly finalise the shortlist before the final interview (SOP section 5)."
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setConvening(true)}>
            <Plus size={14} /> Convene
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {pending > 0 && (
        <div className="rounded-xl border border-[var(--accent-orange)]/30
          bg-[var(--accent-orange-bg)] px-4 py-3">
          <p className="text-[12.5px] font-semibold text-[var(--accent-orange)]">
            {pending} sitting{pending === 1 ? '' : 's'} convened and not yet decided.
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            A candidate cannot reach Selected until a sitting has finalised them.
          </p>
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
                <Chip tone={r.outcome === 'Finalised' ? 'good'
                  : r.outcome === 'Pending' ? 'warn' : 'neutral'}>
                  {r.outcome}
                </Chip>
              </div>
              <Facts items={[
                { label: 'Candidates', value: (r.candidate_uks || []).length },
                { label: 'Members', value: r.committee_state?.member_count },
                { label: 'Decided', value: day(r.decided_at) },
              ]} />
              {canWrite && r.outcome === 'Pending' && (
                <Btn onClick={() => setDeciding(r)}>Decide</Btn>
              )}
            </div>
          )}
        />
      )}

      {convening && (
        <ConveneModal
          scope={scope}
          busy={busy}
          setBusy={setBusy}
          onClose={() => setConvening(false)}
          onDone={() => { setConvening(false); load(); showSuccess('Sitting convened.'); }}
          onError={(m) => showError(m)}
        />
      )}

      {deciding && (
        <DecideModal
          review={deciding}
          busy={busy}
          onClose={() => setDeciding(null)}
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

/** Convene a sitting: pick the requisition, the candidates on it and who sat. */
const ConveneModal = ({ scope, busy, setBusy, onClose, onDone, onError }) => {
  const [reqs, setReqs] = useState([]);
  const [people, setPeople] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [requestNo, setRequestNo] = useState('');
  const [picked, setPicked] = useState([]);
  const [members, setMembers] = useState([]);
  const [notes, setNotes] = useState('');

  useEffect(() => {
    getRequisitions({ ...scope, track: 'internal' })
      .then(({ data }) => setReqs(data?.requisitions || []))
      .catch(() => setReqs([]));
    getEmployees(scope)
      .then(({ data }) => setPeople(data?.employees || []))
      .catch(() => setPeople([]));
  }, [scope]);

  useEffect(() => {
    if (!requestNo) { setCandidates([]); setPicked([]); return; }
    getCandidates({ ...scope, request_no: requestNo })
      .then(({ data }) => setCandidates(data?.candidates || []))
      .catch(() => setCandidates([]));
  }, [requestNo, scope]);

  const toggle = (list, setList, value) =>
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const submit = async () => {
    setBusy(true);
    try {
      await createShortlistReview({
        request_no: requestNo,
        candidate_uks: picked,
        committee_members: members.map((user_id) => ({ user_id, decision: 'Agree' })),
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
      title="Convene a shortlisting committee"
      subtitle="Convening decides nothing. Finalise it once the committee has agreed."
      labelledBy="slr-convene"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !requestNo || !members.length}
            onClick={submit}>
            Convene
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="slr-req">Requisition *</label>
        <select id="slr-req" className={FIELD} value={requestNo}
          onChange={(e) => setRequestNo(e.target.value)}>
          <option value="">Choose an internal requisition</option>
          {reqs.map((r) => (
            <option key={r.request_no} value={r.request_no}>
              {r.request_no} — {r.designation_name}
            </option>
          ))}
        </select>
      </div>

      {!!candidates.length && (
        <div>
          <span className={LABEL}>Candidates</span>
          <div className="space-y-1.5 max-h-52 overflow-y-auto">
            {candidates.map((c) => (
              <label key={c.uk}
                className="flex items-center gap-2.5 text-[12.5px] text-[var(--text-main)]">
                <input type="checkbox" checked={picked.includes(c.uk)}
                  onChange={() => toggle(picked, setPicked, c.uk)} />
                <span className="flex-1 min-w-0 truncate">{c.candidate_name}</span>
                {/* The evidence, beside the name. Advice, never a decision. */}
                {c.scorecard_band && (
                  <Chip tone={toneFor(c.scorecard_band)} title="Scoring decision guide">
                    {c.scorecard_score} · {c.scorecard_band}
                  </Chip>
                )}
              </label>
            ))}
          </div>
        </div>
      )}

      <div>
        <span className={LABEL}>Committee members *</span>
        <p className="text-[11px] text-[var(--text-muted)] mb-1.5">
          SOP section 5 needs HR and the Department Head — two different people. The server
          checks the roles; it will not accept one person covering both.
        </p>
        <div className="space-y-1.5 max-h-40 overflow-y-auto">
          {people.map((p) => (
            <label key={p.user_id}
              className="flex items-center gap-2.5 text-[12.5px] text-[var(--text-main)]">
              <input type="checkbox" checked={members.includes(p.user_id)}
                onChange={() => toggle(members, setMembers, p.user_id)} />
              <span className="truncate">{p.display_name || p.full_name || p.email}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className={LABEL} htmlFor="slr-notes">Notes</label>
        <textarea id="slr-notes" rows={3} className={TEXTAREA} value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What the committee weighed up." />
      </div>
    </Modal>
  );
};

/** Record the outcome. Finalising is what lifts the gate on `Selected`. */
const DecideModal = ({ review, busy, onClose, onSubmit }) => {
  const [value, setValue] = useState('Finalised');
  const state = review.committee_state || {};
  return (
    <Modal
      title={`Decide ${review.slr_no}`}
      subtitle="A decided sitting is frozen. A second decision is a second sitting."
      labelledBy="slr-decide"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => onSubmit(value)}>
            Record
          </Btn>
        </>
      )}
    >
      <Facts items={[
        { label: 'Requisition', value: review.request_no },
        { label: 'Candidates', value: (review.candidate_uks || []).length },
        { label: 'Members', value: state.member_count },
        { label: 'Roles covered', value: (state.covered_roles || []).join(', ') },
      ]} />

      {!state.complete && (
        <p className="text-[12px] text-[var(--accent-orange)] font-semibold">
          Still needed: {(state.outstanding_roles || []).join(', ')}. A sitting can only be
          finalised once the committee is complete.
        </p>
      )}
      {!!(state.objections || []).length && (
        <p className="text-[12px] text-[var(--accent-orange)]">
          Objection recorded by {state.objections.join(', ')}.
        </p>
      )}

      <div>
        <label className={LABEL} htmlFor="slr-outcome-pick">Outcome</label>
        <select id="slr-outcome-pick" className={FIELD} value={value}
          onChange={(e) => setValue(e.target.value)}>
          <option value="Finalised">
            Finalised — these candidates go to the final interview
          </option>
          <option value="Deferred">
            Deferred — more sourcing needed, nobody progresses
          </option>
        </select>
      </div>
    </Modal>
  );
};

export default ShortlistCommittee;
