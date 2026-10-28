import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  SlidersHorizontal, FlaskConical, Send, CheckCircle2, Users, Clock, LogOut,
  PieChart, CircleSlash, FileCheck2, CalendarClock, Lock,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { useNotification } from '../../../context/NotificationContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import BoardTabs from '../common/BoardTabs';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  listPolicyDefinitions, savePolicyDefinition, listPolicyVersions, savePolicyVersion,
  setPolicyVersionStatus, assignPolicyScope, simulateAttendancePolicy,
  createConfigChangeRequest, analyseConfigChangeImpact, submitConfigChangeRequest,
  runConfigChangeSimulation, getPayrollPolicy,
} from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';
import { Btn, Chip } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Attendance Configuration (FRD §23, §29).
 *
 * The rules that judge a day, versioned and effective-dated. §23's ten categories map onto
 * three policy records by WHEN they are read, not one per table row — see
 * ATTENDANCE_POLICY_RULES in models/hrms.py for why.
 *
 * -- Why seven tabs over three policies -----------------------------------------------
 * HR does not think in read patterns; it thinks in §23's categories — "where do I set late
 * coming?". So the SCREEN is one tab per category and the STORAGE stays three policies:
 * Late Coming, Early Going, Half Day and Absent are four windows onto the single ATT_DAY
 * version, each showing only its own rules. That is deliberate and not a layout accident:
 * one day cannot be judged by four competing versions, and four tabs each drafting their
 * own would produce exactly that. The effective dates, the applicability and the approval
 * are therefore shared across those four tabs, because they belong to the one version
 * underneath them. Switching between them does NOT remount the editor, so a half-finished
 * draft survives the hop; switching to Regularisation or Monthly Cut-off moves to a
 * different policy and asks first if anything is unsaved.
 *
 * Every field here is OPTIONAL and blank means "inherit". That is the whole design: a
 * company configuring the half-day combination must not have to restate the grace its
 * shift already gives, and a blank that meant zero would silently remove it. Rules whose
 * default is not `false` are tri-state selects rather than checkboxes for that reason — an
 * unticked box cannot say "inherit".
 *
 * This screen DRAFTS and SENDS FOR APPROVAL; it does not approve or activate. It used to
 * do both through the version status endpoint, which skipped the impact analysis, the
 * simulation and the change request §27 puts between a draft and a live rule — and let
 * whoever drafted a rule approve it themselves. Approval and activation now belong to
 * Configuration Approvals, where the approver can see the impact before deciding.
 */

const TODAY = () => new Date().toISOString().slice(0, 10);
const THIS_MONTH = () => new Date().toISOString().slice(0, 7);

const ATT_DAY = 'ATT_DAY';
const ATT_REGULARISATION = 'ATT_REGULARISATION';
const ATT_CLOSURE = 'ATT_CLOSURE';

const STATUS_TONE = {
  Draft: 'neutral', 'Pending Approval': 'warn', Approved: 'accent',
  Active: 'good', Superseded: 'neutral', Retired: 'neutral',
};

/**
 * One rule field. `tab` is where HR looks for it; `frd` is the §23 category it comes from,
 * shown beside the label so the mapping back to the document stays readable. They differ
 * in only a few places — the LOP parameters are read on the Half Day and Absent tabs
 * because that is where somebody setting them already is.
 */
const F = (key, label, tab, type, frd = tab, help = null) =>
  ({ key, label, tab, type, frd, help });

const RULE_FIELDS = {
  [ATT_DAY]: [
    // §23 Late Coming
    F('daily_grace_minutes', 'Daily grace (min)', 'Late Coming', 'number', 'Late Coming',
      'Arriving within this many minutes of the shift start is not late at all.'),
    F('monthly_buffer_minutes', 'Monthly late buffer (min)', 'Late Coming', 'number'),
    F('late_escalation_days', 'Escalate at late days / month', 'Late Coming', 'number',
      'Late Coming', 'Reported only — it never changes a status or the pay.'),

    // §23 Early Going
    F('early_going_grace_minutes', 'Early-going grace (min)', 'Early Going', 'number',
      'Early Going', 'Leaving within this many minutes of the scheduled out is not early.'),
    F('min_hours', 'Minimum working hours', 'Early Going', 'hours', 'Early Going',
      'A day below this is a half day however early the person left. Blank inherits the '
      + 'shift, then the company timing.'),

    // §23 Half Day
    F('half_day_threshold_minutes', 'Half day below (worked min)', 'Half Day', 'number'),
    F('half_day_early_minutes', 'Half day if early by (min)', 'Half Day', 'number', 'Half Day',
      'Measured against the shift’s scheduled out.'),
    F('half_day_late_minutes', 'Half day if late by (min)', 'Half Day', 'number'),
    F('half_day_exception_types',
      'Approved request types that waive a late / early half day', 'Half Day', 'list'),
    F('half_day_fraction', 'A half day is paid', 'Half Day', 'fraction', 'LOP'),

    // §23 Absent
    F('absent_threshold_minutes', 'Absent below (worked min)', 'Absent', 'number', 'Absent',
      'The minimum a day must show to count at all. No in-punch is Absent regardless.'),
    F('absent_on_no_out_punch', 'No out-punch counts as Absent', 'Absent', 'bool', 'Absent',
      'Off: the day stays Present pending a correction, which is the default behaviour.'),
    F('unpaid_leave_is_lop', 'Unpaid leave is LOP', 'Absent', 'tristate', 'LOP'),
    F('sandwich_weekly_off', 'Weekly off between two absences is LOP', 'Absent', 'tristate',
      'LOP', 'Blank inherits the payroll policy.'),
  ],
  [ATT_REGULARISATION]: [
    F('window_days', 'Request window (days back)', 'Regularisation', 'number',
      'OD / Regularisation', 'How far back a correction may be raised.'),
    F('max_requests_per_month', 'Max requests per month', 'Regularisation', 'number',
      'OD / Regularisation'),
    F('approval_levels', 'Approval path', 'Regularisation', 'levels', 'OD / Regularisation',
      'One level makes the manager’s approval final; two sends it on to HR.'),
    F('evidence_required', 'Supporting evidence required', 'Regularisation', 'tristate',
      'OD / Regularisation'),
    F('request_types', 'Request types allowed', 'Regularisation', 'list',
      'OD / Regularisation', 'e.g. Missing punch, Late approval. Blank allows any.'),
  ],
  [ATT_CLOSURE]: [
    F('closing_day', 'Attendance closing date (day of month)', 'Monthly Cut-off', 'number',
      'Monthly Closure', 'After this day of the following month the period can no longer '
      + 'be edited.'),
    F('enforce_cutoff', 'Enforce the cut-off', 'Monthly Cut-off', 'bool', 'Monthly Closure',
      'Off: the closing date is advisory and edits are still accepted.'),
    F('block_pending_requests', 'Block locking with open requests', 'Monthly Cut-off', 'bool',
      'Monthly Closure'),
    F('lock_cap', 'Lock authority', 'Monthly Cut-off', 'lock_cap', 'Monthly Closure',
      'Which capability may lock and reopen a month. Who holds it is set in Roles & '
      + 'Permissions.'),
  ],
};

// §23 Monthly Closure "lock authority". Mirrors ATTENDANCE_LOCK_ALLOWED_CAPS in
// models/hrms.py — anything outside that set is ignored server-side in favour of the
// default, so offering a wider list here would only invite a silent no-op.
const LOCK_CAP_CHOICES = [
  ['', 'Inherit — HR (attendance.lock)'],
  ['attendance.lock', 'HR (attendance.lock)'],
  ['payroll.approve', 'Finance / payroll approver (payroll.approve)'],
  ['config.approve', 'Configuration approver (config.approve)'],
];

/**
 * The tab strip, and what each tab is a window onto. `categories` names the field tabs it
 * shows (always itself — the indirection exists so Absent can also carry the LOP rules);
 * `scopeOnly` is the applicability tab, which has no rules of its own.
 */
const CONFIG_TABS = [
  {
    key: 'Attendance Policy Group', icon: Users, code: ATT_DAY, scopeOnly: true,
    blurb: 'Which employees the daily rules judge. A group with no boxes ticked is the '
      + 'company-wide default; the most specific match wins. Regularisation and Monthly '
      + 'Cut-off carry their own applicability on their own tabs.',
  },
  {
    key: 'Late Coming', icon: Clock, code: ATT_DAY,
    blurb: 'Grace before a late mark, the monthly buffer, and the escalation threshold.',
  },
  {
    key: 'Early Going', icon: LogOut, code: ATT_DAY,
    blurb: 'Grace before an early mark, and the minimum working hours a day must reach.',
  },
  {
    key: 'Half Day', icon: PieChart, code: ATT_DAY,
    blurb: 'What cuts a day to half — hours worked, or arriving late / leaving early '
      + 'against the shift’s scheduled out — and what a half day is paid.',
  },
  {
    key: 'Absent', icon: CircleSlash, code: ATT_DAY,
    blurb: 'When a day counts as Absent, and how absence and unpaid leave become LOP. '
      + 'A day with no in-punch is Absent whatever is set here.',
  },
  {
    key: 'Regularisation', icon: FileCheck2, code: ATT_REGULARISATION,
    blurb: 'The request window, the approval path, and whether evidence must be attached.',
  },
  {
    key: 'Monthly Cut-off', icon: CalendarClock, code: ATT_CLOSURE,
    blurb: 'When attendance closes, what blocks the lock, and who holds the lock authority.',
  },
];

const POLICY_LABEL = {
  [ATT_DAY]: 'Daily judgement — late, early, half day, absent, LOP',
  [ATT_REGULARISATION]: 'Regularisation and OD requests',
  [ATT_CLOSURE]: 'Monthly closure and cut-off',
};

/**
 * Every §26 / §23 scope key the backend resolves (POLICY_SCOPE_KEYS), ordered so the four
 * dimensions §23 names for rule applicability — employee category, location, level, shift
 * — come first, with the policy group above them because it is the one that usually
 * carries the others.
 */
const SCOPE_FIELDS = [
  ['attendance_policy_groups', 'Attendance policy groups'],
  ['employment_categories', 'Employee categories'],
  ['locations', 'Locations'],
  ['levels', 'Levels'],
  ['shift_codes', 'Shift codes'],
  ['grades', 'Grades'],
  ['departments', 'Department IDs'],
  ['payroll_groups', 'Payroll groups'],
];

/** The payroll cut-off, read-only, beside the attendance one on the Monthly Cut-off tab.
 *
 * §19 keeps `input_cutoff_day` in PAY_POLICY and payroll enforces it there. It is shown
 * and not edited on purpose: a second writable copy would be a second source of truth for
 * one date, and the first time the two disagreed nobody could say which closed the month.
 */
const PayrollCutoffPanel = ({ scope }) => {
  const [policy, setPolicy] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    getPayrollPolicy(scope)
      .then(({ data }) => { if (live) setPolicy(data || {}); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope?.company_id]);

  if (failed) {
    return (
      <p className="text-[11.5px] text-[var(--text-muted)]">
        Payroll cut-off: not visible to you — it is set in the Payroll Policy.
      </p>
    );
  }
  if (!policy) return null;
  const day = policy.input_cutoff_day;
  return (
    <div className="rounded-lg bg-[var(--bg-subtle)] px-3 py-2.5 space-y-1">
      <p className={LABEL}>Payroll cut-off · read-only</p>
      <p className="text-[12px] text-[var(--text-main)]">
        Payroll inputs close on day <b>{day ?? '—'}</b> of the payroll month
        {policy.enforce_input_cutoff
          ? ', enforced.'
          : '. Advisory — edits after it are still accepted.'}
      </p>
      <p className="text-[11.5px] text-[var(--text-muted)]">
        This is the Payroll Policy’s own date (FRD §19) and is changed there, not here —
        one date, one owner. Attendance closing above is the separate attendance lock.
      </p>
    </div>
  );
};

/** §23 Monthly Closure "lock authority" — what the chosen capability actually means. */
const LockAuthorityNote = ({ value, canLock }) => {
  const chosen = LOCK_CAP_CHOICES.find(([v]) => v === (value || '')) || LOCK_CAP_CHOICES[0];
  return (
    <div className="rounded-lg bg-[var(--bg-subtle)] px-3 py-2.5 space-y-1">
      <p className={LABEL}>
        <Lock size={12} className="inline mr-1" />Lock authority
      </p>
      <p className="text-[12px] text-[var(--text-main)]">
        Locking and reopening a month needs <b>{chosen[1]}</b>.
        {' '}You {canLock ? 'hold' : 'do not hold'} the default attendance lock capability.
      </p>
      <p className="text-[11.5px] text-[var(--text-muted)]">
        This names the capability; WHO holds it is a role, set in{' '}
        <a href="/hrms/permissions" className="underline text-[var(--text-main)]">
          Roles &amp; Permissions
        </a>. A capability outside the allowed set falls back to HR rather than widening
        the gate.
      </p>
    </div>
  );
};

const VersionEditor = ({ code, tab, scopeOnly, version, canDraft, canApprove, canLock,
                        scope, onDone, onDirty, showSuccess, showError }) => {
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
  // Only this tab's rules. The SAVE still writes the whole `rules` object, because the four
  // ATT_DAY tabs are one version — a tab is a view, never a separate record.
  const fields = useMemo(
    () => (RULE_FIELDS[code] || []).filter((f) => f.tab === tab),
    [code, tab]);

  // So the parent can ask before moving to a different POLICY, which does remount.
  const vkey = version?.version_no ?? 'new';
  useEffect(() => {
    onDirty?.(vkey, JSON.stringify(rules) !== JSON.stringify(version?.rules || {}));
  }, [rules, version, vkey, onDirty]);
  // Forget this editor on the way out, or the "New version" form — which unmounts the
  // moment its draft saves — would leave a dirty flag behind and prompt on a tab change
  // that has nothing left to lose.
  useEffect(() => () => onDirty?.(vkey, false), [vkey, onDirty]);

  const setRule = (key, raw, type) => setRules((r) => {
    const next = { ...r };
    if (type === 'bool') { next[key] = !!raw; return next; }
    if (type === 'tristate' || type === 'text') {
      // Blank is "inherit", which has to stay distinguishable from an explicit No — an
      // unticked checkbox cannot express that, which is why these are selects.
      if (raw === '' || raw === null) { delete next[key]; return next; }
      next[key] = type === 'tristate' ? raw === 'yes' : raw;
      return next;
    }
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

  const renderField = (f) => {
    const { key, label, type, frd, help } = f;
    const id = `${code}-${key}`;
    const locked = !editable || !canDraft;
    const tri = rules[key] == null ? '' : (rules[key] ? 'yes' : 'no');
    return (
      <div key={key}>
        <label className={LABEL} htmlFor={id}>
          {label} <span className="text-[var(--text-muted)] font-normal">· {frd}</span>
        </label>
        {type === 'bool' ? (
          <label className="flex items-center gap-2 h-9">
            <input id={id} type="checkbox" checked={!!rules[key]} disabled={locked}
              onChange={(e) => setRule(key, e.target.checked, 'bool')} />
            <span className="text-[12px] text-[var(--text-muted)]">
              {rules[key] ? 'Yes' : 'No'}
            </span>
          </label>
        ) : type === 'tristate' ? (
          <select id={id} value={tri} className={FIELD} disabled={locked}
            onChange={(e) => setRule(key, e.target.value, 'tristate')}>
            <option value="">Inherit</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        ) : type === 'levels' ? (
          <select id={id} value={rules[key] ?? ''} className={FIELD} disabled={locked}
            onChange={(e) => setRule(key, e.target.value, 'number')}>
            <option value="">Inherit — whatever this flow already does</option>
            <option value="1">One level — the manager decides</option>
            <option value="2">Two levels — manager, then HR</option>
          </select>
        ) : type === 'lock_cap' ? (
          <select id={id} value={rules[key] ?? ''} className={FIELD} disabled={locked}
            onChange={(e) => setRule(key, e.target.value, 'text')}>
            {LOCK_CAP_CHOICES.map(([v, text]) => (
              <option key={v || 'inherit'} value={v}>{text}</option>
            ))}
          </select>
        ) : type === 'list' ? (
          <input id={id} defaultValue={(rules[key] || []).join(', ')} className={FIELD}
            placeholder="comma separated — blank: inherit" disabled={locked}
            onBlur={(e) => setRule(key, e.target.value, 'list')} />
        ) : type === 'fraction' ? (
          <select id={id} value={rules[key] ?? ''} className={FIELD} disabled={locked}
            onChange={(e) => setRule(key, e.target.value, 'number')}>
            <option value="">Inherit (half)</option>
            <option value="0">Nothing — a full day&apos;s LOP</option>
            <option value="0.25">A quarter day</option>
            <option value="0.5">Half a day</option>
            <option value="0.75">Three quarters</option>
          </select>
        ) : type === 'hours' ? (
          <input id={id} type="number" min="0" max="24" step="0.25" value={rules[key] ?? ''}
            className={FIELD} placeholder="inherit" disabled={locked}
            onChange={(e) => setRule(key, e.target.value, 'number')} />
        ) : (
          <input id={id} type="number" min="0" value={rules[key] ?? ''} className={FIELD}
            placeholder="inherit" disabled={locked}
            onChange={(e) => setRule(key, e.target.value, 'number')} />
        )}
        {help && <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{help}</p>}
      </div>
    );
  };

  return (
    <div className="rounded-lg border border-[var(--border)] px-3.5 py-3 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[12.5px] font-bold text-[var(--text-main)]">
          {version ? `Version ${version.version_no}` : 'New version'}
        </h3>
        {version && <Chip tone={STATUS_TONE[version.status] || 'neutral'}>{version.status}</Chip>}
        {code === ATT_DAY && (
          <span className="text-[11px] text-[var(--text-muted)]">
            Shared with the Late Coming, Early Going, Half Day and Absent tabs — one
            version judges the day.
          </span>
        )}
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

      {!scopeOnly && (
        <div>
          <p className={LABEL}>
            {tab} rules — blank means inherit from the shift or company policy
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-1">
            {fields.map(renderField)}
          </div>
        </div>
      )}

      {tab === 'Monthly Cut-off' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <PayrollCutoffPanel scope={scope} />
          <LockAuthorityNote value={rules.lock_cap} canLock={canLock} />
        </div>
      )}

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
            {code !== ATT_CLOSURE && (
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
          {sim && code === ATT_REGULARISATION && (
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
          {sim && code === ATT_CLOSURE && (
            <div className="text-[12px] text-[var(--text-main)] space-y-1">
              <p>{sim.pending_requests} request(s) are still open for {sim.period}.</p>
              <p>Today: cut-off {sim.was?.cutoff_date || 'not enforced'}, locking {sim.was?.locking_blocked ? 'blocked' : 'allowed'}.</p>
              <p>Draft: cut-off {sim.now?.cutoff_date || 'not enforced'}, locking {sim.now?.locking_blocked ? 'blocked' : 'allowed'}.</p>
            </div>
          )}
          {sim && code === ATT_DAY && (
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

const AttendanceConfiguration = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [tab, setTab] = useState(CONFIG_TABS[0].key);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);

  const canDraft = can(CAP.CONFIG_DRAFT);
  const canApprove = can(CAP.CONFIG_APPROVE);
  const canLock = can(CAP.ATTENDANCE_LOCK);

  const active = CONFIG_TABS.find((t) => t.key === tab) || CONFIG_TABS[0];
  const code = active.code;

  // Which versions have unsaved edits, so moving to a DIFFERENT policy (which reloads and
  // remounts) can ask first. Hopping between the four ATT_DAY tabs keeps the same editor
  // mounted and needs no warning.
  const dirty = useRef(new Set());
  const markDirty = useCallback((vkey, isDirty) => {
    if (isDirty) dirty.current.add(vkey); else dirty.current.delete(vkey);
  }, []);

  const switchTab = (key) => {
    const next = CONFIG_TABS.find((t) => t.key === key);
    if (next && next.code !== code && dirty.current.size
        && !window.confirm('This policy has unsaved rule changes. Leave them behind?')) {
      return;
    }
    if (next && next.code !== code) dirty.current.clear();
    setTab(key);
  };

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

  const editorProps = {
    code, tab, scopeOnly: active.scopeOnly, canDraft, canApprove, canLock, scope,
    onDone: load, onDirty: markDirty, showSuccess, showError,
  };

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={SlidersHorizontal}
        title="Attendance Configuration"
        subtitle="Versioned, effective-dated rules for policy groups, late coming, early going, half day, absent, regularisation and the monthly cut-off (FRD §23)."
      />
      <HrmsScopeBar />

      <BoardTabs tabs={CONFIG_TABS} value={tab} onChange={switchTab}
        label="Attendance configuration sections" />

      <p className="text-[12px] text-[var(--text-muted)] max-w-3xl">{active.blurb}</p>

      {loading && <HrmsLoading label="Loading policy versions…" />}
      {error && <HrmsError message={error} />}

      {!loading && !error && (
        <div className="space-y-3">
          {canDraft && !adding && (
            <Btn onClick={() => setAdding(true)}>New version</Btn>
          )}
          {adding && (
            <VersionEditor {...editorProps} version={null} />
          )}
          {!versions.length && !adding && (
            <HrmsEmpty icon={SlidersHorizontal} title="No versions yet"
              message="This company is running on its shift and company settings. Create a version to override them from a date." />
          )}
          {versions.map((v) => (
            <VersionEditor key={v.version_no} {...editorProps} version={v} />
          ))}
        </div>
      )}
    </div>
  );
};

export default AttendanceConfiguration;
