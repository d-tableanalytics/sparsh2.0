import React from 'react';
import { Lock } from 'lucide-react';
import { FIELD, LABEL, TEXTAREA, day, attLeaveToneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal } from '../internal/internalKit.jsx';
import { SOURCE_LABEL, hoursLabel, payableLabel, shiftLabel, stamp } from './attendanceRules';

/**
 * HRMS ▸ Attendance — one day in full, and the configurable attendance fields.
 *
 * The daily table can only carry the numbers people scan for; this is where "why does this
 * day say Half Day" gets answered: the rule that judged it, the raw punches next to the
 * corrected ones (FRD §18 — raw values are never overwritten), the regularisation that
 * changed it, and every later modification.
 */

const fieldValue = (def, raw) => {
  if (raw == null || raw === '') return null;
  if (def?.data_type === 'boolean') return raw ? 'Yes' : 'No';
  const labelOf = (v) => (def?.options || []).find((o) => o.value === v)?.label || v;
  if (Array.isArray(raw)) return raw.map(labelOf).join(', ');
  if (def?.data_type === 'single_select') return labelOf(raw);
  if (def?.data_type === 'date') return day(raw);
  return String(raw);
};

/**
 * Inputs for the company's ACTIVE attendance fields (FRD §21), in display order. `value` is
 * the custom_fields object being built; mandatory is marked but enforced by the server, which
 * also knows about defaults and fields not yet in force.
 */
export const CustomFieldInputs = ({ defs, value, onChange }) => {
  if (!defs.length) return null;
  const set = (code, v) => onChange({ ...value, [code]: v });
  return (
    <div className="space-y-3 rounded-lg border border-[var(--border)] p-3">
      <p className={LABEL}>Additional details</p>
      {defs.map((d) => {
        const id = `att-cf-${d.code}`;
        const label = (
          <label className={LABEL} htmlFor={id}>{d.label}{d.mandatory ? ' *' : ''}</label>
        );
        const options = (d.options || []).filter((o) => o.active !== false);
        const v = value[d.code];
        let input;
        if (d.data_type === 'long_text') {
          input = <textarea id={id} rows={2} className={TEXTAREA} value={v || ''} onChange={(e) => set(d.code, e.target.value)} />;
        } else if (['number', 'decimal', 'currency'].includes(d.data_type)) {
          input = (
            <input id={id} type="number" step={d.data_type === 'number' ? '1' : '0.01'} className={FIELD}
              value={v ?? ''} onChange={(e) => set(d.code, e.target.value)} />
          );
        } else if (d.data_type === 'date') {
          input = <input id={id} type="date" className={FIELD} value={v || ''} onChange={(e) => set(d.code, e.target.value)} />;
        } else if (d.data_type === 'boolean') {
          return (
            <div key={d.code}>
              <label className="inline-flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
                <input id={id} type="checkbox" checked={!!v} onChange={(e) => set(d.code, e.target.checked)} />
                {d.label}{d.mandatory ? ' *' : ''}
              </label>
              {d.help_text && <p className="mt-1 text-[11px] text-[var(--text-muted)]">{d.help_text}</p>}
            </div>
          );
        } else if (d.data_type === 'single_select') {
          input = (
            <select id={id} className={FIELD} value={v || ''} onChange={(e) => set(d.code, e.target.value)}>
              <option value="">— select —</option>
              {options.map((o) => <option key={o.value} value={o.value}>{o.label || o.value}</option>)}
            </select>
          );
        } else if (d.data_type === 'multi_select') {
          const picked = Array.isArray(v) ? v : [];
          input = (
            <div className="flex flex-wrap gap-x-4 gap-y-1.5" id={id}>
              {options.map((o) => (
                <label key={o.value} className="inline-flex items-center gap-1.5 text-[12.5px] text-[var(--text-main)]">
                  <input type="checkbox" checked={picked.includes(o.value)}
                    onChange={() => set(d.code, picked.includes(o.value)
                      ? picked.filter((x) => x !== o.value) : [...picked, o.value])} />
                  {o.label || o.value}
                </label>
              ))}
            </div>
          );
        } else {
          input = <input id={id} className={FIELD} value={v || ''} onChange={(e) => set(d.code, e.target.value)} />;
        }
        return (
          <div key={d.code}>
            {label}
            {input}
            {d.help_text && <p className="mt-1 text-[11px] text-[var(--text-muted)]">{d.help_text}</p>}
          </div>
        );
      })}
    </div>
  );
};

const Section = ({ title, children }) => (
  <div className="space-y-2">
    <p className={LABEL}>{title}</p>
    {children}
  </div>
);

const HISTORY_KEYS = [['actual_in', 'In'], ['actual_out', 'Out'], ['status', 'Status'], ['source', 'Source']];

/** The full record for one employee-day. */
export const DayDetailModal = ({ row: r, fieldDefs, onClose }) => {
  const defByCode = Object.fromEntries((fieldDefs || []).map((d) => [d.code, d]));
  const custom = Object.entries(r.custom_fields || {});
  const history = [...(r.modification_history || [])].reverse();
  const corrected = r.regularization_flag || r.corrected_in || r.corrected_out;
  const cell = 'py-1.5 px-2 text-left';

  return (
    <Modal wide title={`${r.employee_name || r.employee_code} · ${day(r.work_date)}`} labelledBy="att-day-title"
      subtitle={`Judged by: ${shiftLabel(r)}${r.rule_version ? ` · rules from ${day(r.rule_version)}` : ''}`}
      onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        {r.missing_out_punch && <Chip tone="warn">Missing out-punch</Chip>}
        {r.locked && (
          <Chip tone="neutral" title={r.locked_at ? `Locked ${stamp(r.locked_at)}` : undefined}>
            <Lock size={11} /> Locked
          </Chip>
        )}
      </div>
      {/* FRD §6 Identity and Date/Schedule. The title carries the name and the date; a
          record that is read to settle a dispute also has to say WHICH Sharma, in which
          department and at which location, without the reader going to the directory. */}
      <Facts items={[
        { label: 'Employee ID', value: r.employee_code },
        { label: 'Department', value: r.department },
        { label: 'Location', value: r.work_location },
        { label: 'Day', value: r.day },
        { label: 'Scheduled', value: r.scheduled_in ? `${r.scheduled_in} – ${r.scheduled_out || '—'}` : null },
        { label: 'Actual', value: `${r.actual_in || '—'} – ${r.actual_out || '—'}` },
        { label: 'Worked', value: hoursLabel(r.worked_minutes) },
        { label: 'Payable hours', value: r.payable_hours != null ? `${r.payable_hours} h` : null },
        { label: 'Payable day', value: payableLabel(r) },
        { label: 'Late', value: r.late_minutes ? `${r.late_minutes} min` : '—' },
        { label: 'Early going', value: r.early_minutes ? `${r.early_minutes} min` : '—' },
        { label: 'Grace used', value: r.grace_applied_minutes ? `${r.grace_applied_minutes} min` : null },
        { label: 'Source', value: SOURCE_LABEL[r.source] || r.source },
        { label: 'Reference', value: r.source_reference },
        { label: 'Flexible timing', value: r.flexi_no },
        { label: 'Notes', value: r.notes },
      ]} />

      <Section title="Original vs corrected">
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)]">
                <th scope="col" className={cell}>&nbsp;</th>
                <th scope="col" className={cell}>Original (raw)</th>
                <th scope="col" className={cell}>{corrected ? 'Corrected' : 'Current'}</th>
              </tr>
            </thead>
            <tbody className="text-[var(--text-main)]">
              <tr className="border-b border-[var(--border)]">
                <th scope="row" className={`${cell} text-[var(--text-muted)] font-semibold`}>In</th>
                <td className={cell}>{r.original_in || '—'}</td>
                <td className={cell}>{r.corrected_in || r.actual_in || '—'}</td>
              </tr>
              <tr className="border-b border-[var(--border)]">
                <th scope="row" className={`${cell} text-[var(--text-muted)] font-semibold`}>Out</th>
                <td className={cell}>{r.original_out || '—'}</td>
                <td className={cell}>{r.corrected_out || r.actual_out || '—'}</td>
              </tr>
              <tr>
                <th scope="row" className={`${cell} text-[var(--text-muted)] font-semibold`}>Source</th>
                <td className={cell}>{SOURCE_LABEL[r.original_source] || r.original_source || '—'}</td>
                <td className={cell}>{SOURCE_LABEL[r.source] || r.source || '—'}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Section>

      {(r.regularization_flag || r.regularized_from) && (
        <Section title="Regularisation">
          {/* §6 Correction (flag, proposed in/out, reason, evidence) and §6 Approval
              (manager, HR, comments). The proposed times are the corrected ones shown
              above — once applied they ARE the record, so repeating them here would
              invite the reader to treat one of the two as the real value. */}
          <Facts items={[
            { label: 'Request', value: r.regularized_from },
            { label: 'Type', value: r.regularisation_request_type },
            { label: 'Reason given', value: r.regularisation_reason },
            { label: 'Evidence', value: r.regularisation_evidence },
            { label: 'Manager', value: r.manager_status },
            { label: 'HR', value: r.hr_status },
            { label: 'Comments', value: r.approver_comments },
          ]} />
          {r.regularisation_has_evidence_file && (
            <p className="text-[11.5px] text-[var(--text-muted)]">
              A file was attached to {r.regularized_from}. Open it from the Regularisations
              tab — it stays on the request rather than being copied onto the day.
            </p>
          )}
        </Section>
      )}

      {custom.length > 0 && (
        <Section title="Additional details">
          <Facts items={custom.map(([code, raw]) => ({
            label: defByCode[code]?.label || code, value: fieldValue(defByCode[code], raw),
          }))} />
        </Section>
      )}

      {/* §6 Lock: "Locked Flag; Locked By; Locked Date". The flag and the date were shown
          and the WHO was guarded on but never drawn — so the one question a locked day
          gets asked ("who closed this?") was the one it could not answer. */}
      {r.locked && (r.locked_at || r.locked_by_name) && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Locked {stamp(r.locked_at)}
          {r.locked_by_name ? ` by ${r.locked_by_name}` : ''} — changes now need the month
          reopened on Monthly Closure.
        </p>
      )}

      <Section title="Modification history">
        {history.length ? (
          <ul className="space-y-1.5">
            {history.map((h, i) => (
              <li key={`${h.at}-${i}`}
                className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-[12px]">
                <p className="font-semibold text-[var(--text-main)]">
                  {stamp(h.at)} · {h.via === 'mark' ? 'Re-marked' : h.via}
                </p>
                <p className="text-[var(--text-muted)]">
                  {HISTORY_KEYS
                    .filter(([k]) => (h.old?.[k] ?? null) !== (h.new?.[k] ?? null))
                    .map(([k, label]) => `${label}: ${h.old?.[k] || '—'} → ${h.new?.[k] || '—'}`)
                    .join(' · ') || 'No change to punches or status'}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[12px] text-[var(--text-muted)]">Not changed since it was first recorded.</p>
        )}
      </Section>
    </Modal>
  );
};
