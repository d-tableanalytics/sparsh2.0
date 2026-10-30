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

// P1-095: the configured approval chain. What a company that has configured nothing gets
// today, shown as the starting point for a custom chain.
const DEFAULT_CHAIN = [
  { name: 'Checker', cap: 'payroll.check', roles: [] },
  { name: 'Finance Approver', cap: 'payroll.approve', roles: [] },
];
const STAGE_CAPS = [
  ['payroll.check', 'Payroll / HR Checker'],
  ['payroll.approve', 'Finance / Authorised Approver'],
  ['payroll.process', 'Payroll Maker'],
];
const STAGE_ROLES = [['hr', 'HR'], ['md', 'MD'], ['finance', 'Finance'], ['admin', 'Admin']];

const VERSION_TONE = {
  Draft: 'neutral', 'Pending Approval': 'warn', Approved: 'accent',
  Active: 'good', Superseded: 'neutral', Retired: 'neutral',
};

const PayrollPolicyModal = ({ scope, canEdit, onClose, onDone, showSuccess, showError }) => {
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const [versions, setVersions] = useState([]);
  const [effectiveFrom, setEffectiveFrom] = useState(TODAY());
  const [effectiveTo, setEffectiveTo] = useState('');
  // §26 scope of the drafted version; blank = company-wide.
  const [scopeText, setScopeText] = useState({ locations: '', grades: '', employment_categories: '', payroll_groups: '' });
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  useEffect(() => {
    let live = true;
    getPayrollPolicy(scope)
      .then(({ data }) => {
        if (!live) return;
        const levels = data?.approval_levels || [];
        setForm({ ...data, custom_chain: levels.length > 0,
          chain_stages: levels.length ? levels : DEFAULT_CHAIN });
      })
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
    if (effectiveTo && effectiveTo < effectiveFrom) {
      showError('Effective to is before effective from.');
      return;
    }
    if (form.custom_chain && form.chain_stages.some((st) => !String(st.name || '').trim())) {
      showError('Give every approval stage a name.');
      return;
    }
    const list = (text) => String(text || '').split(',').map((v) => v.trim()).filter(Boolean);
    const approvalAbove = String(form.adjustment_approval_above ?? '').trim();
    run(() => savePayrollPolicy({
      effective_from: effectiveFrom,
      effective_to: effectiveTo || null,
      scope: Object.fromEntries(Object.entries(scopeText).map(([k, v]) => [k, list(v)])),
      change_reason: reason.trim(),
      excluded_employee_categories: list(form.excluded_text ?? (form.excluded_employee_categories || []).join(', ')),
      enforce_input_cutoff: !!form.enforce_input_cutoff,
      adjustment_approval_above: approvalAbove === '' ? null : Number(approvalAbove),
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
      // P1-095: only sent when it says something — a custom chain, or switching back to
      // the default from one ([] = default).
      ...(form.custom_chain
        ? { approval_levels: form.chain_stages.map((st) => ({ ...st, name: st.name.trim() })) }
        : (form.approval_levels?.length ? { approval_levels: [] } : {})),
    }, scope), 'Drafted as a change request — open it in Configuration Approvals (Draft) and send it for approval.');
  };

  const setStage = (i, patch) => setForm((f) => ({
    ...f, chain_stages: f.chain_stages.map((st, j) => (j === i ? { ...st, ...patch } : st)),
  }));
  const toggleRole = (i, role) => setStage(i, {
    roles: form.chain_stages[i].roles?.includes(role)
      ? form.chain_stages[i].roles.filter((r) => r !== role)
      : [...(form.chain_stages[i].roles || []), role],
  });

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
          {check('enforce_input_cutoff', 'Enforce the input cut-off',
            'After the cut-off day of the payroll month, only a payroll approver can change monthly inputs and one-off lines.')}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="pp-adj-limit">One-off lines above this amount need approval</label>
              <input id="pp-adj-limit" type="number" min="0" step="1" value={form.adjustment_approval_above ?? ''}
                className={FIELD} disabled={!canEdit} placeholder="Blank = no approval needed"
                onChange={set('adjustment_approval_above')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="pp-excluded">Categories left out of payroll</label>
              <input id="pp-excluded" className={FIELD} disabled={!canEdit} placeholder="e.g. Consultant, Intern"
                value={form.excluded_text ?? (form.excluded_employee_categories || []).join(', ')}
                onChange={set('excluded_text')} />
            </div>
          </div>

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
            {/* P1-095 — the approval levels themselves, as configuration. */}
            {check('custom_chain', 'Use a custom approval chain',
              'On: the run passes through the stages below, in order, instead of check-then-approve. '
              + 'The maker can never approve their own run, and nobody can pass two stages.')}
            {form.custom_chain && (
              <div className="space-y-2">
                {form.chain_stages.map((st, i) => (
                  <div key={i} className="rounded-lg border border-[var(--border)] p-2.5 space-y-2">
                    <div className="flex items-end gap-2">
                      <div className="flex-1">
                        <label className={LABEL} htmlFor={`pp-stage-${i}`}>Stage {i + 1} name</label>
                        <input id={`pp-stage-${i}`} className={FIELD} value={st.name} disabled={!canEdit}
                          maxLength={60} onChange={(e) => setStage(i, { name: e.target.value })} />
                      </div>
                      <div className="flex-1">
                        <label className={LABEL} htmlFor={`pp-stage-cap-${i}`}>Permission needed</label>
                        <select id={`pp-stage-cap-${i}`} className={FIELD} value={st.cap} disabled={!canEdit}
                          onChange={(e) => setStage(i, { cap: e.target.value })}>
                          {STAGE_CAPS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                        </select>
                      </div>
                      {canEdit && form.chain_stages.length > 1 && (
                        <Btn tone="ghost" onClick={() => setForm((f) => ({
                          ...f, chain_stages: f.chain_stages.filter((_x, j) => j !== i) }))}>
                          Remove
                        </Btn>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-[var(--text-main)]">
                      <span className="text-[11.5px] text-[var(--text-muted)]">Only these roles (none ticked = anyone with the permission):</span>
                      {STAGE_ROLES.map(([v, label]) => (
                        <label key={v} className="inline-flex items-center gap-1.5">
                          <input type="checkbox" disabled={!canEdit}
                            checked={(st.roles || []).includes(v)} onChange={() => toggleRole(i, v)} />
                          {label}
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
                {canEdit && form.chain_stages.length < 3 && (
                  <Btn tone="ghost" onClick={() => setForm((f) => ({
                    ...f, chain_stages: [...f.chain_stages,
                      { name: `Stage ${f.chain_stages.length + 1}`, cap: 'payroll.approve', roles: [] }] }))}>
                    Add stage
                  </Btn>
                )}
              </div>
            )}
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
                  <label className={LABEL} htmlFor="pp-eff-to">Effective to (optional)</label>
                  <input id="pp-eff-to" type="date" value={effectiveTo} className={FIELD}
                    onChange={(e) => setEffectiveTo(e.target.value)} />
                </div>
                <div className="sm:col-span-2">
                  <label className={LABEL} htmlFor="pp-reason">Why (business reason)</label>
                  <input id="pp-reason" value={reason} className={FIELD}
                    placeholder="Required — the approver reads this"
                    onChange={(e) => setReason(e.target.value)} />
                </div>
              </div>
              <div>
                <p className={LABEL}>Applies to (blank = everyone)</p>
                <p className="text-[11px] text-[var(--text-muted)] mb-2">
                  Comma-separated values. Rounding, the sandwich rule and salary approval follow
                  the scope; run-wide settings (cut-off, approvals) stay company-wide.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {[['locations', 'Locations'], ['grades', 'Grades'],
                    ['employment_categories', 'Employee categories'], ['payroll_groups', 'Payroll groups']]
                    .map(([k, l]) => (
                      <div key={k}>
                        <label className={LABEL} htmlFor={`pp-scope-${k}`}>{l}</label>
                        <input id={`pp-scope-${k}`} className={FIELD} value={scopeText[k]}
                          onChange={(e) => setScopeText((s) => ({ ...s, [k]: e.target.value }))} />
                      </div>
                    ))}
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
