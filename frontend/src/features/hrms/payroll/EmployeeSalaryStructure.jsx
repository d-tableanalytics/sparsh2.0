import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Info, Plus, AlertTriangle } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  listSalaryComponents, saveSalaryStructure, getSalaryStructureHistory, decideSalaryStructure,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Modal } from '../internal/internalKit.jsx';
import { DEDUCTING_TYPES, errText, when, useSubmit } from './payrollKit';

/**
 * HRMS ▸ one employee's salary structure — the figures payroll actually pays from (FRD §9).
 *
 * Mounted in two places so there is one way to do this, not two that drift:
 *   - the employee's own page (Salary tab), where HR naturally looks for "their salary";
 *   - Payroll ▸ Salary Structure, after picking the employee.
 *
 * A structure is never edited. A pay change is a NEW structure with its own "effective
 * from" date; payroll uses the latest APPROVED one that has started by the month being paid
 * (hrms_payroll_service.get_current_structure). So the list below is also the pay history,
 * each entry with the date it ran to. When the payroll policy asks for it, a new structure
 * waits as "Pending Approval" — and is not paid — until someone other than its maker, holding
 * payroll approval, accepts it.
 *
 * Percentage components (e.g. HRA = 40% of BASIC) are worked out by the server from their
 * base; the figure shown while editing is an estimate of that, not what is saved.
 */

const todayIso = () => new Date().toLocaleDateString('en-CA');
const money = (n) => `₹${(Number(n) || 0).toLocaleString('en-IN')}`;
const NOT_PAID = ['Pending Approval', 'Rejected'];

const isPct = (c) => c?.calculation_method === 'Percentage';
// Formula / Slab lines: included or not; the amount is worked out by the server on save.
const isComputed = (c) => ['Formula', 'Slab'].includes(c?.calculation_method);
const baseLabel = (code, typeOf) => (code === 'GROSS' ? 'gross' : code === 'CTC' ? 'CTC'
  : typeOf[code]?.name || code);

/** Monthly totals by component type — the server's figures when it sent them. */
const totalsOf = (structure, lines, typeOf) => {
  if (structure?.monthly_gross != null) {
    return {
      gross: structure.monthly_gross, deductions: structure.monthly_deductions,
      employer: structure.monthly_employer_contributions, net: structure.monthly_net,
    };
  }
  let gross = 0; let deductions = 0; let employer = 0;
  for (const l of lines) {
    const amt = Number(l.amount) || 0;
    const type = typeOf[l.code]?.component_type || 'Earning';
    if (DEDUCTING_TYPES.includes(type)) deductions += amt;
    else if (type === 'Employer Contribution') employer += amt;
    else if (type === 'Earning' || type === 'Reimbursement') gross += amt;
  }
  return { gross, deductions, employer, net: gross - deductions };
};

const roundBy = (amount, rule) => {
  if (rule === 'Nearest') return Math.round(amount);
  if (rule === 'Floor') return Math.floor(amount);
  if (rule === 'Ceiling') return Math.ceil(amount);
  return Math.round(amount * 100) / 100;
};

/** The server's resolve_lines, client-side, for the preview only: in sequence order, a
 *  percentage line is worked out from a base already resolved, GROSS (earnings so far) or
 *  CTC (annual ÷ 12). `null` means "cannot be worked out yet" (base missing or later). */
const previewLines = (lines, typeOf, annualCtc) => {
  const ordered = lines.map((l, i) => [i, l]).sort((a, b) => (
    ((typeOf[a[1].code]?.sequence ?? 100) - (typeOf[b[1].code]?.sequence ?? 100)) || a[0] - b[0]));
  const resolved = {};
  for (const [, l] of ordered) {
    const m = typeOf[l.code] || {};
    let amount;
    if (isPct(m)) {
      const pct = Number(l.percentage ?? m.percentage);
      let base = null;
      if (m.calculation_base === 'GROSS') {
        base = Object.entries(resolved)
          .filter(([c, v]) => v != null && (typeOf[c]?.component_type || 'Earning') === 'Earning')
          .reduce((s, [, v]) => s + v, 0);
      } else if (m.calculation_base === 'CTC') {
        base = Number(annualCtc) > 0 ? Number(annualCtc) / 12 : null;
      } else {
        base = resolved[m.calculation_base] ?? null;
      }
      amount = base == null || Number.isNaN(pct) ? null : (base * pct) / 100;
    } else if (isComputed(m)) {
      amount = null;
    } else {
      amount = Number(l.amount) || 0;
    }
    if (amount != null) {
      if (m.min_amount != null) amount = Math.max(amount, Number(m.min_amount));
      if (m.max_amount != null) amount = Math.min(amount, Number(m.max_amount));
      amount = roundBy(amount, m.rounding);
    }
    resolved[l.code] = amount;
  }
  return resolved;
};

const EmployeeSalaryStructure = ({ employeeCode, employeeName, employmentStatus, components: given }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [components, setComponents] = useState(given || []);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);

  const canManage = can(CAP.SALARY_STRUCTURE_MANAGE);
  const canDecide = can(CAP.PAYROLL_APPROVE);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [comps, hist] = await Promise.all([
        given ? Promise.resolve({ data: given }) : listSalaryComponents(scope),
        getSalaryStructureHistory(employeeCode, scope),
      ]);
      setComponents(comps.data || []);
      setHistory(hist.data || []);
    } catch (err) {
      setError(errText(err, 'Could not load the salary structure.'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeCode, scope.company_id, given]);

  useEffect(() => { load(); }, [load]);

  const typeOf = useMemo(
    () => Object.fromEntries(components.map((c) => [c.code, c])), [components]);

  // Newest first from the server; the one in force is the first APPROVED one already started.
  const today = todayIso();
  const currentIdx = history.findIndex((h) => !NOT_PAID.includes(h.status)
    && (h.effective_from || '') <= today);
  const current = currentIdx >= 0 ? history[currentIdx] : null;
  const pending = history.filter((h) => h.status === 'Pending Approval').length;

  if (loading) return <HrmsLoading label="Loading salary…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  const labelOf = (h, i) => {
    if (h.status === 'Pending Approval') return 'Pending approval';
    if (h.status === 'Rejected') return 'Rejected';
    if (i === currentIdx) return 'Current';
    return (h.effective_from || '') > today ? `Starts ${day(h.effective_from)}` : 'Earlier';
  };

  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-[var(--accent-indigo-bg)] px-4 py-3 flex items-start gap-2.5">
        <Info size={16} className="text-[var(--accent-indigo)] shrink-0 mt-0.5" />
        <p className="text-[12.5px] text-[var(--text-main)]">
          <span className="font-bold">This is what payroll pays from.</span>{' '}
          Every month, payroll takes the salary below, adjusts it for days worked, and adds any
          advance recovery or variable pay. To change someone&apos;s pay, add a new structure
          with the date it starts — the old one is kept as history.
        </p>
      </div>

      {employmentStatus && employmentStatus !== 'Active' && (
        <div className="rounded-xl bg-[var(--accent-orange-bg)] px-4 py-3 flex items-start gap-2.5">
          <AlertTriangle size={16} className="text-[var(--accent-orange)] shrink-0 mt-0.5" />
          <p className="text-[12.5px] text-[var(--text-main)]">
            {employeeName || 'This employee'} is <span className="font-bold">{employmentStatus}</span>.
            Payroll only includes employees whose status is <span className="font-bold">Active</span>.
          </p>
        </div>
      )}

      {pending > 0 && (
        <div className="rounded-xl bg-[var(--accent-orange-bg)] px-4 py-3 text-[12.5px] text-[var(--text-main)]">
          <span className="font-bold">{pending} salary change(s) waiting for approval.</span>{' '}
          {canDecide
            ? 'Approve or reject below — you cannot approve one you set yourself.'
            : 'They are not paid until a payroll approver accepts them.'}
        </div>
      )}

      {!components.length ? (
        <div className="rounded-xl border border-[var(--border)] p-4 text-[12.5px] text-[var(--text-muted)]">
          No pay components are set up yet — these are the lines a salary is made of, like
          Basic or HRA. Add them once in{' '}
          <Link to="/hrms/payroll" className="font-bold text-[var(--accent-indigo)] hover:underline">
            Payroll → Salary Structure
          </Link>, then come back here.
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {current ? 'Current salary' : 'No salary set yet'}
          </p>
          {canManage && (
            <Btn tone="primary" onClick={() => setEditing(true)}>
              <Plus size={14} /> {current ? 'Change salary' : 'Set salary'}
            </Btn>
          )}
        </div>
      )}

      {components.length > 0 && !history.length && (
        <p className="text-[12.5px] text-[var(--text-muted)]">
          Until a salary is set, payroll will show this employee&apos;s pay as ₹0.
        </p>
      )}

      {history.map((h, i) => (
        <StructureCard key={h.id || `${h.effective_from}-${i}`} structure={h} typeOf={typeOf}
          label={labelOf(h, i)} highlight={i === currentIdx}
          canDecide={canDecide && h.status === 'Pending Approval'} scope={scope}
          onDecided={load} showSuccess={showSuccess} showError={showError} />
      ))}

      {editing && (
        <StructureModal employeeCode={employeeCode} employeeName={employeeName}
          components={components} startFrom={current}
          onClose={() => setEditing(false)}
          onDone={() => { setEditing(false); load(); }}
          scope={scope} showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const STATUS_TONE = { 'Pending approval': 'warn', Rejected: 'bad', Current: 'good' };

const StructureCard = ({
  structure, typeOf, label, highlight, canDecide, scope, onDecided, showSuccess, showError,
}) => {
  const [comments, setComments] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDecided);
  const lines = structure.components || [];
  const t = totalsOf(structure, lines, typeOf);
  const pendingOrRejected = NOT_PAID.includes(structure.status);
  const decide = (approved) => run(
    () => decideSalaryStructure(structure.id, { approved, comments: comments.trim() || undefined }, scope),
    approved ? 'Salary approved — payroll will use it.' : 'Salary change rejected.');

  return (
    <div className={`rounded-xl border bg-[var(--bg-card)] p-4 ${highlight
      ? 'border-[var(--accent-indigo)]'
      : pendingOrRejected ? 'border-[var(--accent-orange)]/50' : 'border-[var(--border)] opacity-80'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <Chip tone={STATUS_TONE[label]}>{label}</Chip>
          {structure.structure_name && (
            <span className="text-[12.5px] font-bold text-[var(--text-main)] truncate">{structure.structure_name}</span>
          )}
        </div>
        <span className="text-[11.5px] text-[var(--text-muted)]">
          {day(structure.effective_from)}{structure.effective_to ? ` – ${day(structure.effective_to)}` : ' onwards'}
        </span>
      </div>
      {structure.revision_reason && (
        <p className="mt-1.5 text-[12px] text-[var(--text-main)]">
          <span className="text-[var(--text-muted)]">Reason:</span> {structure.revision_reason}
        </p>
      )}

      <div className="mt-3 grid gap-1">
        {lines.map((l) => {
          const c = typeOf[l.code];
          const deducting = DEDUCTING_TYPES.includes(c?.component_type);
          return (
            <div key={l.code} className="flex justify-between gap-3 text-[12.5px]">
              <span className="text-[var(--text-main)] min-w-0">
                {c?.name || l.code}
                {l.method === 'Percentage' && l.percentage != null && (
                  <span className="text-[var(--text-muted)]"> · {l.percentage}% of {baseLabel(l.base, typeOf)}</span>
                )}
                {deducting && <span className="text-[var(--text-muted)]"> (deduction)</span>}
                {c?.component_type === 'Employer Contribution' && (
                  <span className="text-[var(--text-muted)]"> (paid by the company)</span>
                )}
              </span>
              <span className="text-[var(--text-main)] shrink-0">{deducting ? '− ' : ''}{money(l.amount)}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 pt-2.5 border-t border-[var(--border)] grid grid-cols-2 sm:grid-cols-4 gap-2 text-[12px]">
        <div><p className="text-[var(--text-muted)]">Monthly gross</p><p className="font-bold">{money(t.gross)}</p></div>
        <div><p className="text-[var(--text-muted)]">Deductions</p><p className="font-bold">{money(t.deductions)}</p></div>
        <div><p className="text-[var(--text-muted)]">Employer contrib.</p><p className="font-bold">{money(t.employer)}</p></div>
        <div><p className="text-[var(--text-muted)]">Take-home (before tax/PF)</p><p className="font-bold">{money(t.net)}</p></div>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-[var(--text-muted)]">
        {structure.annual_ctc != null && (
          <span>Annual CTC <b className="text-[var(--text-main)]">{money(structure.annual_ctc)}</b></span>
        )}
        {structure.payroll_group && <span>Group {structure.payroll_group}</span>}
        {structure.created_by_name && <span>Set by {structure.created_by_name}</span>}
        {structure.approved_by_name && structure.status !== 'Pending Approval' && (
          <span>
            {structure.status === 'Rejected' ? 'Rejected' : 'Approved'} by {structure.approved_by_name}
            {structure.approved_at && ` · ${when(structure.approved_at)}`}
            {structure.approval_mode && ` (${structure.approval_mode})`}
          </span>
        )}
      </div>
      {structure.comments && (
        <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">Comments: {structure.comments}</p>
      )}
      {structure.decision_comments && (
        <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">Approver&apos;s note: {structure.decision_comments}</p>
      )}

      {canDecide && (
        <div className="mt-3 pt-3 border-t border-[var(--border)] space-y-2">
          <label className={LABEL} htmlFor={`decide-${structure.id}`}>Approver&apos;s comments</label>
          <input id={`decide-${structure.id}`} value={comments} className={FIELD}
            onChange={(e) => setComments(e.target.value)} />
          <div className="flex justify-end gap-2">
            <Btn tone="danger" disabled={busy} onClick={() => decide(false)}>Reject</Btn>
            <Btn tone="primary" disabled={busy} onClick={() => decide(true)}>{busy ? 'Working…' : 'Approve'}</Btn>
          </div>
        </div>
      )}
    </div>
  );
};

const SECTION_TYPES = [
  [['Earning'], 'Earnings'],
  [['Reimbursement'], 'Reimbursements'],
  [['Deduction', 'Recovery'], 'Deductions'],
  [['Employer Contribution'], 'Employer contributions (on top of gross)'],
  [['Informational'], 'For information only'],
];

export const StructureModal = ({
  employeeCode, employeeName, components, startFrom, scope, onClose, onDone, showSuccess, showError,
}) => {
  const usable = components.filter((c) => c.active !== false);
  const typeOf = Object.fromEntries(components.map((c) => [c.code, c]));
  const [effectiveFrom, setEffectiveFrom] = useState(todayIso());
  const [structureName, setStructureName] = useState(startFrom?.structure_name || '');
  const [reason, setReason] = useState('');
  const [annualCtc, setAnnualCtc] = useState('');
  const [payrollGroup, setPayrollGroup] = useState(startFrom?.payroll_group || '');
  const [comments, setComments] = useState('');
  // A pay change usually alters one or two lines, so start from what they get today. Fixed
  // lines keep an amount; a percentage line keeps its percentage (present = included).
  const [amounts, setAmounts] = useState(() => Object.fromEntries(
    (startFrom?.components || []).filter((l) => !isPct(typeOf[l.code]) && !isComputed(typeOf[l.code]))
      .map((l) => [l.code, String(l.amount)])));
  const [computed, setComputed] = useState(() => new Set(
    (startFrom?.components || []).filter((l) => isComputed(typeOf[l.code])).map((l) => l.code)));
  const [pcts, setPcts] = useState(() => Object.fromEntries(
    (startFrom?.components || []).filter((l) => isPct(typeOf[l.code]))
      .map((l) => [l.code, String(l.percentage ?? typeOf[l.code]?.percentage ?? '')])));
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState(null);

  const retiredCarried = (startFrom?.components || [])
    .filter((l) => typeOf[l.code]?.active === false).map((l) => typeOf[l.code]?.name || l.code);

  const lines = [
    ...usable.filter((c) => !isPct(c) && !isComputed(c) && Number(amounts[c.code]) > 0)
      .map((c) => ({ code: c.code, amount: Number(amounts[c.code]) })),
    ...usable.filter((c) => isComputed(c) && computed.has(c.code))
      .map((c) => ({ code: c.code, amount: 0 })),
    ...usable.filter((c) => isPct(c) && pcts[c.code] != null)
      .map((c) => ({ code: c.code, amount: 0, percentage: Number(pcts[c.code]) })),
  ];
  const resolved = previewLines(lines, typeOf, annualCtc);
  const t = totalsOf(null, lines.map((l) => ({ code: l.code, amount: resolved[l.code] || 0 })), typeOf);

  const togglePct = (c) => setPcts((p) => {
    const next = { ...p };
    if (next[c.code] != null) delete next[c.code];
    else next[c.code] = String(c.percentage ?? '');
    return next;
  });

  const submit = async () => {
    if (!lines.length) { showError('Enter at least one amount.'); return; }
    const badPct = lines.find((l) => l.percentage != null && !(l.percentage > 0));
    if (badPct) { showError(`Enter a percentage above 0 for ${typeOf[badPct.code]?.name || badPct.code}.`); return; }
    if (annualCtc !== '' && !(Number(annualCtc) > 0)) { showError('Annual CTC must be above 0, or left blank.'); return; }
    setBusy(true); setSaveError(null);
    try {
      const { data } = await saveSalaryStructure({
        employee_code: employeeCode, effective_from: effectiveFrom,
        // Send a percentage only when it overrides the component's own — otherwise a later
        // change to the component's default would never reach this salary.
        components: lines.map((l) => (l.percentage != null
          ? { code: l.code, amount: 0,
            ...(Number(l.percentage) !== Number(typeOf[l.code]?.percentage) ? { percentage: l.percentage } : {}) }
          : { code: l.code, amount: l.amount })),
        structure_name: structureName.trim() || undefined,
        revision_reason: reason.trim() || undefined,
        annual_ctc: annualCtc === '' ? undefined : Number(annualCtc),
        payroll_group: payrollGroup.trim() || undefined,
        comments: comments.trim() || undefined,
      }, scope);
      showSuccess(data?.status === 'Pending Approval'
        ? 'Saved — waiting for a payroll approver. It is not paid until approved.'
        : 'Salary saved. Payroll will use it from the date you chose.');
      onDone();
    } catch (err) {
      const msg = errText(err, 'Could not save the salary.');
      setSaveError(msg);
      showError(msg);
    } finally {
      setBusy(false);
    }
  };

  const section = (types, title) => {
    const list = usable.filter((c) => types.includes(c.component_type || 'Earning'));
    if (!list.length) return null;
    return (
      <div className="space-y-2">
        <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{title}</p>
        {list.map((c) => (isComputed(c) ? (
          <div key={c.code} className="grid grid-cols-[1fr_auto] items-center gap-3">
            <label className="flex items-start gap-2 text-[12.5px] text-[var(--text-main)] min-w-0">
              <input type="checkbox" className="mt-0.5" checked={computed.has(c.code)}
                onChange={() => setComputed((s) => {
                  const next = new Set(s);
                  if (next.has(c.code)) next.delete(c.code); else next.add(c.code);
                  return next;
                })} />
              <span className="min-w-0">
                {c.name}
                <span className="block text-[11px] text-[var(--text-muted)] break-words">
                  {c.calculation_method === 'Formula' ? `= ${c.formula}` : `Slab on ${baseLabel(c.calculation_base, typeOf)}`}
                </span>
              </span>
            </label>
            <span className="text-right text-[12px] text-[var(--text-muted)]">
              {computed.has(c.code) ? 'worked out on save' : 'not included'}
            </span>
          </div>
        ) : isPct(c) ? (
          <div key={c.code} className="grid grid-cols-[1fr_84px] sm:grid-cols-[1fr_96px_110px] items-center gap-x-3 gap-y-1">
            <label className="flex items-start gap-2 text-[12.5px] text-[var(--text-main)] min-w-0">
              <input type="checkbox" className="mt-0.5" checked={pcts[c.code] != null} onChange={() => togglePct(c)} />
              <span className="min-w-0">
                {c.name}
                <span className="block text-[11px] text-[var(--text-muted)]">
                  % of {baseLabel(c.calculation_base, typeOf)} (default {c.percentage ?? '—'}%)
                </span>
              </span>
            </label>
            <div className="relative">
              <input type="number" min="0" step="0.01" inputMode="decimal" aria-label={`${c.name} percentage`}
                className={`${FIELD} pr-6`} disabled={pcts[c.code] == null}
                value={pcts[c.code] ?? ''} placeholder={String(c.percentage ?? '')}
                onChange={(e) => setPcts({ ...pcts, [c.code]: e.target.value })} />
              <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[12px] text-[var(--text-muted)]">%</span>
            </div>
            <span className="col-span-2 sm:col-span-1 text-right text-[12px] text-[var(--text-muted)]">
              {pcts[c.code] == null ? 'not included'
                : resolved[c.code] == null
                  ? (c.calculation_base === 'CTC' ? 'enter annual CTC' : `needs ${baseLabel(c.calculation_base, typeOf)}`)
                  : `≈ ${money(resolved[c.code])}`}
            </span>
          </div>
        ) : (
          <div key={c.code} className="grid grid-cols-[1fr_150px] items-center gap-3">
            <label htmlFor={`amt-${c.code}`} className="text-[12.5px] text-[var(--text-main)]">
              {c.name}
              {c.calculation_method === 'Manual Input' && (
                <span className="block text-[11px] text-[var(--text-muted)]">Usually typed in each month</span>
              )}
            </label>
            <input id={`amt-${c.code}`} type="number" min="0" inputMode="decimal" placeholder="0"
              className={FIELD} value={amounts[c.code] || ''}
              onChange={(e) => setAmounts({ ...amounts, [c.code]: e.target.value })} />
          </div>
        )))}
      </div>
    );
  };

  return (
    <Modal title={startFrom ? 'Change salary' : 'Set salary'} labelledBy="structure-title" wide
      subtitle={`${employeeName ? `${employeeName} · ` : ''}${employeeCode} · monthly amounts in ₹`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !lines.length}>
            {busy ? 'Saving…' : 'Save salary'}
          </Btn>
        </>
      )}
    >
      {saveError && (
        <div className="rounded-lg px-3.5 py-2.5 flex items-start gap-2 bg-[var(--accent-red-bg)]">
          <AlertTriangle size={16} className="shrink-0 mt-0.5 text-[var(--accent-red)]" />
          <p className="text-[12.5px] font-semibold text-[var(--accent-red)]">{saveError}</p>
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="structure-date">Starts from *</label>
          <input id="structure-date" type="date" value={effectiveFrom} className={FIELD}
            onChange={(e) => setEffectiveFrom(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="structure-name">Structure name</label>
          <input id="structure-name" value={structureName} className={FIELD} placeholder="e.g. Staff Grade B"
            onChange={(e) => setStructureName(e.target.value)} />
        </div>
      </div>
      <p className="-mt-1.5 text-[11px] text-[var(--text-muted)]">
        Payroll uses this salary for any month on or after this date. It cannot start inside a
        month whose payroll is already locked — pay that difference as an arrear instead.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="sm:col-span-2">
          <label className={LABEL} htmlFor="structure-reason">Reason for the change</label>
          <input id="structure-reason" value={reason} className={FIELD}
            placeholder={startFrom ? 'e.g. Annual increment' : 'e.g. New joiner'}
            onChange={(e) => setReason(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="structure-group">Payroll group</label>
          <input id="structure-group" value={payrollGroup} className={FIELD}
            onChange={(e) => setPayrollGroup(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="structure-ctc">Annual CTC</label>
        <input id="structure-ctc" type="number" min="0" inputMode="decimal" value={annualCtc} className={FIELD}
          placeholder={`Leave blank to work it out (≈ ${money((t.gross + t.employer) * 12)})`}
          onChange={(e) => setAnnualCtc(e.target.value)} />
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          Needed only when a line is a percentage of CTC.
        </p>
      </div>

      {retiredCarried.length > 0 && (
        <p className="text-[11.5px] text-[var(--accent-orange)]">
          {retiredCarried.join(', ')} {retiredCarried.length === 1 ? 'is' : 'are'} retired and left out of the new salary.
        </p>
      )}
      {SECTION_TYPES.map(([types, title]) => (
        <React.Fragment key={title}>{section(types, title)}</React.Fragment>
      ))}

      <div className="rounded-lg bg-[var(--input-bg)] px-3.5 py-2.5 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[12px]">
        <div><p className="text-[var(--text-muted)]">Gross</p><p className="font-bold">{money(t.gross)}</p></div>
        <div><p className="text-[var(--text-muted)]">Deductions</p><p className="font-bold">{money(t.deductions)}</p></div>
        <div><p className="text-[var(--text-muted)]">Employer contrib.</p><p className="font-bold">{money(t.employer)}</p></div>
        <div><p className="text-[var(--text-muted)]">Take-home</p><p className="font-bold">{money(t.net)}</p></div>
      </div>
      <p className="-mt-1.5 text-[11px] text-[var(--text-muted)]">
        Percentage lines are estimates here; the saved salary uses the server&apos;s figures.
      </p>

      <div>
        <label className={LABEL} htmlFor="structure-comments">Comments</label>
        <textarea id="structure-comments" rows={2} value={comments} className={TEXTAREA}
          onChange={(e) => setComments(e.target.value)} />
      </div>
    </Modal>
  );
};

export default EmployeeSalaryStructure;
