import React, { useCallback, useEffect, useState } from 'react';
import {
  Building2, Briefcase, MapPin, Plus, Loader2, AlertTriangle, Power, Check, X,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { getOrgMasters, createOrgMaster, updateOrgMaster } from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { Field } from '../../components/hrms/hrmsUi';
import { inputCls } from '../../components/hrms/hrmsStyles';

// HRMS ▸ Organization structure — the master lists behind the employee form's comboboxes.
//
// Three near-identical shapes (departments / designations / locations) share one collection
// with a `kind` discriminator, so this is one screen with three tabs rather than three screens.
//
// Retiring is the only removal path: `active=false` takes a value out of the pickers while
// leaving every employee that references it by name rendering correctly. A hard delete would
// silently blank those records, so it isn't offered.

const KINDS = [
  { key: 'department', label: 'Departments', icon: Building2, singular: 'Department' },
  { key: 'designation', label: 'Designations', icon: Briefcase, singular: 'Designation' },
  { key: 'location', label: 'Locations', icon: MapPin, singular: 'Location' },
];

const LOCATION_TYPES = ['Office', 'Factory', 'Warehouse', 'Branch', 'Remote'];

const OrgStructure = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const canCreate = hasHrmsPermission(user, 'hrms', 'create');
  const canUpdate = hasHrmsPermission(user, 'hrms', 'update');

  const [kind, setKind] = useState('department');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showInactive, setShowInactive] = useState(false);

  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ name: '', code: '', head: '', department: '', grade: '', type: 'Office', city: '', state: '' });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getOrgMasters({ kind, include_inactive: showInactive || undefined });
      setRows(res.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load organization data');
    } finally {
      setLoading(false);
    }
  }, [kind, showInactive]);

  useEffect(() => { load(); }, [load]);

  const resetDraft = () =>
    setDraft({ name: '', code: '', head: '', department: '', grade: '', type: 'Office', city: '', state: '' });

  const submit = async () => {
    if (!draft.name.trim()) { showError('Name is required'); return; }
    setSaving(true);
    try {
      await createOrgMaster({ kind, ...draft, name: draft.name.trim() });
      showSuccess(`${current.singular} added`);
      resetDraft();
      setAdding(false);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to add entry');
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (row) => {
    try {
      await updateOrgMaster(row.id, { active: !row.active });
      showSuccess(row.active ? `${row.name} retired` : `${row.name} restored`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update entry');
    }
  };

  const current = KINDS.find((k) => k.key === kind) || KINDS[0];

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <Building2 size={20} />
          </span>
          <div>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-[var(--text-main)] leading-tight">
              Organization
            </h1>
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              Departments, designations and locations
            </p>
          </div>
        </div>
        {canCreate && !adding && (
          <button onClick={() => setAdding(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] transition-all">
            <Plus size={15} /> Add {current.singular}
          </button>
        )}
      </div>

      {/* Kind tabs */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {KINDS.map((k) => (
          <button key={k.key} onClick={() => { setKind(k.key); setAdding(false); resetDraft(); }}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest transition-colors border ${
              kind === k.key
                ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]'
                : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
            }`}>
            <k.icon size={14} /> {k.label}
          </button>
        ))}
        <label className="flex items-center gap-2 px-3 py-2 ml-auto rounded-xl bg-[var(--input-bg)] border border-[var(--input-border)] cursor-pointer">
          <input type="checkbox" checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
            className="w-3.5 h-3.5 accent-[var(--accent-indigo)]" />
          <span className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
            Show retired
          </span>
        </label>
      </div>

      {/* Add form */}
      {adding && (
        <div className="p-4 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-3.5">
          <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
            New {current.singular}
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
            <Field label="Name" required>
              <input className={inputCls} value={draft.name} autoFocus
                onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </Field>

            {kind === 'department' && (
              <>
                <Field label="Code">
                  <input className={inputCls} value={draft.code}
                    onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
                </Field>
                <Field label="Head">
                  <input className={inputCls} value={draft.head}
                    onChange={(e) => setDraft({ ...draft, head: e.target.value })} />
                </Field>
              </>
            )}

            {kind === 'designation' && (
              <>
                <Field label="Department">
                  <input className={inputCls} value={draft.department}
                    onChange={(e) => setDraft({ ...draft, department: e.target.value })} />
                </Field>
                <Field label="Grade">
                  <input className={inputCls} value={draft.grade}
                    onChange={(e) => setDraft({ ...draft, grade: e.target.value })} />
                </Field>
              </>
            )}

            {kind === 'location' && (
              <>
                <Field label="Type">
                  <select className={`${inputCls} cursor-pointer`} value={draft.type}
                    onChange={(e) => setDraft({ ...draft, type: e.target.value })}>
                    {LOCATION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Field>
                <Field label="City">
                  <input className={inputCls} value={draft.city}
                    onChange={(e) => setDraft({ ...draft, city: e.target.value })} />
                </Field>
              </>
            )}
          </div>
          <div className="flex items-center justify-end gap-2">
            <button onClick={() => { setAdding(false); resetDraft(); }}
              className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
              Cancel
            </button>
            <button onClick={submit} disabled={saving}
              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
              {saving && <Loader2 size={13} className="animate-spin" />} Add
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
          style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full" style={{ minWidth: 620 }}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                {['Name', 'Details', 'Status', ''].map((h, i) => (
                  <th key={i}
                    className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={4} className="px-4 py-12 text-center">
                  <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                    <Loader2 size={16} className="animate-spin" /> Loading…
                  </span>
                </td></tr>
              )}

              {!loading && rows.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-12 text-center">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">
                    No {current.label.toLowerCase()} yet.
                  </p>
                  <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                    They also appear automatically when someone types a new value on the employee form.
                  </p>
                </td></tr>
              )}

              {!loading && rows.map((r) => (
                <tr key={r.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <td className="px-4 py-3 text-[13px] font-black text-[var(--text-main)]">{r.name}</td>
                  <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                    {[r.code, r.head, r.department, r.grade, r.type, r.city, r.state]
                      .filter(Boolean).join(' · ') || '—'}
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-block px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border"
                      style={r.active
                        ? { color: 'var(--status-active-text)', backgroundColor: 'var(--status-active-bg)', borderColor: 'var(--status-active-border)' }
                        : { color: 'var(--text-muted)', backgroundColor: 'var(--input-bg)', borderColor: 'var(--border)' }}>
                      {r.active ? 'Active' : 'Retired'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {canUpdate && (
                      <button onClick={() => toggleActive(r)}
                        title={r.active ? 'Retire' : 'Restore'}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors">
                        {r.active ? <><Power size={12} /> Retire</> : <><Check size={12} /> Restore</>}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-[11.5px] font-medium text-[var(--text-muted)] flex items-start gap-2">
        <X size={13} className="mt-0.5 shrink-0" />
        Entries are retired, never deleted — employees that reference a value by name keep
        displaying it correctly.
      </p>
    </div>
  );
};

export default OrgStructure;
