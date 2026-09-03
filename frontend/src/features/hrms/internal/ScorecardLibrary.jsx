import React, { useCallback, useEffect, useState } from 'react';
import { Target, Plus, Trash2, CheckCircle2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getScorecards, createScorecard, approveScorecard, getRequisitions,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList, SignatureField,
} from './internalKit.jsx';

/**
 * HRMS ▸ internal track — position scorecards.
 *
 * What "good" looks like for one vacancy, agreed BEFORE anybody is interviewed. HR drafts,
 * the hiring manager approves, and Management approves as well for managerial roles.
 *
 * The builder shows a live weight breakdown as percentages. Weights do not have to sum to
 * anything — "SQL twice as important as culture fit" is the judgement being captured — but a
 * reader still wants to know what 3-2-1 actually means in practice, so the screen does that
 * arithmetic rather than leaving it to them.
 */

const CATEGORIES = [
  { value: 'skill', label: 'Skill' },
  { value: 'experience', label: 'Experience' },
  { value: 'culture_fit', label: 'Culture fit' },
];

const ScorecardLibrary = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [building, setBuilding] = useState(false);
  const [approving, setApproving] = useState(null);

  const canWrite = can(CAP.SCORECARD_WRITE);
  const canApprove = can(CAP.SCORECARD_APPROVE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getScorecards({ ...scope, limit: 200 });
      setRows(data?.scorecards || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load scorecards.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'scr', label: 'Scorecard',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.title || r.designation_name}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.scr_no} · {r.request_no}
          </span>
        </>
      ) },
    { key: 'criteria', label: 'Criteria',
      render: (r) => (
        <span className="text-[var(--text-muted)]">
          {(r.criteria || []).length} criteria
          {r.managerial ? ' · managerial' : ''}
        </span>
      ) },
    { key: 'created', label: 'Drafted',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">{r.created_by_name || '—'}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {day(r.created_at)}
          </span>
        </>
      ) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1.5">
          <Chip tone={toneFor(r.status)}>{r.status}</Chip>
          {r.status !== 'Approved' && canApprove && (
            <Btn tone="ghost" onClick={() => setApproving(r)}>Review</Btn>
          )}
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.title || r.designation_name}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.scr_no} · {r.request_no}
          </p>
        </div>
        <Chip tone={toneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'Criteria', value: (r.criteria || []).length },
        { label: 'Managerial', value: r.managerial ? 'Yes' : 'No' },
        { label: 'Drafted', value: day(r.created_at) },
      ]} />
      {r.status !== 'Approved' && canApprove && (
        <Btn tone="ghost" onClick={() => setApproving(r)}>Review</Btn>
      )}
    </div>
  );

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Target}
        title="Position scorecards"
        subtitle="The bar a role is hired against, agreed before sourcing begins"
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setBuilding(true)}>
            <Plus size={14} /> New scorecard
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading scorecards…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.scr_no}
          empty={<HrmsEmpty
            icon={Target}
            title="No scorecards yet"
            hint="An internal requisition cannot be approved until its scorecard is."
          />}
        />
      )}

      {building && (
        <ScorecardBuilder
          scope={scope}
          onClose={() => setBuilding(false)}
          onDone={() => { setBuilding(false); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}

      {approving && (
        <ApproveModal
          row={approving} scope={scope}
          onClose={() => setApproving(null)}
          onDone={() => { setApproving(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}
    </div>
  );
};

/** The builder. Criteria are rows you add and remove; the weight column shows what each one
 *  is actually worth as a share of the total, recomputed as you type. */
const ScorecardBuilder = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [reqs, setReqs] = useState([]);
  const [requestNo, setRequestNo] = useState('');
  const [title, setTitle] = useState('');
  const [managerial, setManagerial] = useState(false);
  const [notes, setNotes] = useState('');
  const [criteria, setCriteria] = useState([
    { label: '', category: 'skill', weight: 1, max_score: 5 },
  ]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getRequisitions({ ...scope, track: 'internal', limit: 200 })
      .then(({ data }) => setReqs(data?.requisitions || []))
      .catch(() => setReqs([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalWeight = criteria.reduce((sum, c) => sum + (Number(c.weight) || 0), 0);
  const setRow = (index, key, value) => setCriteria((rows) =>
    rows.map((row, i) => (i === index ? { ...row, [key]: value } : row)));

  const submit = async () => {
    const cleaned = criteria
      .map((c) => ({ ...c, label: c.label.trim(), weight: Number(c.weight) || 0 }))
      .filter((c) => c.label);
    if (!requestNo) { showError('Choose the requisition this scorecard is for.'); return; }
    if (!cleaned.length) { showError('Add at least one criterion.'); return; }
    if (cleaned.some((c) => c.weight <= 0)) {
      showError('Every criterion needs a weight greater than zero.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await createScorecard({
        request_no: requestNo, title: title.trim() || null, managerial,
        notes: notes.trim() || null, criteria: cleaned,
      }, scope);
      showSuccess(`${data.scr_no} drafted — it needs approval before sourcing`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not create the scorecard.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="New position scorecard" labelledBy="scr-build-title"
      subtitle="Weights express relative importance — they do not have to add up to anything"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Create'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="scr-req">Requisition *</label>
        <select id="scr-req" value={requestNo} className={FIELD}
          onChange={(e) => setRequestNo(e.target.value)}>
          <option value="">Select an internal requisition…</option>
          {reqs.map((r) => (
            <option key={r.request_no} value={r.request_no}>
              {r.request_no} — {r.designation_name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className={LABEL} htmlFor="scr-title">Title</label>
        <input id="scr-title" value={title} onChange={(e) => setTitle(e.target.value)}
          className={FIELD} placeholder="Defaults to the designation" />
      </div>

      <label className="flex items-start gap-2.5 cursor-pointer">
        <input type="checkbox" checked={managerial} className="mt-0.5"
          onChange={(e) => setManagerial(e.target.checked)} />
        <span>
          <span className="block text-[13px] font-semibold text-[var(--text-main)]">
            Managerial or above
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            Needs Management&rsquo;s approval as well as the hiring manager&rsquo;s — two
            different people.
          </span>
        </span>
      </label>

      <div className="space-y-2">
        <p className={LABEL}>Criteria *</p>
        {criteria.map((row, index) => (
          <div key={index}
            className="rounded-lg border border-[var(--border)] p-2.5 space-y-2">
            <div className="flex gap-2">
              <input
                aria-label={`Criterion ${index + 1} label`}
                value={row.label} className={FIELD} placeholder="e.g. SQL"
                onChange={(e) => setRow(index, 'label', e.target.value)}
              />
              <button type="button" aria-label={`Remove criterion ${index + 1}`}
                onClick={() => setCriteria((rows) => rows.filter((_, i) => i !== index))}
                disabled={criteria.length === 1}
                className="shrink-0 h-9 w-9 grid place-items-center rounded-lg
                  border border-[var(--border)] text-[var(--text-muted)]
                  hover:text-[var(--accent-red)] disabled:opacity-40">
                <Trash2 size={14} />
              </button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <select aria-label={`Criterion ${index + 1} category`}
                value={row.category} className={FIELD}
                onChange={(e) => setRow(index, 'category', e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
              <input type="number" min="0.5" step="0.5"
                aria-label={`Criterion ${index + 1} weight`}
                value={row.weight} className={FIELD}
                onChange={(e) => setRow(index, 'weight', e.target.value)} />
              <div className="grid place-items-center rounded-lg bg-[var(--input-bg)]
                text-[12px] font-bold text-[var(--text-muted)]">
                {totalWeight
                  ? `${Math.round(((Number(row.weight) || 0) / totalWeight) * 100)}%`
                  : '—'}
              </div>
            </div>
          </div>
        ))}
        <Btn onClick={() => setCriteria((rows) =>
          [...rows, { label: '', category: 'skill', weight: 1, max_score: 5 }])}>
          <Plus size={13} /> Add criterion
        </Btn>
      </div>

      <div>
        <label className={LABEL} htmlFor="scr-notes">Notes</label>
        <textarea id="scr-notes" rows={2} value={notes} className={TEXTAREA}
          onChange={(e) => setNotes(e.target.value)} />
      </div>
    </Modal>
  );
};

/** One approval signature. The dialog names who is still outstanding, so a managerial
 *  scorecard does not look stuck for no visible reason after the first signature. */
const ApproveModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [signature, setSignature] = useState('');
  const [remarks, setRemarks] = useState('');
  const [busy, setBusy] = useState(false);
  const outstanding = row.approval_state?.outstanding_roles || [];

  const decide = async (decision) => {
    if (!signature.trim()) { showError('Type your name to sign this approval.'); return; }
    if (decision === 'Fail' && !remarks.trim()) {
      showError('Say why it is being sent back, so HR can act on it.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await approveScorecard(row.scr_no,
        { decision, signature: signature.trim(), remarks: remarks.trim() }, scope);
      showSuccess(data.status === 'Approved'
        ? `${row.scr_no} approved`
        : `${row.scr_no} recorded — still waiting on `
          + `${(data.approval_state?.outstanding_roles || []).join(', ') || 'approval'}`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the approval.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Review ${row.scr_no}`} labelledBy="scr-approve-title"
      subtitle={row.title || row.designation_name} onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" onClick={() => decide('Fail')} disabled={busy}>Send back</Btn>
          <Btn tone="primary" onClick={() => decide('Pass')} disabled={busy}>
            <CheckCircle2 size={14} /> {busy ? 'Working…' : 'Approve'}
          </Btn>
        </>
      )}
    >
      <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
        <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          Criteria
        </p>
        <ul className="mt-2 space-y-1.5">
          {(row.criteria || []).map((c) => (
            <li key={c.label} className="flex items-baseline justify-between gap-3 text-[12.5px]">
              <span className="text-[var(--text-main)]">{c.label}</span>
              <span className="text-[var(--text-muted)] shrink-0">
                weight {c.weight} · out of {c.max_score}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {outstanding.length > 0 && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Still outstanding after this: <b>{outstanding.join(', ')}</b>. A managerial
          scorecard needs two different people.
        </p>
      )}

      <SignatureField id="scr-sign" value={signature} onChange={setSignature} />

      <div>
        <label className={LABEL} htmlFor="scr-remarks">
          Remarks (required to send back)
        </label>
        <textarea id="scr-remarks" rows={3} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

export default ScorecardLibrary;
