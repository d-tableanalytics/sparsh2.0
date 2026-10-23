import React, { useCallback, useEffect, useState } from 'react';
import { Landmark, Eye, Plus, Trash2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { useNotification } from '../../../context/NotificationContext';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  listBankFileFormats, saveBankFileFormat, previewBankFileFormat,
} from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';
import { Btn, Chip, Modal } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Payroll ▸ Bank File Format designer (FRD §13, §19).
 *
 * §19 leaves "bank-specific layout and mandatory fields" open. This is where the answer
 * gets entered when it arrives, instead of becoming a code change.
 *
 * The PREVIEW is the point of the screen. A column list is hard to check against a bank's
 * specification sheet; two rendered rows are easy, and they go through exactly the same
 * renderer the real download uses — so what you see here is what the bank gets.
 */

const SOURCES = [
  ['serial', 'Row number'], ['batch_no', 'Batch number'], ['period', 'Payroll period'],
  ['employee_code', 'Employee ID'], ['employee_name', 'Employee name'],
  ['account_holder', 'Beneficiary name'], ['bank_account', 'Account number'],
  ['bank_ifsc', 'IFSC'], ['bank_name', 'Bank'], ['bank_branch', 'Branch'],
  ['bank_account_type', 'Account type'], ['amount', 'Net pay'],
  ['payment_mode', 'Payment mode'], ['narration', 'Narration'],
  ['generated_date', 'Generated date'], ['constant', 'Fixed value'],
];
const AMOUNTS = [['2dp', '1234.50'], ['0dp', '1235'], ['paise', '123450'], ['comma', '1,234.50']];
const DATES = [['iso', '2026-03-31'], ['dmy', '31/03/2026'], ['dmy_dash', '31-03-2026'],
  ['mdy', '03/31/2026'], ['compact', '20260331']];

const blankFormat = () => ({
  name: '', bank: '', delimiter: ',', fixed_width: false, include_header: true,
  include_totals_row: false, amount_format: '2dp', date_format: 'iso',
  narration_template: 'Salary {period}', header_lines: [], trailer_lines: [],
  columns: [{ source: 'employee_code', label: 'Employee ID', align: 'left' }],
});

const FormatEditor = ({ initial, scope, onClose, onDone, showSuccess, showError }) => {
  const [form, setForm] = useState(() => ({ ...blankFormat(), ...(initial || {}) }));
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (key) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [key]: v }));
  };

  const setColumn = (i, patch) => setForm((f) => ({
    ...f, columns: f.columns.map((c, n) => (n === i ? { ...c, ...patch } : c)),
  }));
  const addColumn = () => setForm((f) => ({
    ...f, columns: [...f.columns, { source: 'amount', label: 'Amount', align: 'left' }],
  }));
  const removeColumn = (i) => setForm((f) => ({
    ...f, columns: f.columns.filter((_, n) => n !== i),
  }));

  const runPreview = async () => {
    setBusy(true);
    try {
      const { data } = await previewBankFileFormat(form, scope);
      setPreview(data?.preview || '');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not render a preview.');
    } finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true);
    try {
      await saveBankFileFormat(form, scope);
      showSuccess('Bank file format saved.');
      await onDone();
      onClose();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the format.');
    } finally { setBusy(false); }
  };

  const lines = (key) => (form[key] || []).join('\n');
  const setLines = (key) => (e) => setForm((f) => ({
    ...f, [key]: e.target.value.split('\n').filter((l) => l.length),
  }));

  return (
    <Modal title={initial?.name ? `Format · ${initial.name}` : 'New bank file format'}
      labelledBy="bank-format-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn onClick={runPreview} disabled={busy}><Eye size={14} /> Preview</Btn>
          <Btn tone="primary" onClick={save} disabled={busy || !form.name.trim()}>
            {busy ? 'Saving…' : 'Save'}
          </Btn>
        </>
      )}>
      <div className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label className={LABEL} htmlFor="bf-name">Name *</label>
            <input id="bf-name" value={form.name} className={FIELD} placeholder="HDFC_NEFT"
              disabled={!!initial?.name} onChange={set('name')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="bf-bank">Bank</label>
            <input id="bf-bank" value={form.bank || ''} className={FIELD} onChange={set('bank')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="bf-delim">Delimiter</label>
            <input id="bf-delim" value={form.delimiter} className={FIELD}
              disabled={form.fixed_width} onChange={set('delimiter')} />
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div>
            <label className={LABEL} htmlFor="bf-amt">Amounts look like</label>
            <select id="bf-amt" value={form.amount_format} className={FIELD}
              onChange={set('amount_format')}>
              {AMOUNTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label className={LABEL} htmlFor="bf-date">Dates look like</label>
            <select id="bf-date" value={form.date_format} className={FIELD}
              onChange={set('date_format')}>
              {DATES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-2 self-end pb-2">
            <input type="checkbox" checked={!!form.fixed_width} onChange={set('fixed_width')} />
            <span className="text-[12px] text-[var(--text-main)]">Fixed width</span>
          </label>
          <label className="flex items-center gap-2 self-end pb-2">
            <input type="checkbox" checked={!!form.include_header} onChange={set('include_header')} />
            <span className="text-[12px] text-[var(--text-main)]">Column headers</span>
          </label>
        </div>

        <div>
          <label className={LABEL} htmlFor="bf-narr">Narration</label>
          <input id="bf-narr" value={form.narration_template} className={FIELD}
            onChange={set('narration_template')} />
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
            {'Use {period}, {employee_code}, {employee_name}, {batch_no}.'}
          </p>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <p className={LABEL}>Columns, in order</p>
            <Btn tone="ghost" onClick={addColumn}><Plus size={14} /> Add</Btn>
          </div>
          <div className="space-y-1.5 mt-1">
            {form.columns.map((c, i) => (
              // Index as key is correct here: the list IS ordered by position, and a
              // column has no identity apart from where it sits in the file.
              <div key={`col-${i}`} className="grid grid-cols-12 gap-1.5 items-center">
                <select value={c.source} className={`${FIELD} col-span-4`}
                  onChange={(e) => setColumn(i, { source: e.target.value })}>
                  {SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <input value={c.label || ''} className={`${FIELD} col-span-3`} placeholder="Header"
                  onChange={(e) => setColumn(i, { label: e.target.value })} />
                {c.source === 'constant' ? (
                  <input value={c.value || ''} className={`${FIELD} col-span-2`} placeholder="Value"
                    onChange={(e) => setColumn(i, { value: e.target.value })} />
                ) : (
                  <input type="number" min="1" value={c.width || ''} className={`${FIELD} col-span-2`}
                    placeholder={form.fixed_width ? 'width *' : 'width'}
                    onChange={(e) => setColumn(i, {
                      width: e.target.value === '' ? undefined : Number(e.target.value),
                    })} />
                )}
                <select value={c.align || 'left'} className={`${FIELD} col-span-2`}
                  onChange={(e) => setColumn(i, { align: e.target.value })}>
                  <option value="left">left</option>
                  <option value="right">right</option>
                </select>
                <button type="button" onClick={() => removeColumn(i)}
                  className="col-span-1 text-[var(--text-muted)]" aria-label={`Remove column ${i + 1}`}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="bf-head">Header records (one per line)</label>
            <textarea id="bf-head" rows={2} value={lines('header_lines')}
              className={`${FIELD} font-mono`} onChange={setLines('header_lines')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="bf-trail">Trailer records (one per line)</label>
            <textarea id="bf-trail" rows={2} value={lines('trailer_lines')}
              className={`${FIELD} font-mono`} onChange={setLines('trailer_lines')} />
          </div>
        </div>

        <label className="flex items-center gap-2">
          <input type="checkbox" checked={!!form.include_totals_row}
            onChange={set('include_totals_row')} />
          <span className="text-[12px] text-[var(--text-main)]">
            Totals row at the end — some banks reject it
          </span>
        </label>

        {preview !== null && (
          <div>
            <p className={LABEL}>Preview — exactly what the bank receives</p>
            <pre className="mt-1 p-2.5 rounded-lg bg-[var(--bg-subtle)] text-[11px] font-mono text-[var(--text-main)] overflow-x-auto whitespace-pre">
              {preview}
            </pre>
          </div>
        )}
      </div>
    </Modal>
  );
};

const BankFileFormat = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [rows, setRows] = useState([]);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const canEdit = can(CAP.CONFIG_DRAFT);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await listBankFileFormats(scope);
      setRows(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the bank file formats.');
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-[13px] font-bold text-[var(--text-main)] flex items-center gap-1.5">
            <Landmark size={15} /> Bank file formats
          </h2>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            The layout the payment file is written in (FRD §13, §19).
          </p>
        </div>
        {canEdit && <Btn tone="primary" onClick={() => setEditing({})}>New format</Btn>}
      </div>

      {loading && <HrmsLoading label="Loading formats…" />}
      {error && <HrmsError message={error} />}

      {!loading && !error && (
        <div className="space-y-1.5">
          {rows.map((f) => (
            <div key={f.name}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2">
              <span className="text-[12.5px] font-bold text-[var(--text-main)] font-mono">
                {f.name}
              </span>
              {f.built_in && <Chip tone="neutral">built in</Chip>}
              {f.bank && <Chip tone="accent">{f.bank}</Chip>}
              {f.fixed_width && <Chip tone="warn">fixed width</Chip>}
              <span className="text-[11.5px] text-[var(--text-muted)]">
                {(f.columns || []).length} column(s)
                {f.version ? ` · v${f.version}` : ''}
              </span>
              <span className="ml-auto">
                <Btn tone="ghost" onClick={() => setEditing(f)}>
                  {canEdit && !f.built_in ? 'Edit' : 'View / copy'}
                </Btn>
              </span>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <FormatEditor
          initial={editing.built_in ? { ...editing, name: '', built_in: undefined } : editing}
          scope={scope} onClose={() => setEditing(null)} onDone={load}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

export default BankFileFormat;
