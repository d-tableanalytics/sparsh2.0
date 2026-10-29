import React, { useCallback, useEffect, useState } from 'react';
import { SlidersHorizontal, FlaskConical, Send, CheckCircle2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { useNotification } from '../../../context/NotificationContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  listPolicyDefinitions, savePolicyDefinition, listPolicyVersions, savePolicyVersion,
  setPolicyVersionStatus, assignPolicyScope, simulateAttendancePolicy,
  createConfigChangeRequest, analyseConfigChangeImpact, submitConfigChangeRequest,
  runConfigChangeSimulation,
} from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';
import { Btn, Chip } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Attendance ▸ Policy Designer (FRD §23, §29).
 *
 * The rules that judge a day, versioned and effective-dated. §23's ten categories map onto
 * three policy records by WHEN they are read, not one per table row — see
 * ATTENDANCE_POLICY_RULES in models/hrms.py for why.
 *
 * Every field here is OPTIONAL and blank means "inherit". That is the whole design: a
 * company configuring the half-day combination must not have to restate the grace its
 * shift already gives, and a blank that meant zero would silently remove it.
 *
 * This screen DRAFTS and SENDS FOR APPROVAL; it does not approve or activate. It used to
 * do both through the version status endpoint, which skipped the impact analysis, the
 * simulation and the change request §27 puts between a draft and a live rule — and let
 * whoever drafted a rule approve it themselves. Approval and activation now belong to
 * Configuration Approvals, where the approver can see the impact before deciding.
 */

const TODAY = () => new Date().toISOString().slice(0, 10);
const THIS_MONTH = () => new Date().toISOString().slice(0, 7);

const STATUS_TONE = {
  Draft: 'neutral', 'Pending Approval': 'warn', Approved: 'accent',
  Active: 'good', Superseded: 'neutral', Retired: 'neutral',
};

// Which rule keys each policy offers, with the §23 category they come from.
const RULE_FIELDS = {
  ATT_DAY: [
    ['daily_grace_minutes', 'Daily grace (min)', 'Late Coming', 'number'],
    ['monthly_buffer_minutes', 'Monthly late buffer (min)', 'Late Coming', 'number'],
    ['late_threshold_minutes', 'Late mark only beyond (min after grace)', 'Late Coming', 'number'],
    ['late_escalation_days', 'Escalate at late days / month', 'Late Coming', 'number'],
    ['early_going_grace_minutes', 'Early-going grace (min)', 'Early Going', 'number'],
    ['half_day_threshold_minutes', 'Half day below (worked min)', 'Half Day', 'number'],
    ['half_day_late_minutes', 'Half day if late by (min)', 'Half Day', 'number'],
    ['half_day_early_minutes', 'Half day if early by (min)', 'Half Day', 'number'],
    ['half_day_exception_types', 'Approved request types that waive a late / early half day', 'Half Day', 'list'],
    ['absent_threshold_minutes', 'Absent below (worked min)', 'Absent', 'number'],
    ['half_day_fraction', 'A half day is paid', 'LOP', 'fraction'],
    ['absent_on_no_out_punch', 'No out-punch counts as Absent', 'Absent', 'bool'],
    ['unpaid_leave_is_lop', 'Unpaid leave is LOP', 'LOP', 'bool'],
  ],
  ATT_REGULARISATION: [
    ['window_days', 'Request window (days back)', 'OD / Regularisation', 'number'],
    ['max_requests_per_month', 'Max requests per month', 'OD / Regularisation', 'number'],
    ['approval_levels', 'Approval levels (1 or 2)', 'OD / Regularisation', 'number'],
    ['evidence_required', 'Evidence required', 'OD / Regularisation', 'bool'],
    ['request_types', 'Request types allowed', 'OD / Regularisation', 'list'],
  ],
  ATT_CLOSURE: [
    ['closing_day', 'Attendance closes on day', 'Monthly Closure', 'number'],
    ['enforce_cutoff', 'Enforce the cut-off', 'Monthly Closure', 'bool'],
    ['block_pending_requests', 'Block locking with open requests', 'Monthly Closure', 'bool'],
  ],
};

const POLICY_LABEL = {
  ATT_DAY: 'Daily judgement — late, early, half day, absent, LOP',
  ATT_REGULARISATION: 'Regularisation and OD requests',
  ATT_CLOSURE: 'Monthly closure and cut-off',
};

// Every §26 / §23 scope key the backend resolves (POLICY_SCOPE_KEYS).
const SCOPE_FIELDS = [
  ['locations', 'Locations'],
  ['departments', 'Department IDs'],
  ['grades', 'Grades'],
  ['levels', 'Levels'],
  ['employment_categories', 'Employee categories'],
  ['shift_codes', 'Shift codes'],
  ['attendance_policy_groups', 'Attendance policy groups'],
  ['payroll_groups', 'Payroll groups'],
];

const VersionEditor = ({ code, version, canDraft, canApprove, scope, onDone,
                        showSuccess, showError }) => {
  const [rules, setRules] = useState(version?.rules || {});
  const [effectiveFrom, setEffectiveFrom] = useState(version?.effective_from || TODAY());
  const [effectiveTo, setEffectiveTo] = useState(version?.effective_to || '');
  const [reason, setReason] = useState('');
  const [simCodes, setSimCodes] = useState('');
  const [scopeText, setScopeText] = useState(() => {
    const a = (version?.assignments || [])[0];
    return Object.fromEntries(SCOPE_FIELDS.map(([k]) => [k, (a?.scope?.[k] || []).join(', ')]));
  });
  const [simPeriod, setSimPeriod] = useState(THIS_MONTH());
  const [sim, setSim] = useState(null);
  const [busy, setBusy] = useState(false);

  const editable = !version || ['Draft', 'Pending Approval'].includes(version.status);
  const fields = RULE_FIELDS[code] || [];

  const setRule = (key, raw, type) => setRules((r) => {
    const next = { ...r };
    if (type === 'bool') { next[key] = !!raw; return next; }
    if (type === 'list') {
      const items = String(raw || '').split(',').map((v) => v.trim()).filter(Boolean);
      if (items.length) next[key] = items; else delete next[key];
      return next;
    }
    if (raw === '' || raw === null) { delete next[key]; return next; }
    next[key] = Number(raw);
    return next;
  });

  const run = async (fn, message) => {
    setBusy(true);
    try { await fn(); showSuccess(message); await onDone(); }
    catch (err) { showError(err?.response?.data?.detail || 'That did not go through.'); }
    finally { setBusy(false); }
  };

  const save = () => run(async () => {
    if (effectiveTo && effectiveTo < effectiveFrom) {
      throw { response: { data: { detail: 'Effective to is before effective from.' } } };
    }
    const { data } = await savePolicyVersion(code, {
      policy_code: code, effective_from: effectiveFrom, effective_to: effectiveTo || null,
      rules, change_reason: reason,
    }, { ...scope, ...(version ? { version_no: version.version_no } : {}) });
    const vno = data?.version_no ?? version?.version_no;
    const cleaned = Object.fromEntries(SCOPE_FIELDS
      .map(([k]) => [k, (scopeText[k] || '').split(',').map((v) => v.trim()).filter(Boolean)])
      .filter(([, v]) => v.length));
    if (vno && Object.keys(cleaned).length) {
      await assignPolicyScope(code, vno, { policy_code: code, version_no: vno, scope: cleaned }, scope);
    }
  }, 'Draft saved.');

  const simulate = async () => {
    if (!version?.version_no) { showError('Save the draft first.'); return; }
    setBusy(true);
    try {
      const { data } = await simulateAttendancePolicy(code, version.version_no,
        { ...scope, period: simPeriod, ...(simCodes.trim() ? { employee_codes: simCodes.trim() } : {}) });
      setSim(data);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not simulate that.');
    } finally { setBusy(false); }
  };

  const move = (status) => run(
    () => setPolicyVersionStatus(code, version.version_no, { status }, scope),
    `Version ${status.toLowerCase()}.`);

  /**
   * §27 Request → Impact Analysis → Approval. Raising the request and running the impact
   * analysis are the drafter's two steps, so they go together behind one button: a request
   * sitting un-analysed cannot be submitted anyway, and asking the drafter to click twice
   * only produces requests stuck at the first stage.
   *
   * The version is also handed to Pending Approval so the designer reflects that it is no
   * longer the drafter's to edit — that transition is still a direct call, because it
   * makes no rule real.
   */
  const sendForApproval = () => run(async () => {
    if (!reason.trim()) {
      throw { response: { data: { detail: 'Say why this change is wanted — the approver and the audit trail both need it.' } } };
    }
    const { data } = await createConfigChangeRequest({
      entity_type: 'policy_version', entity_code: code,
      version_no: version.version_no, reason: reason.trim(),
      effective_from: effectiveFrom,
      title: `${code} v${version.version_no}`,
    }, scope);
    await analyseConfigChangeImpact(data.request_no, scope);
    // §27 Test / Simulation, recorded on the request so the approver sees what it showed.
    await runConfigChangeSimulation(data.request_no, { ...scope, period: simPeriod });
    await submitConfigChangeRequest(data.request_no, scope);
    if (version.status === 'Draft') {
      await setPolicyVersionStatus(code, version.version_no,
        { status: 'Pending Approval' }, scope);
    }
  }, 'Sent for approval — an approver activates it in Configuration Approvals.');

  return (
    <div className="rounded-lg border border-[var(--border)] px-3.5 py-3 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[12.5px] font-bold text-[var(--text-main)]">
          {version ? `Version ${version.version_no}` : 'New version'}
        </h3>
        {version && <Chip tone={STATUS_TONE[version.status] || 'neutral'}>{version.status}</Chip>}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor={`eff-${code}`}>Effective from</label>
          <input id={`eff-${code}`} type="date" value={effectiveFrom} className={FIELD}
            disabled={!editable || !canDraft} onChange={(e) => setEffectiveFrom(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor={`eto-${code}`}>Effective to (optional)</label>
          <input id={`eto-${code}`} type="date" value={effectiveTo} className={FIELD}
            disabled={!editable || !canDraft} onChange={(e) => setEffectiveTo(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor={`rsn-${code}`}>Why (change reason)</label>
          <input id={`rsn-${code}`} value={reason} className={FIELD}
            disabled={!editable || !canDraft} onChange={(e) => setReason(e.target.value)} />
        </div>
      </div>

      <div>
        <p className={LABEL}>Rules — blank means inherit from the shift or company policy</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-1">
          {fields.map(([key, label, category, type]) => (
            <div key={key}>
              <label className={LABEL} htmlFor={`${code}-${key}`}>
                {label} <span className="text-[var(--text-muted)] font-normal">· {category}</span>
              </label>
              {type === 'bool' ? (
                <label className="flex items-center gap-2 h-9">
                  <input id={`${code}-${key}`} type="checkbox" checked={!!rules[key]}
                    disabled={!editable || !canDraft}
                    onChange={(e) => setRule(key, e.target.checked, 'bool')} />
                  <span className="text-[12px] text-[var(--text-muted)]">
                    {rules[key] ? 'Yes' : 'No'}
                  </span>
                </label>
              ) : type === 'list' ? (
                <input id={`${code}-${key}`} defaultValue={(rules[key] || []).join(', ')}
                  className={FIELD} placeholder="comma separated — blank: inherit"
                  disabled={!editable || !canDraft}
                  onBlur={(e) => setRule(key, e.target.value, 'list')} />
              ) : type === 'fraction' ? (
                <select id={`${code}-${key}`} value={rules[key] ?? ''} className={FIELD}
                  disabled={!editable || !canDraft}
                  onChange={(e) => setRule(key, e.target.value, 'number')}>
                  <option value="">Inherit (half)</option>
                  <option value="0">Nothing — a full day's LOP</option>
                  <option value="0.25">A quarter day</option>
                  <option value="0.5">Half a day</option>
                  <option value="0.75">Three quarters</option>
                </select>
              ) : (
                <input id={`${code}-${key}`} type="number" min="0" value={rules[key] ?? ''}
                  className={FIELD} placeholder="inherit"
                  disabled={!editable || !canDraft}
                  onChange={(e) => setRule(key, e.target.value, 'number')} />
              )}
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className={LABEL}>Who it applies to — blank in every box means everybody</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-1">
          {SCOPE_FIELDS.map(([key, label]) => (
            <div key={key}>
              <label className={LABEL} htmlFor={`${code}-sc-${key}`}>{label}</label>
              <input id={`${code}-sc-${key}`} value={scopeText[key] || ''} className={FIELD}
                placeholder="comma separated" disabled={!editable || !canDraft}
                onChange={(e) => setScopeText((t) => ({ ...t, [key]: e.target.value }))} />
            </div>
          ))}
        </div>
      </div>

      {/* §23: "create a new policy version, TEST IT and activate it from a future date". */}
      {version && (
        <div className="rounded-lg bg-[var(--bg-subtle)] px-3 py-2.5 space-y-2">
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className={LABEL} htmlFor={`sim-${code}`}>Test against</label>
              <input id={`sim-${code}`} type="month" value={simPeriod} className={FIELD}
                onChange={(e) => setSimPeriod(e.target.value)} />
            </div>
            {code !== 'ATT_CLOSURE' && (
              <div>
                <label className={LABEL} htmlFor={`simc-${code}`}>Employees (optional)</label>
                <input id={`simc-${code}`} value={simCodes} className={FIELD}
                  placeholder="EMP codes, comma separated" onChange={(e) => setSimCodes(e.target.value)} />
              </div>
            )}
            <Btn onClick={simulate} disabled={busy}>
              <FlaskConical size={14} /> {busy ? 'Working…' : 'Simulate'}
            </Btn>
          </div>
          {sim && code === 'ATT_REGULARISATION' && (
            <div className="text-[12px] text-[var(--text-main)] space-y-1">
              <p>
                Of {sim.requests_examined} request(s) in {sim.period}, the draft would refuse{' '}
                <b>{sim.would_refuse}</b> more and allow <b>{sim.would_allow}</b> more than today.
              </p>
              {(sim.changes || []).slice(0, 15).map((c) => (
                <p key={`${c.request_no}-${c.work_date}`} className="text-[11.5px] text-[var(--text-muted)]">
                  {c.employee_code} · {c.work_date}: {c.would_be_refused.length
                    ? `refused (${c.would_be_refused.join('; ')})` : 'allowed'}
                </p>
              ))}
              {sim.note && <p className="text-[var(--text-muted)]">{sim.note}</p>}
            </div>
          )}
          {sim && code === 'ATT_CLOSURE' && (
            <div className="text-[12px] text-[var(--text-main)] space-y-1">
              <p>{sim.pending_requests} request(s) are still open for {sim.period}.</p>
              <p>Today: cut-off {sim.was?.cutoff_date || 'not enforced'}, locking {sim.was?.locking_blocked ? 'blocked' : 'allowed'}.</p>
              <p>Draft: cut-off {sim.now?.cutoff_date || 'not enforced'}, locking {sim.now?.locking_blocked ? 'blocked' : 'allowed'}.</p>
            </div>
          )}
          {sim && code === 'ATT_DAY' && (
            <div className="text-[12px] text-[var(--text-main)] space-y-1">
              <p>
                <span className="font-bold">{sim.days_changed}</span> of {sim.days_examined} recorded
                day(s) would change, across {sim.employees_affected} employee(s).
                {sim.payable_days_delta !== 0 && (
                  <span className={sim.payable_days_delta < 0 ? 'text-[var(--accent-red)]' : ''}>
                    {' '}Payable days {sim.payable_days_delta > 0 ? '+' : ''}{sim.payable_days_delta}.
                  </span>
                )}
              </p>
              {sim.note && <p className="text-[var(--text-muted)]">{sim.note}</p>}
              {!!(sim.changes || []).length && (
                <div className="overflow-x-auto">
                  <table className="text-[11.5px] w-full">
                    <thead>
                      <tr className="text-[var(--text-muted)] text-left">
                        <th className="pr-3 py-1">Employee</th><th className="pr-3">Date</th>
                        <th className="pr-3">Was</th><th className="pr-3">Would be</th>
                        <th>Why</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sim.changes.slice(0, 25).map((c) => (
                        <tr key={`${c.employee_code}-${c.work_date}`}>
                          <td className="pr-3 py-0.5">{c.employee_code}</td>
                          <td className="pr-3">{c.work_date}</td>
                          <td className="pr-3">{c.was.status} ({c.was.payable_day})</td>
                          <td className="pr-3">{c.now.status} ({c.now.payable_day})</td>
                          <td className="text-[var(--text-muted)]">{c.now.reason || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {sim.changes.length > 25 && (
                    <p className="text-[var(--text-muted)] pt-1">
                      …and {sim.changes.length - 25} more.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {canDraft && editable && (
          <Btn tone="primary" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : (version ? 'Save draft' : 'Create draft')}
          </Btn>
        )}
        {canDraft && ['Draft', 'Pending Approval'].includes(version?.status) && (
          <Btn tone="primary" onClick={sendForApproval} disabled={busy}>
            <Send size={14} /> {busy ? 'Working…' : 'Send for approval'}
          </Btn>
        )}
        {canDraft && version?.status === 'Pending Approval' && (
          <Btn onClick={() => move('Draft')} disabled={busy}>Take back to draft</Btn>
        )}
      </div>
      {version?.status === 'Pending Approval' && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          <CheckCircle2 size={12} className="inline" /> With an approver. They review the
          impact and activate it in Configuration Approvals — somebody other than whoever
          raised it, which is why this screen cannot do it.
          {canApprove && (
            <>
              {' '}You hold that approval: open{' '}
              <a href="/hrms/config-approvals"
                className="underline text-[var(--text-main)]">Configuration Approvals</a>
              {' '}to decide on it.
            </>
          )}
        </p>
      )}
      {version?.status === 'Approved' && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Approved. It takes effect on {version.effective_from} once activated — activating
          before that date is safe, the effective date is what decides which days it judges.
        </p>
      )}
    </div>
  );
};

const AttendancePolicyDesigner = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [code, setCode] = useState('ATT_DAY');
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);

  const canDraft = can(CAP.CONFIG_DRAFT);
  const canApprove = can(CAP.CONFIG_APPROVE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      // The definition is created on first use — a company should not have to register a
      // policy before configuring it.
      const { data: defs } = await listPolicyDefinitions({ ...scope, module: 'attendance' });
      if (!(defs || []).some((d) => d.code === code) && canDraft) {
        await savePolicyDefinition(
          { code, name: POLICY_LABEL[code], module: 'attendance' }, scope);
      }
      const { data } = await listPolicyVersions(code, scope);
      setVersions(Array.isArray(data) ? data : []);
      setAdding(false);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the attendance policies.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, code]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={SlidersHorizontal}
        title="Attendance Policy Designer"
        subtitle="Versioned, effective-dated rules for late, early, half day, absent, LOP, regularisation and closure (FRD §23)."
      />
      <HrmsScopeBar />

      <div className="max-w-md">
        <label className={LABEL} htmlFor="apd-code">Policy</label>
        <select id="apd-code" value={code} className={FIELD}
          onChange={(e) => setCode(e.target.value)}>
          {Object.entries(POLICY_LABEL).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </div>

      {loading && <HrmsLoading label="Loading policy versions…" />}
      {error && <HrmsError message={error} />}

      {!loading && !error && (
        <div className="space-y-3">
          {canDraft && !adding && (
            <Btn onClick={() => setAdding(true)}>New version</Btn>
          )}
          {adding && (
            <VersionEditor code={code} version={null} canDraft={canDraft}
              canApprove={canApprove} scope={scope} onDone={load}
              showSuccess={showSuccess} showError={showError} />
          )}
          {!versions.length && !adding && (
            <HrmsEmpty icon={SlidersHorizontal} title="No versions yet"
              message="This company is running on its shift and company settings. Create a version to override them from a date." />
          )}
          {versions.map((v) => (
            <VersionEditor key={v.version_no} code={code} version={v} canDraft={canDraft}
              canApprove={canApprove} scope={scope} onDone={load}
              showSuccess={showSuccess} showError={showError} />
          ))}
        </div>
      )}
    </div>
  );
};

export default AttendancePolicyDesigner;
