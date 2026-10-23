import React, { useEffect, useState } from 'react';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  getPayrollPolicy, savePayrollPolicy, listPayrollPolicyVersions,
} from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';
import { Btn, Chip, Modal } from '../internal/internalKit.jsx';
import { ROUNDING, errText, useSubmit } from './payrollKit';

/**
 * HRMS ▸ Payroll ▸ the company's payroll controls (FRD §19, §21, §24 Payroll Policy).
 *
 * Starting values the company can change — not rules frozen in code. Read by anyone who
 * runs or reviews payroll; drafted only by the maker (PAYROLL_PROCESS), which `canEdit`
 * mirrors.
 *
 * Saving here is a GOVERNED change (§21 "with versioning", §27). It drafts a PAY_POLICY
 * version and raises a change request; nothing moves until that request is approved and
 * activated in Configuration Approvals. So the screen has to collect the effective date
 * and the business reason, and has to be honest that Save is not Apply — the version list
 * below the form is what tells the reader which values the runs are actually using.
 */

const TODAY = () => new Date().toISOString().slice(0, 10);

const VERSION_TONE = {
  Draft: 'neutral', 'Pending Approval': 'warn', Approved: 'accent',
  Active: 'good', Superseded: 'neutral', Retired: 'neutral',
};

const PayrollPolicyModal = ({ scope, canEdit, onClose, onDone, showSuccess, showError }) => {
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const [versions, setVersions] = useState([]);
  const [effectiveFrom, setEffectiveFrom] = useState(TODAY());
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  useEffect(() => {
    let live = true;
    getPayrollPolicy(scope)
      .then(({ data }) => { if (live) setForm({ ...data }); })
      .catch((err) => { if (live) setError(errText(err, 'Could not load the payroll policy.')); });
    // A company with no versions yet is the normal case, not an error: the flat settings
    // are still the base everything resolves from, so an empty list is simply empty.
    listPayrollPolicyVersions(scope)
      .then(({ data }) => { if (live) setVersions(data || []); })
      .catch(() => { if (live) setVersions([]); });
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
    if (!reason.trim()) {
      showError('Say why the payroll policy is changing — the approver needs the reason.');
      return;
    }
    run(() => savePayrollPolicy({
      effective_from: effectiveFrom,
      change_reason: reason.trim(),
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
    }, scope), 'Drafted for approval — activate it in Configuration Approvals.');
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
      subtitle={canEdit
        ? 'Changes are drafted for approval — they do not take effect when you save.'
        : 'Read-only — HR changes these.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>{canEdit ? 'Cancel' : 'Close'}</Btn>
          {canEdit && form && (
            <Btn tone="primary" onClick={submit} disabled={busy}>
              {busy ? 'Drafting…' : 'Draft for approval'}
            </Btn>
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

          {/* §27 Effective Dating and Request. A governed change cannot be raised without
              these two, so the form collects them rather than the API rejecting the save. */}
          {canEdit && (
            <div className="pt-3 border-t border-[var(--border-subtle)] space-y-3">
              <div>
                <h3 className="text-[12.5px] font-bold text-[var(--text-main)]">
                  Raise this as a change
                </h3>
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  Saving drafts a new policy version and sends it for approval. A run for a
                  closed period keeps reading the version that was in force then.
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="pp-eff">Effective from</label>
                  <input id="pp-eff" type="date" value={effectiveFrom} className={FIELD}
                    onChange={(e) => setEffectiveFrom(e.target.value)} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="pp-reason">Why (business reason)</label>
                  <input id="pp-reason" value={reason} className={FIELD}
                    placeholder="Required — the approver reads this"
                    onChange={(e) => setReason(e.target.value)} />
                </div>
              </div>
            </div>
          )}

          {/* §21 — which versions exist, and which one the runs are actually using. */}
          <div className="pt-3 border-t border-[var(--border-subtle)] space-y-2">
            <h3 className="text-[12.5px] font-bold text-[var(--text-main)]">Versions</h3>
            {versions.length === 0 ? (
              <p className="text-[11.5px] text-[var(--text-muted)]">
                No versions yet — the values above are the company defaults, which every
                version lays over.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[11.5px]">
                  <thead>
                    <tr className="text-left text-[var(--text-muted)]">
                      <th className="py-1 pr-3 font-semibold">Ver</th>
                      <th className="py-1 pr-3 font-semibold">Status</th>
                      <th className="py-1 pr-3 font-semibold">From</th>
                      <th className="py-1 pr-3 font-semibold">To</th>
                      <th className="py-1 font-semibold">Approved by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {versions.map((v) => (
                      <tr key={v.version_no} className="border-t border-[var(--border-subtle)]">
                        <td className="py-1.5 pr-3 text-[var(--text-main)]">v{v.version_no}</td>
                        <td className="py-1.5 pr-3">
                          <Chip tone={VERSION_TONE[v.status] || 'neutral'}>{v.status}</Chip>
                        </td>
                        <td className="py-1.5 pr-3 text-[var(--text-main)]">{v.effective_from || '—'}</td>
                        <td className="py-1.5 pr-3 text-[var(--text-main)]">{v.effective_to || '—'}</td>
                        <td className="py-1.5 text-[var(--text-muted)]">
                          {v.approved_by_name || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
};

export default PayrollPolicyModal;
