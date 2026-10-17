import React, { useCallback, useEffect, useState } from 'react';
import { CAP } from '../access';
import { HrmsLoading } from '../common/HrmsStates';
import {
  getPayslipTemplate, savePayslipTemplate, listPayslipTemplateVersions,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA } from '../internal/internalKit';
import { Btn, Chip } from '../internal/internalKit.jsx';
import { errText, when } from './payrollKit';

/**
 * HRMS ▸ Payroll ▸ Payslip Template tab (SM-HR-064, FRD §14 Template).
 *
 * The layout options a company signs off on. Every save is a new VERSION; a payroll keeps
 * the version it was LOCKED with, so editing the template never changes a payslip already
 * issued — which is why the earlier versions are listed underneath.
 */

const TOGGLES = [
  ['show_identifiers', 'Show PAN, UAN, PF / ESI numbers, location and grade'],
  ['show_bank', 'Show the bank and (masked) account number'],
  ['show_lop_days', 'Show loss-of-pay days'],
  ['show_employer_contributions', 'Show employer contributions (PF / ESI paid by the company)'],
  ['hide_zero_lines', 'Hide lines that are zero'],
  ['show_net_in_words', 'Show net pay in words'],
];

const EMPTY = {
  company_name: '', company_address: '', header_note: '', footer_note: '',
  show_identifiers: true, show_bank: true, show_lop_days: true,
  show_employer_contributions: false, hide_zero_lines: true, show_net_in_words: true,
};

const PayslipTemplateTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [form, setForm] = useState(EMPTY);
  const [version, setVersion] = useState(0);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const canWrite = can(CAP.PAYROLL_PROCESS);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    try {
      const [{ data }, vers] = await Promise.all([
        getPayslipTemplate(scope),
        listPayslipTemplateVersions(scope).catch(() => ({ data: [] })),
      ]);
      const next = { ...EMPTY };
      Object.keys(EMPTY).forEach((k) => {
        if (data?.[k] != null) next[k] = data[k];
      });
      setForm(next);
      setVersion(data?.version || 0);
      setVersions(vers.data || []);
    } catch {
      // A never-configured template is a 200 with defaults, not an error — nothing to show here.
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [key]: value }));
  };

  const save = async () => {
    setSaving(true);
    try {
      await savePayslipTemplate({
        company_name: form.company_name.trim() || undefined,
        company_address: form.company_address.trim() || undefined,
        header_note: form.header_note.trim() || undefined,
        footer_note: form.footer_note.trim() || undefined,
        ...Object.fromEntries(TOGGLES.map(([k]) => [k, !!form[k]])),
      }, scope);
      showSuccess('Payslip template saved as a new version.');
      load();
    } catch (err) {
      showError(errText(err, 'Could not save the template.'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <HrmsLoading label="Loading the payslip template…" />;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,320px)]">
      <div className="space-y-4 max-w-xl">
        <p className="text-[12.5px] text-[var(--text-muted)]">
          What every payslip shows. Saving makes a new version (now on
          {' '}<span className="font-bold text-[var(--text-main)]">v{version}</span>). A payroll that is
          already locked keeps the version it was locked with.
        </p>
        <div>
          <label className={LABEL} htmlFor="pt-name">Company name on payslip</label>
          <input id="pt-name" value={form.company_name} className={FIELD} disabled={!canWrite}
            onChange={set('company_name')} placeholder="Sparsh Magic LLP" />
        </div>
        <div>
          <label className={LABEL} htmlFor="pt-address">Company address</label>
          <textarea id="pt-address" rows={2} value={form.company_address} className={TEXTAREA} disabled={!canWrite}
            onChange={set('company_address')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="pt-header">Header note</label>
          <textarea id="pt-header" rows={2} value={form.header_note} className={TEXTAREA} disabled={!canWrite}
            onChange={set('header_note')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="pt-footer">Footer note</label>
          <textarea id="pt-footer" rows={2} value={form.footer_note} className={TEXTAREA} disabled={!canWrite}
            onChange={set('footer_note')}
            placeholder="This is a system-generated payslip and does not require a signature." />
        </div>
        <fieldset className="space-y-2">
          <legend className={LABEL}>Show on the payslip</legend>
          {TOGGLES.map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
              <input type="checkbox" checked={!!form[key]} disabled={!canWrite} onChange={set(key)} />
              {label}
            </label>
          ))}
        </fieldset>
        {canWrite && (
          <Btn tone="primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save new version'}</Btn>
        )}
      </div>

      <div className="space-y-2">
        <p className="text-[12.5px] font-bold text-[var(--text-main)]">Earlier versions</p>
        <p className="text-[11.5px] text-[var(--text-muted)]">
          A locked payroll keeps the version it was locked with, so its payslips never change.
        </p>
        {!versions.length && (
          <p className="text-[12px] text-[var(--text-muted)]">No versions saved yet.</p>
        )}
        {versions.map((v) => (
          <div key={v.version} className="rounded-lg border border-[var(--border)] px-3 py-2.5 space-y-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12.5px] font-bold text-[var(--text-main)]">v{v.version}</span>
              {v.version === version && <Chip tone="good">Current</Chip>}
            </div>
            <p className="text-[11.5px] text-[var(--text-muted)]">{when(v.updated_at || v.created_at)}</p>
            <p className="text-[12px] text-[var(--text-main)] truncate" title={v.company_name || ''}>
              {v.company_name || 'Default company name'}
            </p>
            {(v.header_note || v.footer_note) && (
              <p className="text-[11.5px] text-[var(--text-muted)] line-clamp-2">
                {[v.header_note, v.footer_note].filter(Boolean).join(' · ')}
              </p>
            )}
            <p className="text-[11px] text-[var(--text-muted)]">
              {TOGGLES.filter(([k]) => v[k]).length} of {TOGGLES.length} options on
            </p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default PayslipTemplateTab;
