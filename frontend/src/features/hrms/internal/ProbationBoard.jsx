import React, { useCallback, useEffect, useState } from 'react';
import { CalendarClock, FileCheck2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getProbations, getProbationsDue, confirmProbation, closePersonnelFile,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList, SignatureField,
} from './internalKit.jsx';

/**
 * HRMS ▸ internal track — probation reviews.
 *
 * Probation is an EMPLOYEE event, not a recruitment stage: the candidate pipeline ends at
 * joining. That is why this screen lives in the sidebar with the other governance surfaces
 * rather than in the hiring tab strip.
 *
 * OVERDUE and DUE SOON are shown as two separate groups because they are two different
 * conversations — a missed commitment and a diary entry. One date-sorted list leaves the
 * reader to work out which is which, which is exactly the work a screen should do for them.
 */

const OUTCOMES = ['Confirmed', 'Extended', 'Terminated'];

const ProbationBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [due, setDue] = useState(null);
  const [all, setAll] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [closing, setClosing] = useState(null);

  const canDecide = can(CAP.PROBATION_CONFIRM);
  const canCloseFile = can(CAP.PERSONNEL_FILE_CLOSE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const [dueRes, allRes] = await Promise.all([
        getProbationsDue({ ...scope, within_days: 30 }),
        getProbations({ ...scope, limit: 200 }),
      ]);
      setDue(dueRes.data);
      setAll(allRes.data?.probation_reviews || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load probation reviews.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.employee_name || r.employee_code}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.employee_code} · {r.prb_no}
          </span>
        </>
      ) },
    { key: 'period', label: 'Period',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">{day(r.started_on)}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.duration_months} month{r.duration_months === 1 ? '' : 's'}
            {r.extension_count ? ` · extended ${r.extension_count}×` : ''}
          </span>
        </>
      ) },
    { key: 'ends', label: 'Ends',
      render: (r) => <span className="text-[var(--text-main)]">{day(r.ends_on)}</span> },
    { key: 'rating', label: 'Rating', align: 'right',
      render: (r) => (
        <span className="text-[var(--text-muted)]">{r.rating ?? '—'}</span>
      ) },
    { key: 'outcome', label: 'Outcome', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1.5">
          <Chip tone={toneFor(r.outcome)}>{r.outcome}</Chip>
          {r.outcome === 'Pending' && canDecide && (
            <Btn tone="ghost" onClick={() => setConfirming(r)}>Review</Btn>
          )}
          {r.outcome === 'Confirmed' && canCloseFile && (
            <Btn tone="ghost" onClick={() => setClosing(r)}>
              <FileCheck2 size={13} /> Close file
            </Btn>
          )}
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.employee_name || r.employee_code}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.employee_code} · {r.prb_no}
          </p>
        </div>
        <Chip tone={toneFor(r.outcome)}>{r.outcome}</Chip>
      </div>
      <Facts items={[
        { label: 'Started', value: day(r.started_on) },
        { label: 'Ends', value: day(r.ends_on) },
        { label: 'Rating', value: r.rating ?? '—' },
      ]} />
      <div className="flex gap-2">
        {r.outcome === 'Pending' && canDecide && (
          <Btn tone="ghost" onClick={() => setConfirming(r)}>Review</Btn>
        )}
        {r.outcome === 'Confirmed' && canCloseFile && (
          <Btn tone="ghost" onClick={() => setClosing(r)}>Close file</Btn>
        )}
      </div>
    </div>
  );

  const Group = ({ title, hint, rows, tone }) => (
    rows?.length ? (
      <section className="space-y-2.5">
        <div>
          <h2 className="text-[13.5px] font-bold text-[var(--text-main)] flex items-center gap-2">
            {title} <Chip tone={tone}>{rows.length}</Chip>
          </h2>
          {hint && <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">{hint}</p>}
        </div>
        <RecordList rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.prb_no} />
      </section>
    ) : null
  );

  const decided = all.filter((r) => r.outcome !== 'Pending');

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={CalendarClock}
        title="Probation"
        subtitle="Confirmation decisions for internal joiners. Opened automatically when somebody joins."
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading probation reviews…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <>
          <Group
            title="Overdue" tone="bad" rows={due?.overdue}
            hint="Past the probation end date with no decision recorded."
          />
          <Group
            title="Due soon" tone="warn" rows={due?.due_soon}
            hint="Falling due in the next 30 days."
          />
          <Group title="Decided" tone="neutral" rows={decided} />

          {!due?.overdue?.length && !due?.due_soon?.length && !decided.length && (
            <HrmsEmpty
              icon={CalendarClock}
              title="No probation reviews yet"
              hint="One opens automatically when an internal joiner is issued an Employee ID."
            />
          )}
        </>
      )}

      {confirming && (
        <ConfirmModal
          row={confirming} scope={scope}
          onClose={() => setConfirming(null)}
          onDone={() => { setConfirming(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}

      {closing && (
        <CloseFileModal
          row={closing} scope={scope}
          onClose={() => setClosing(null)}
          onDone={() => { setClosing(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}
    </div>
  );
};

/** Confirm, extend or end. An extension is more time, not a verdict — the review returns to
 *  Pending with a later date, which the copy says outright so nobody expects it to close. */
const ConfirmModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [outcome, setOutcome] = useState('Confirmed');
  const [rating, setRating] = useState(row.rating ?? '');
  const [extendedTo, setExtendedTo] = useState('');
  const [remarks, setRemarks] = useState('');
  const [signature, setSignature] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!signature.trim()) {
      showError('Type your name to sign this decision.');
      return;
    }
    if (outcome === 'Extended' && !extendedTo) {
      showError('An extension needs a new end date.');
      return;
    }
    if (outcome !== 'Confirmed' && !remarks.trim()) {
      showError(`Record why the probation is being ${outcome.toLowerCase()}.`);
      return;
    }
    setBusy(true);
    try {
      await confirmProbation(row.prb_no, {
        outcome,
        rating: rating === '' ? null : Number(rating),
        extended_to: outcome === 'Extended' ? extendedTo : null,
        remarks: remarks.trim(),
        signature: signature.trim(),
      }, scope);
      showSuccess(outcome === 'Extended'
        ? `${row.prb_no} extended to ${extendedTo} — it returns to the due list`
        : `${row.prb_no} ${outcome.toLowerCase()}`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the decision.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Probation review — ${row.employee_name || row.employee_code}`}
      labelledBy="prb-confirm-title"
      subtitle={`${row.prb_no} · ends ${day(row.ends_on)}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Working…' : 'Record decision'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="prb-outcome">Outcome *</label>
        <select id="prb-outcome" value={outcome} className={FIELD}
          onChange={(e) => setOutcome(e.target.value)}>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        {outcome === 'Extended' && (
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            An extension is more time, not a verdict — the review reopens with the new date
            and appears in the due list again.
          </p>
        )}
        {outcome === 'Confirmed' && (
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Confirming also closes the requisition as Hired. There is no client handover on
            this track.
          </p>
        )}
      </div>

      {outcome === 'Extended' && (
        <div>
          <label className={LABEL} htmlFor="prb-extended">New end date *</label>
          <input id="prb-extended" type="date" value={extendedTo} className={FIELD}
            onChange={(e) => setExtendedTo(e.target.value)} />
        </div>
      )}

      <div>
        <label className={LABEL} htmlFor="prb-rating">Rating (1–5, optional)</label>
        <input id="prb-rating" type="number" min="1" max="5" step="0.1" value={rating}
          className={FIELD} onChange={(e) => setRating(e.target.value)} />
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          The same 1–5 scale as the position scorecard.
        </p>
      </div>

      <div>
        <label className={LABEL} htmlFor="prb-remarks">
          Remarks {outcome === 'Confirmed' ? '' : '*'}
        </label>
        <textarea id="prb-remarks" rows={3} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>

      <SignatureField id="prb-sign" value={signature} onChange={setSignature}
        hint="This decision ends or extends somebody's employment." />
    </Modal>
  );
};

/** Personnel-file closure. Only offered once probation is confirmed, which the server also
 *  enforces — the file is closed when the confirmation is on record, not before. */
const CloseFileModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!note.trim()) {
      showError('Record what was checked. An empty closure note closes nothing.');
      return;
    }
    setBusy(true);
    try {
      await closePersonnelFile(
        { employee_code: row.employee_code, closure_note: note.trim() }, scope);
      showSuccess(`Personnel file closed for ${row.employee_code}`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not close the personnel file.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Close the personnel file" labelledBy="prb-close-title"
      subtitle={`${row.employee_name || row.employee_code} · ${row.employee_code}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Close file'}
          </Btn>
        </>
      )}
    >
      <p className="text-[12.5px] text-[var(--text-muted)]">
        The file is the offer, joining documents, verification reports and the probation
        confirmation. What is recorded here is that somebody checked the set is complete.
      </p>
      <div>
        <label className={LABEL} htmlFor="prb-note">Closure note *</label>
        <textarea id="prb-note" rows={4} value={note} className={TEXTAREA}
          placeholder="Offer, joining documents, BGV and confirmation all filed."
          onChange={(e) => setNote(e.target.value)} />
      </div>
    </Modal>
  );
};

export default ProbationBoard;
