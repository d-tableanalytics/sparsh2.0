import React, { useEffect, useState } from 'react';
import {
  saveSalaryComponent, simulateSalaryComponent, listCalculationVariables,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import {
  COMPONENT_TYPES, METHODS, SECTIONS, ROUNDING, FREQUENCIES, COMPONENT_TYPE_TONE, methodText,
  componentPayload, useSubmit, PRORATION, LIFECYCLE, ATTENDANCE_BASES,} from './payrollKit';

/**
 * HRMS ▸ Payroll ▸ the salary component master (FRD §24).
 *
 * A component says HOW a line of pay behaves — fixed, a percentage of another line, or typed
 * in each month; prorated by payable days or not; rounded; capped; which payslip section it
 * prints under; and in what order it is worked out (`sequence` — a percentage is computed
 * from lines already worked out, which is also what keeps formulas from going in circles).
 *
 * Nothing is deleted: a component that is no longer used is RETIRED (`active: false`), so
 * past payrolls that paid it still read correctly. The server refuses a type change on a
 * component already paid, and a percentage chain that would depend on itself.
 */

/**
 * FRD §25 / §29 — every name a formula may use, grouped by where its value comes from.
 *
 * Grouped rather than one flat list because the groups answer different questions: "what
 * is this person's situation this month" (attendance), "who are they" (employee), "what
 * has been worked out already" (components). A flat list of thirty names answers none.
 *
 * Clicking appends the name, because the names are the part people get wrong — an unknown
 * one is refused on save, and guessing is how that happens.
 */
const VariablePicker = ({ bases, vars, onPick }) => {
  const groups = [
    ['Earlier components', (bases || []).map((b) => b.code)],
    ['Structure', vars?.built_in?.structure || []],
    ['Attendance', vars?.built_in?.attendance || []],
    ['Employee', vars?.built_in?.employee || []],
    ['Company constants', (vars?.variables || []).map((v) => v.name)],
  ].filter(([, names]) => names.length);

  return (
    <div className="mt-2 space-y-1.5">
      {groups.map(([label, names]) => (
        <div key={label} className="flex flex-wrap items-baseline gap-1.5">
          <span className="text-[11px] text-[var(--text-muted)] sm:min-w-[9rem]">{label}</span>
          {names.map((n) => (
            <button key={n} type="button" onClick={() => onPick(n)}
              className="px-1.5 py-0.5 rounded border border-[var(--border)] text-[11px] font-mono text-[var(--text-main)]">
              {n}
            </button>
          ))}
        </div>
      ))}
      <p className="text-[11.5px] text-[var(--text-muted)] pt-0.5">
        Plus + − × ÷, comparisons, AND / OR, and IF(condition, then, else), MIN, MAX,
        ROUND, FLOOR, CEIL, ABS. Nothing else runs — an unknown name is refused on save.
      </p>
    </div>
  );
};

export const ComponentList = ({ components, canManage, onEdit, onToggle, busyCode }) => {
  const sorted = [...components].sort((a, b) => (a.sequence ?? 100) - (b.sequence ?? 100)
    || a.code.localeCompare(b.code));
  const status = (c) => (
    <Chip tone={c.active === false ? 'neutral' : 'good'}>{c.active === false ? 'Retired' : 'Active'}</Chip>
  );
  const actions = (c) => canManage && (
    <div className="flex gap-3">
      <button type="button" onClick={() => onEdit(c)}
        className="text-[11.5px] font-bold text-[var(--accent-indigo)] hover:underline">Edit</button>
      <button type="button" disabled={busyCode === c.code} onClick={() => onToggle(c)}
        className="text-[11.5px] font-bold text-[var(--text-muted)] hover:text-[var(--text-main)] disabled:opacity-50">
        {c.active === false ? 'Activate' : 'Retire'}
      </button>
    </div>
  );
  return (
    <RecordList rows={sorted} keyOf={(c) => c.code}
      columns={[
        { key: 'seq', label: '#', render: (c) => <span className="text-[var(--text-muted)]">{c.sequence ?? 100}</span> },
        { key: 'name', label: 'Component', render: (c) => (
          <>
            <span className={`font-semibold ${c.active === false ? 'text-[var(--text-muted)]' : 'text-[var(--text-main)]'}`}>{c.name}</span>
            <span className="block text-[11px] text-[var(--text-muted)]">
              {c.code}{c.statutory ? ' · statutory' : ''}{c.frequency ? ` · ${c.frequency}` : ''}
            </span>
          </>
        ) },
        { key: 'type', label: 'Type', render: (c) => <Chip tone={COMPONENT_TYPE_TONE[c.component_type]}>{c.component_type}</Chip> },
        { key: 'method', label: 'Worked out', render: (c) => (
          <>
            <span className="text-[var(--text-main)]">{methodText(c)}</span>
            <span className="block text-[11px] text-[var(--text-muted)]">
              {c.proration === 'Payable Days' ? 'Prorated by payable days' : 'Not prorated'}
            </span>
          </>
        ) },
        { key: 'section', label: 'Payslip section', render: (c) => <span>{c.payslip_section || '—'}</span> },
        { key: 'status', label: 'Status', align: 'right', render: (c) => (
          <div className="flex flex-col items-end gap-1.5">{status(c)}{actions(c)}</div>
        ) },
      ]}
      renderCard={(c) => (
        <div className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[13px] font-bold text-[var(--text-main)]">{c.name}</p>
              <p className="text-[11.5px] text-[var(--text-muted)]">{c.code}{c.statutory ? ' · statutory' : ''}</p>
            </div>
            {status(c)}
          </div>
          <Facts items={[
            { label: 'Type', value: c.component_type },
            { label: 'Worked out', value: methodText(c) },
            { label: 'Section', value: c.payslip_section },
            { label: 'Order', value: c.sequence ?? 100 },
          ]} />
          {actions(c)}
        </div>
      )} />
  );
};

export const ComponentEditorModal = ({
  component, components, scope, onClose, onDone, showSuccess, showError,
}) => {
  const editing = !!component;
  const [vars, setVars] = useState(null);
  const [form, setForm] = useState(() => ({
    code: component?.code || '',
    name: component?.name || '',
    component_type: component?.component_type || 'Earning',
    statutory: !!component?.statutory,
    active: component ? component.active !== false : true,
    calculation_method: component?.calculation_method || 'Fixed',
    calculation_base: component?.calculation_base || '',
    percentage: component?.percentage ?? '',
    proration: component?.proration || '',
    lifecycle: component?.lifecycle || '',
    effective_from: component?.effective_from || '',
    effective_to: component?.effective_to || '',
    attendance_basis: component?.attendance_basis || 'payable_days',
    rate: component?.rate ?? '',
    applicability: Object.fromEntries(
      Object.entries(component?.applicability || {}).map(([k, v]) => [k, (v || []).join(', ')])),
    rounding: component?.rounding || 'None',
    min_amount: component?.min_amount ?? '',
    max_amount: component?.max_amount ?? '',
    sequence: component?.sequence ?? 100,
    payslip_section: component?.payslip_section || '',
    frequency: component?.frequency || 'Monthly',
    accounting_code: component?.accounting_code || '',
    description: component?.description || '',
    formula: component?.formula || '',
    // The editor works on {upto, kind, value}; payrollKit turns it into {upto, amount|percent}.
    slabs: (component?.slabs || []).map((s) => ({
      upto: s.upto ?? '', kind: s.percent != null ? 'percent' : 'amount',
      value: s.percent ?? s.amount ?? '',
    })),
    change_reason: '',
  }));
  const [sim, setSim] = useState(null);
  const [simBusy, setSimBusy] = useState(false);
  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [key]: value }));
  };
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const isPct = form.calculation_method === 'Percentage';
  const isFormula = form.calculation_method === 'Formula';
  const isSlab = form.calculation_method === 'Slab';
  const setSlab = (i, key, value) => setForm((f) => ({
    ...f, slabs: f.slabs.map((s, j) => (j === i ? { ...s, [key]: value } : s)),
  }));
  const code = form.code.trim().toUpperCase();
  const bases = components.filter((c) => c.code !== code);

  useEffect(() => {
    let alive = true;
    listCalculationVariables(scope)
      .then(({ data }) => { if (alive) setVars(data); })
      .catch(() => { /* the picker is help, not a gate — the textarea still works */ });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = () => {
    if (!code || !form.name.trim()) { showError('Code and name are required.'); return; }
    if (isPct && (!(Number(form.percentage) > 0) || !form.calculation_base)) {
      showError('A percentage component needs a percentage above 0 and what it is a percentage of.');
      return;
    }
    if (isFormula && !form.formula.trim()) { showError('Write the formula.'); return; }
    if (isSlab && (!form.slabs.length || !form.calculation_base)) {
      showError('A slab component needs at least one slab and what it is applied to.');
      return;
    }
    if (form.min_amount !== '' && form.max_amount !== '' && Number(form.min_amount) > Number(form.max_amount)) {
      showError('The minimum is above the maximum.');
      return;
    }
    // The route overrides `code` from the URL anyway, but SalaryComponentIn still requires
    // it in the body — the same shape LeaveTypeConfigIn/saveLeaveType already use.
    run(() => saveSalaryComponent(code, componentPayload({ ...form, code, name: form.name.trim() }), scope),
      editing ? `${code} updated.` : `${code} added.`);
  };

  // FRD §25 Simulation: old result vs the proposed rule, before anything is saved.
  const simulate = async () => {
    if (!code) { showError('Give the component a code first.'); return; }
    setSimBusy(true);
    try {
      const { data } = await simulateSalaryComponent(
        code, componentPayload({ ...form, code, name: form.name.trim() || code }), scope);
      setSim(data);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not simulate this change.');
    } finally {
      setSimBusy(false);
    }
  };

  return (
    <Modal title={editing ? `Edit ${component.name}` : 'Add Salary Component'} labelledBy="component-title" wide
      subtitle={editing
        ? `Version ${component.version ?? 1}${component.history?.length ? ` · ${component.history.length} change(s) on record` : ''}. Changes apply to payrolls calculated from now on.`
        : 'A line a salary can be made of, and how it is worked out.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          {editing && (
            <Btn onClick={simulate} disabled={busy || simBusy}>{simBusy ? 'Simulating…' : 'Simulate change'}</Btn>
          )}
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className={LABEL} htmlFor="comp-code">Code *</label>
          <input id="comp-code" value={form.code} className={FIELD} placeholder="e.g. BASIC"
            disabled={editing} onChange={set('code')} />
        </div>
        <div className="sm:col-span-2">
          <label className={LABEL} htmlFor="comp-name">Name *</label>
          <input id="comp-name" value={form.name} className={FIELD} onChange={set('name')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-type">Type</label>
          <select id="comp-type" value={form.component_type} className={FIELD} onChange={set('component_type')}>
            {COMPONENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-section">Payslip section</label>
          <select id="comp-section" value={form.payslip_section} className={FIELD} onChange={set('payslip_section')}>
            <option value="">Default for the type</option>
            {SECTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-seq">Order (sequence)</label>
          <input id="comp-seq" type="number" step="1" value={form.sequence} className={FIELD} onChange={set('sequence')} />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className={LABEL} htmlFor="comp-method">Worked out as</label>
          <select id="comp-method" value={form.calculation_method} className={FIELD} onChange={set('calculation_method')}>
            {METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        {isPct && (
          <>
            <div>
              <label className={LABEL} htmlFor="comp-pct">Percentage *</label>
              <input id="comp-pct" type="number" min="0" step="0.01" inputMode="decimal" value={form.percentage}
                className={FIELD} onChange={set('percentage')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="comp-base">Of *</label>
              <select id="comp-base" value={form.calculation_base} className={FIELD} onChange={set('calculation_base')}>
                <option value="">Choose…</option>
                <option value="GROSS">Gross (earnings before it)</option>
                <option value="CTC">CTC (annual ÷ 12)</option>
                {bases.map((c) => <option key={c.code} value={c.code}>{c.name} ({c.code})</option>)}
              </select>
            </div>
          </>
        )}
      </div>
      {isPct && (
        <p className="text-[11.5px] text-[var(--text-muted)] -mt-1.5">
          The base must come earlier in the order, so it is worked out first.
        </p>
      )}
      {isFormula && (
        <div>
          <label className={LABEL} htmlFor="comp-formula">Formula *</label>
          <textarea id="comp-formula" rows={2} value={form.formula} className={`${TEXTAREA} font-mono`}
            placeholder="IF(PAYABLE_DAYS < 15, 0, 1500)" onChange={set('formula')} />
          <VariablePicker bases={bases} vars={vars}
            onPick={(name) => setForm((f) => ({
              ...f,
              formula: f.formula && !/[\s(]$/.test(f.formula)
                ? `${f.formula} ${name}` : `${f.formula}${name}`,
            }))} />
        </div>
      )}
      {isSlab && (
        <div className="space-y-2">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className={LABEL} htmlFor="comp-slab-base">Applied to *</label>
              <select id="comp-slab-base" value={form.calculation_base} className={FIELD} onChange={set('calculation_base')}>
                <option value="">Choose…</option>
                <option value="GROSS">Gross (earnings before it)</option>
                <option value="CTC">CTC (annual)</option>
                {bases.map((c) => <option key={c.code} value={c.code}>{c.name} ({c.code})</option>)}
              </select>
            </div>
          </div>
          <p className={LABEL}>Slabs (first row whose “up to” covers the base wins; blank = no ceiling)</p>
          {form.slabs.map((s, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 items-center">
              <input type="number" min="0" aria-label={`Slab ${i + 1} up to`} placeholder="Up to (blank = above)"
                value={s.upto} className={FIELD} onChange={(e) => setSlab(i, 'upto', e.target.value)} />
              <select aria-label={`Slab ${i + 1} kind`} value={s.kind} className={FIELD}
                onChange={(e) => setSlab(i, 'kind', e.target.value)}>
                <option value="amount">Amount ₹</option>
                <option value="percent">% of base</option>
              </select>
              <input type="number" min="0" step="0.01" aria-label={`Slab ${i + 1} value`} value={s.value}
                className={FIELD} onChange={(e) => setSlab(i, 'value', e.target.value)} />
              <button type="button" className="text-[12px] text-[var(--accent-red)] px-2"
                onClick={() => setForm((f) => ({ ...f, slabs: f.slabs.filter((_, j) => j !== i) }))}>Remove</button>
            </div>
          ))}
          <Btn onClick={() => setForm((f) => ({ ...f, slabs: [...f.slabs, { upto: '', kind: 'amount', value: '' }] }))}>
            Add slab
          </Btn>
        </div>
      )}
      {sim && (
        <div className="rounded-lg border border-[var(--border)] p-3 space-y-2">
          <p className="text-[12.5px] font-bold text-[var(--text-main)]">
            Simulation — {sim.summary.employees_affected} employee(s) change; monthly net
            {' '}{sim.summary.monthly_net_difference >= 0 ? '+' : ''}{sim.summary.monthly_net_difference.toLocaleString('en-IN')},
            {' '}employer cost {sim.summary.monthly_employer_difference >= 0 ? '+' : ''}
            {sim.summary.monthly_employer_difference.toLocaleString('en-IN')}
          </p>
          {sim.dependants?.length > 0 && (
            <p className="text-[11.5px] text-[var(--text-muted)]">Also affected (they read this one): {sim.dependants.join(', ')}</p>
          )}
          <div className="max-h-60 overflow-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left text-[var(--text-muted)]">
                  <th className="py-1 pr-2">Employee</th><th className="py-1 pr-2">Lines</th>
                  <th className="py-1 pr-2 text-right">Net now</th><th className="py-1 text-right">Net after</th>
                </tr>
              </thead>
              <tbody>
                {sim.employees.map((r) => (
                  <tr key={r.employee_code} className="border-t border-[var(--border)]">
                    <td className="py-1 pr-2">{r.employee_name || r.employee_code}</td>
                    <td className="py-1 pr-2">
                      {Object.entries(r.components).map(([c, v]) => `${c} ${v.old} → ${v.new}`).join('; ') || 'no change'}
                    </td>
                    <td className="py-1 pr-2 text-right">{r.old_monthly_net.toLocaleString('en-IN')}</td>
                    <td className="py-1 text-right font-semibold">{r.new_monthly_net.toLocaleString('en-IN')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sim.errors?.length > 0 && (
            <p className="text-[11.5px] text-[var(--accent-red)]">
              {sim.errors.length} salary(ies) could not be worked out: {sim.errors[0].error}
            </p>
          )}
          <p className="text-[11px] text-[var(--text-muted)]">{sim.note}</p>
        </div>
      )}

      {/* FRD §24 Lifecycle and Applicability. Only an Active component is paid; blank
          lifecycle keeps the pre-§24 behaviour where `active` is the only switch. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <label className={LABEL} htmlFor="comp-lifecycle">Lifecycle</label>
          <select id="comp-lifecycle" value={form.lifecycle} className={FIELD}
            onChange={set('lifecycle')}>
            <option value="">Not set — uses the Active switch</option>
            {LIFECYCLE.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-eff-from">Effective from</label>
          <input id="comp-eff-from" type="date" value={form.effective_from} className={FIELD}
            onChange={set('effective_from')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-eff-to">Effective to</label>
          <input id="comp-eff-to" type="date" value={form.effective_to} className={FIELD}
            onChange={set('effective_to')} />
        </div>
        {form.lifecycle && form.lifecycle !== 'Active' && (
          <p className="text-[11.5px] text-[var(--accent-orange)] self-end pb-2">
            Only an <b>Active</b> component is paid.
          </p>
        )}
      </div>

      {form.calculation_method === 'Attendance Linked' && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="comp-att-basis">Multiply the rate by</label>
            <select id="comp-att-basis" value={form.attendance_basis} className={FIELD}
              onChange={set('attendance_basis')}>
              {ATTENDANCE_BASES.map((b) => (
                <option key={b} value={b}>{b.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL} htmlFor="comp-rate">Rate (per day)</label>
            <input id="comp-rate" type="number" min="0" step="0.01" value={form.rate}
              className={FIELD} onChange={set('rate')} />
          </div>
        </div>
      )}

      <div>
        <p className={LABEL}>Applies to — blank in every box means every employee</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-1">
          {[['locations', 'Locations'], ['grades', 'Grades'],
            ['employment_categories', 'Categories'], ['payroll_groups', 'Payroll groups']]
            .map(([key, label]) => (
              <div key={key}>
                <label className={LABEL} htmlFor={`comp-ap-${key}`}>{label}</label>
                <input id={`comp-ap-${key}`} value={form.applicability?.[key] || ''}
                  className={FIELD} placeholder="comma separated"
                  onChange={(e) => setForm((f) => ({
                    ...f, applicability: { ...f.applicability, [key]: e.target.value },
                  }))} />
              </div>
            ))}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <label className={LABEL} htmlFor="comp-proration">Proration</label>
          <select id="comp-proration" value={form.proration} className={FIELD} onChange={set('proration')}>
            {PRORATION.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-rounding">Rounding</label>
          <select id="comp-rounding" value={form.rounding} className={FIELD} onChange={set('rounding')}>
            {ROUNDING.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-min">Minimum</label>
          <input id="comp-min" type="number" min="0" inputMode="decimal" value={form.min_amount}
            className={FIELD} onChange={set('min_amount')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-max">Maximum</label>
          <input id="comp-max" type="number" min="0" inputMode="decimal" value={form.max_amount}
            className={FIELD} onChange={set('max_amount')} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="comp-frequency">Frequency</label>
          <select id="comp-frequency" value={form.frequency} className={FIELD} onChange={set('frequency')}>
            {FREQUENCIES.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-acct">Accounting code</label>
          <input id="comp-acct" value={form.accounting_code} className={FIELD} onChange={set('accounting_code')} />
        </div>
      </div>
      {editing && (
        <div>
          <label className={LABEL} htmlFor="comp-reason">Reason for this change</label>
          <input id="comp-reason" value={form.change_reason} className={FIELD} onChange={set('change_reason')}
            placeholder="Kept in the component's history" />
        </div>
      )}
      <div>
        <label className={LABEL} htmlFor="comp-desc">Description</label>
        <textarea id="comp-desc" rows={2} value={form.description} className={TEXTAREA} onChange={set('description')} />
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        <label className="flex items-center gap-2 text-[12px] text-[var(--text-main)]">
          <input type="checkbox" checked={form.statutory} onChange={set('statutory')} />
          Statutory component
        </label>
        <label className="flex items-center gap-2 text-[12px] text-[var(--text-main)]">
          <input type="checkbox" checked={form.active} onChange={set('active')} />
          Active (untick to retire it)
        </label>
      </div>
    </Modal>
  );
};
