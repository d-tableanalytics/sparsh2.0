import React, { useEffect, useState } from 'react';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { getPayrollPolicy, savePayrollPolicy } from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';
import { Btn, Modal } from '../internal/internalKit.jsx';
import { ROUNDING, errText, useSubmit } from './payrollKit';

/**
 * HRMS ▸ Payroll ▸ the company's payroll controls (FRD §19, §24 Payroll Policy).
 *
 * Starting values the company can change — not rules frozen in code. Read by anyone who
 * runs or reviews payroll; saved only by the maker (PAYROLL_PROCESS), which `canEdit` mirrors.
 */

const PayrollPolicyModal = ({ scope, canEdit, onClose, onDone, showSuccess, showError }) => {
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  useEffect(() => {
    let live = true;
    getPayrollPolicy(scope)
      .then(({ data }) => { if (live) setForm({ ...data }); })
      .catch((err) => { if (live) setError(errText(err, 'Could not load the payroll policy.')); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [key]: value }));
  };

  const submit = () => {
    const variance = Number(form.variance_threshold_percent);
    const cutoff = Number(form.input_cutoff_day);
    if (Number.isNaN(variance) || variance < 0 || variance > 100) {
      showError('The variance threshold must be between 0 and 100%.');
      return;
    }
    if (!Number.isInteger(cutoff) || cutoff < 1 || cutoff > 31) {
      showError('The input cut-off day must be 1 to 31.');
      return;
    }
    run(() => savePayrollPolicy({
      require_attendance_lock: !!form.require_attendance_lock,
      variance_threshold_percent: variance,
      structure_approval_required: !!form.structure_approval_required,
      payslip_release: form.payslip_release,
      input_cutoff_day: cutoff,
      net_rounding: form.net_rounding,
      sandwich_weekly_off: !!form.sandwich_weekly_off,
      // FRD §12 / §19 approval matrix.
      checker_required: !!form.checker_required,
      approver_distinct_from_checker: !!form.approver_distinct_from_checker,
      lock_cap: form.lock_cap || 'payroll.approve',
    }, scope), 'Payroll policy saved.');
  };

  const check = (key, label, hint) => (
    <label className="flex items-start gap-2.5">
      <input type="checkbox" className="mt-0.5" checked={!!form[key]} disabled={!canEdit} onChange={set(key)} />
      <span>
        <span className="block text-[12.5px] font-bold text-[var(--text-main)]">{label}</span>
        <span className="block text-[11.5px] text-[var(--text-muted)]">{hint}</span>
      </span>
    </label>
  );

  return (
    <Modal title="Payroll Policy" labelledBy="payroll-policy-title"
      subtitle={canEdit ? 'Starting values — you can change them.' : 'Read-only — HR changes these.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>{canEdit ? 'Cancel' : 'Close'}</Btn>
          {canEdit && form && (
            <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
          )}
        </>
      )}
    >
      {error && <HrmsError message={error} />}
      {!error && !form && <HrmsLoading label="Loading the policy…" />}
      {form && (
        <div className="space-y-4">
          {check('require_attendance_lock', 'Attendance must be locked before calculating',
            'Calculate is refused until the month is locked in Attendance → Monthly Closure.')}
          {check('sandwich_weekly_off', 'Sandwich rule for weekly offs and holidays',
            'A weekly off or holiday between LOP days is LOP too — so someone absent all month is not paid for its Sundays.')}
          {check('structure_approval_required', 'A new salary needs a second person’s approval',
            'A salary someone sets stays “Pending Approval” — and is not paid — until a payroll approver accepts it.')}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="pp-variance">Flag net-pay change above (%)</label>
              <input id="pp-variance" type="number" min="0" max="100" step="0.5" value={form.variance_threshold_percent ?? ''}
                className={FIELD} disabled={!canEdit} onChange={set('variance_threshold_percent')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="pp-cutoff">Input cut-off day</label>
              <input id="pp-cutoff" type="number" min="1" max="31" step="1" value={form.input_cutoff_day ?? ''}
                className={FIELD} disabled={!canEdit} onChange={set('input_cutoff_day')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="pp-release">Payslips are released</label>
              <select id="pp-release" value={form.payslip_release || 'on_lock'} className={FIELD}
                disabled={!canEdit} onChange={set('payslip_release')}>
                <option value="on_lock">When payroll is locked</option>
                <option value="after_payment">After the employee is paid</option>
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="pp-rounding">Round net pay</label>
              <select id="pp-rounding" value={form.net_rounding || 'None'} className={FIELD}
                disabled={!canEdit} onChange={set('net_rounding')}>
                {ROUNDING.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          </div>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            The cut-off day is the last day of the month inputs (PF, tax, one-off lines) are
            expected. A net-pay change beyond the threshold shows as a warning on that employee.
          </p>

          {/* FRD §12 stages 7-10 / §19 "Payroll Approval Matrix". Who performs each stage is
              a setting because the FRD leaves the exact approvers unconfirmed. */}
          <div className="pt-3 border-t border-[var(--border-subtle)] space-y-3">
            <div>
              <h3 className="text-[12.5px] font-bold text-[var(--text-main)]">Approval matrix</h3>
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Payroll runs maker → checker → approver → lock. The person who submits can never
                check or approve their own run; that rule is not optional.
              </p>
            </div>
            {check('checker_required', 'A checker verifies before Finance approves',
              'Off: the run goes straight from the maker to Finance for approval, skipping the separate check.')}
            {check('approver_distinct_from_checker', 'The approver must not be the checker',
              'On: whoever passed the check cannot also give the approval.')}
            <div>
              <label className={LABEL} htmlFor="pp-lockcap">Who locks the approved payroll</label>
              <select id="pp-lockcap" value={form.lock_cap || 'payroll.approve'} className={FIELD}
                disabled={!canEdit} onChange={set('lock_cap')}>
                <option value="payroll.approve">Finance / Authorised Approver</option>
                <option value="payroll.check">Payroll / HR Checker</option>
                <option value="payroll.process">Payroll Maker</option>
              </select>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
};

export default PayrollPolicyModal;
