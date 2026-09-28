import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Info, Plus, AlertTriangle } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  listSalaryComponents, saveSalaryStructure, getSalaryStructureHistory,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, day } from '../internal/internalKit';
import { Btn, Chip, Modal } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ one employee's salary structure — the figures payroll actually pays from.
 *
 * Mounted in two places so there is one way to do this, not two that drift:
 *   - the employee's own page (Salary tab), where HR naturally looks for "their salary";
 *   - Payroll ▸ Salary Structure, after picking the employee.
 *
 * A structure is never edited. A pay change is a NEW structure with its own "effective
 * from" date; payroll uses the latest one that has started by the month being paid
 * (hrms_payroll_service.get_current_structure). So the list below is also the pay history.
 */

const todayIso = () => new Date().toLocaleDateString('en-CA');
const money = (n) => `₹${(Number(n) || 0).toLocaleString('en-IN')}`;

const EmployeeSalaryStructure = ({ employeeCode, employeeName, employmentStatus, components: given }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [components, setComponents] = useState(given || []);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);

  const canManage = can(CAP.SALARY_STRUCTURE_MANAGE);

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
      setError(err?.response?.data?.detail || 'Could not load the salary structure.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeCode, scope.company_id, given]);

  useEffect(() => { load(); }, [load]);

  const typeOf = useMemo(
    () => Object.fromEntries(components.map((c) => [c.code, c])), [components]);

  // Newest first from the server; the one in force is the first that has already started.
  const today = todayIso();
  const currentIdx = history.findIndex((h) => (h.effective_from || '') <= today);
  const current = currentIdx >= 0 ? history[currentIdx] : null;

  if (loading) return <HrmsLoading label="Loading salary…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

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
        <StructureCard key={h.id || h.effective_from} structure={h} typeOf={typeOf}
          label={i === currentIdx ? 'Current'
            : (h.effective_from || '') > today ? `Starts ${day(h.effective_from)}` : 'Earlier'}
          highlight={i === currentIdx} />
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

const totalsOf = (lines, typeOf) => {
  let earnings = 0; let deductions = 0;
  for (const l of lines) {
    const amt = Number(l.amount) || 0;
    if (typeOf[l.code]?.component_type === 'Deduction') deductions += amt; else earnings += amt;
  }
  return { earnings, deductions, net: earnings - deductions };
};

const StructureCard = ({ structure, typeOf, label, highlight }) => {
  const lines = structure.components || [];
  const t = totalsOf(lines, typeOf);
  return (
    <div className={`rounded-xl border bg-[var(--bg-card)] p-4 ${highlight
      ? 'border-[var(--accent-indigo)]' : 'border-[var(--border)] opacity-80'}`}>
      <div className="flex items-center justify-between gap-2">
        <Chip tone={highlight ? 'good' : undefined}>{label}</Chip>
        <span className="text-[11.5px] text-[var(--text-muted)]">From {day(structure.effective_from)}</span>
      </div>
      <div className="mt-3 grid gap-1">
        {lines.map((l) => (
          <div key={l.code} className="flex justify-between text-[12.5px]">
            <span className="text-[var(--text-main)]">
              {typeOf[l.code]?.name || l.code}
              {typeOf[l.code]?.component_type === 'Deduction' && (
                <span className="text-[var(--text-muted)]"> (deduction)</span>
              )}
            </span>
            <span className="text-[var(--text-main)]">
              {typeOf[l.code]?.component_type === 'Deduction' ? '− ' : ''}{money(l.amount)}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-3 pt-2.5 border-t border-[var(--border)] grid grid-cols-3 gap-2 text-[12px]">
        <div><p className="text-[var(--text-muted)]">Monthly earnings</p><p className="font-bold">{money(t.earnings)}</p></div>
        <div><p className="text-[var(--text-muted)]">Deductions</p><p className="font-bold">{money(t.deductions)}</p></div>
        <div><p className="text-[var(--text-muted)]">Take-home (before tax/PF)</p><p className="font-bold">{money(t.net)}</p></div>
      </div>
    </div>
  );
};

export const StructureModal = ({
  employeeCode, employeeName, components, startFrom, scope, onClose, onDone, showSuccess, showError,
}) => {
  const [effectiveFrom, setEffectiveFrom] = useState(todayIso());
  // A pay change usually alters one or two lines, so start from what they get today.
  const [amounts, setAmounts] = useState(() => Object.fromEntries(
    (startFrom?.components || []).map((c) => [c.code, String(c.amount)])));
  const [busy, setBusy] = useState(false);

  const typeOf = Object.fromEntries(components.map((c) => [c.code, c]));
  const rows = Object.entries(amounts)
    .filter(([, v]) => Number(v) > 0)
    .map(([code, amount]) => ({ code, amount: Number(amount) }));
  const t = totalsOf(rows, typeOf);

  const submit = async () => {
    if (!rows.length) { showError('Enter at least one amount.'); return; }
    setBusy(true);
    try {
      await saveSalaryStructure({ employee_code: employeeCode, effective_from: effectiveFrom, components: rows }, scope);
      showSuccess('Salary saved. Payroll will use it from the date you chose.');
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the salary.');
    } finally {
      setBusy(false);
    }
  };

  const section = (type, title) => {
    const list = components.filter((c) => (c.component_type || 'Earning') === type);
    if (!list.length) return null;
    return (
      <div className="space-y-2">
        <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{title}</p>
        {list.map((c) => (
          <div key={c.code} className="grid grid-cols-[1fr_150px] items-center gap-3">
            <label htmlFor={`amt-${c.code}`} className="text-[12.5px] text-[var(--text-main)]">{c.name}</label>
            <input id={`amt-${c.code}`} type="number" min="0" inputMode="decimal" placeholder="0"
              className={FIELD} value={amounts[c.code] || ''}
              onChange={(e) => setAmounts({ ...amounts, [c.code]: e.target.value })} />
          </div>
        ))}
      </div>
    );
  };

  return (
    <Modal title={startFrom ? 'Change salary' : 'Set salary'} labelledBy="structure-title"
      subtitle={`${employeeName ? `${employeeName} · ` : ''}${employeeCode} · monthly amounts in ₹`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !rows.length}>
            {busy ? 'Saving…' : 'Save salary'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="structure-date">Starts from</label>
        <input id="structure-date" type="date" value={effectiveFrom} className={FIELD}
          onChange={(e) => setEffectiveFrom(e.target.value)} />
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          Payroll uses this salary for any month on or after this date. Earlier months keep the old one.
        </p>
      </div>
      {section('Earning', 'Earnings')}
      {section('Deduction', 'Deductions')}
      <div className="rounded-lg bg-[var(--input-bg)] px-3.5 py-2.5 grid grid-cols-3 gap-2 text-[12px]">
        <div><p className="text-[var(--text-muted)]">Earnings</p><p className="font-bold">{money(t.earnings)}</p></div>
        <div><p className="text-[var(--text-muted)]">Deductions</p><p className="font-bold">{money(t.deductions)}</p></div>
        <div><p className="text-[var(--text-muted)]">Take-home</p><p className="font-bold">{money(t.net)}</p></div>
      </div>
    </Modal>
  );
};

export default EmployeeSalaryStructure;
