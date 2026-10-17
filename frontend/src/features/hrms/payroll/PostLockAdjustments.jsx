import React, { useCallback, useEffect, useState } from 'react';
import { CAP } from '../access';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { listPostLockAdjustments, createPostLockAdjustment } from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, money, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { FINAL_RUN_STATUSES, paymentTone, errText, nextPeriod, useSubmit } from './payrollKit';

/**
 * HRMS ▸ Payroll ▸ post-lock corrections (FRD §18).
 *
 * A locked month is never edited in place. A mistake found afterwards becomes an arrear
 * (pay more), a recovery (take back) or a reversal, recorded against THIS month and paid in
 * a LATER one — it shows up there as a read-only "carried in" line, and is marked Applied
 * when that later month is locked. The list shows both directions: corrections raised from
 * this month, and corrections landing in it.
 */

const TYPES = {
  Arrear: 'Pay the employee more in a later month.',
  Recovery: 'Take an overpayment back in a later month.',
  Reversal: 'Undo something paid in this month (recovered in a later month).',
};

const PostLockAdjustments = ({ period, runStatus, records, scope, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);

  const canCreate = can(CAP.PAYROLL_PROCESS) && FINAL_RUN_STATUSES.includes(runStatus);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await listPostLockAdjustments(period, scope);
      setRows(data || []);
    } catch (err) {
      setError(errText(err, 'Could not load corrections for this month.'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  useEffect(() => { load(); }, [load]);

  const direction = (r) => (r.source_period === period
    ? `From this month → paid in ${r.target_period}`
    : `Raised on ${r.source_period} → lands in this month`);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.employee_code}</span>
      </>
    ) },
    { key: 'type', label: 'Type', render: (r) => (
      <>
        <span className="text-[var(--text-main)]">{r.is_reversal ? 'Reversal' : r.adjustment_type}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{direction(r)}</span>
      </>
    ) },
    { key: 'amount', label: 'Amount', render: (r) => <span className="font-semibold">{money(r.amount)}</span> },
    { key: 'reason', label: 'Reason', render: (r) => (
      <>
        <span className="text-[var(--text-main)]">{r.reason}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">
          {r.created_by_name || '—'} · {day(r.created_at)}
        </span>
      </>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <Chip tone={paymentTone(r.status)}>{r.status}</Chip>
    ) },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-[12px] text-[var(--text-muted)] max-w-xl">
          A locked month is never changed. To correct it, record an arrear, a recovery or a
          reversal here — it is added to a later month&apos;s payroll as its own line.
        </p>
        {canCreate && (
          <Btn tone="primary" onClick={() => setAdding(true)}>Add correction</Btn>
        )}
      </div>
      {!FINAL_RUN_STATUSES.includes(runStatus) && (
        <p className="text-[12px] text-[var(--text-muted)]">
          This month is still open — change its figures with Adjust instead. Corrections can be
          raised once it is locked.
        </p>
      )}
      {loading && <HrmsLoading label="Loading corrections…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} keyOf={(r) => r.id}
            renderCard={(r) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
                    <p className="text-[11.5px] text-[var(--text-muted)]">{direction(r)}</p>
                  </div>
                  <Chip tone={paymentTone(r.status)}>{r.status}</Chip>
                </div>
                <Facts items={[
                  { label: 'Type', value: r.is_reversal ? 'Reversal' : r.adjustment_type },
                  { label: 'Amount', value: money(r.amount) },
                  { label: 'By', value: r.created_by_name },
                ]} />
                <p className="text-[12px] text-[var(--text-main)]">{r.reason}</p>
              </div>
            )} />
        ) : (
          <p className="text-[12px] text-[var(--text-muted)]">No corrections for this month.</p>
        )
      )}
      {adding && (
        <AddCorrectionModal period={period} records={records} scope={scope}
          onClose={() => setAdding(false)} onDone={() => { setAdding(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const AddCorrectionModal = ({ period, records, scope, onClose, onDone, showSuccess, showError }) => {
  const [employeeCode, setEmployeeCode] = useState(records[0]?.employee_code || '');
  const [kind, setKind] = useState('Arrear');
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [target, setTarget] = useState(nextPeriod(period));
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employeeCode || !(Number(amount) > 0) || !reason.trim()) {
      showError('Pick the employee, enter an amount above 0 and say why.');
      return;
    }
    if (target && target <= period) {
      showError(`The correction must land in a month after ${period}.`);
      return;
    }
    run(() => createPostLockAdjustment(period, {
      employee_code: employeeCode, adjustment_type: kind, amount: Number(amount),
      reason: reason.trim(), target_period: target || undefined,
    }, scope), `${kind} recorded — it will be added to ${target || nextPeriod(period)}.`);
  };

  return (
    <Modal title={`Correct ${period}`} labelledBy="post-lock-title"
      subtitle="Recorded against this month, paid or recovered in a later one."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="pl-employee">Employee *</label>
        <select id="pl-employee" value={employeeCode} className={FIELD}
          onChange={(e) => setEmployeeCode(e.target.value)}>
          {records.map((r) => (
            <option key={r.employee_code} value={r.employee_code}>
              {r.employee_name || r.employee_code} ({r.employee_code})
            </option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="pl-type">Type *</label>
          <select id="pl-type" value={kind} className={FIELD} onChange={(e) => setKind(e.target.value)}>
            {Object.keys(TYPES).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="pl-amount">Amount *</label>
          <input id="pl-amount" type="number" min="0" inputMode="decimal" value={amount} className={FIELD}
            onChange={(e) => setAmount(e.target.value)} />
        </div>
      </div>
      <p className="text-[11.5px] text-[var(--text-muted)] -mt-1.5">{TYPES[kind]}</p>
      <div>
        <label className={LABEL} htmlFor="pl-target">Paid / recovered in</label>
        <input id="pl-target" type="month" value={target} className={FIELD}
          onChange={(e) => setTarget(e.target.value)} />
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          Defaults to next month. That month&apos;s payroll must still be open.
        </p>
      </div>
      <div>
        <label className={LABEL} htmlFor="pl-reason">Reason *</label>
        <textarea id="pl-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

export default PostLockAdjustments;
