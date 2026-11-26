import React, { useCallback, useEffect, useState } from 'react';
import { Plus, Check, X, Loader2, Trash2 } from 'lucide-react';
import api from '../../services/api';
import { useAuth } from '../../context/AuthContext';

/**
 * "Department" (or "Designation") picker for the member forms — the company's MASTER list
 * (HRMS ▸ Departments / Designations, the one list every module uses) — with an inline
 * "Add …" that creates a new entry in that same master and selects it.
 *
 * Props: companyId ('internal' = Sparsh Magic's own staff), value (id), onChange(id),
 * kind ('department' | 'designation', default 'department'), labelClassName, selectClassName.
 */
const KINDS = {
  department: { label: 'Department', plural: 'departments' },
  designation: { label: 'Designation', plural: 'designations' },
};

const MasterDepartmentSelect = ({ companyId, value, onChange, kind = 'department', labelClassName, selectClassName }) => {
  const { label, plural } = KINDS[kind] || KINDS.department;
  const lower = label.toLowerCase();
  // Delete: Super Admin, Admin or MD only (the server enforces the same rule).
  const { user } = useAuth();
  const canDelete = ['superadmin', 'admin'].includes(user?.role)
    || (user?.governance_role || '').trim().toUpperCase() === 'MD';
  const [items, setItems] = useState([]);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    if (!companyId) return;
    api.get(`/companies/${companyId}/${plural}`)
      .then((res) => setItems(res.data?.[plural] || []))
      .catch(() => setItems([]));
  }, [companyId, plural]);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    const clean = name.trim();
    if (!clean) { setError(`Enter a ${lower} name.`); return; }
    setBusy(true); setError('');
    try {
      const { data } = await api.post(`/companies/${companyId}/${plural}`, { name: clean });
      setItems(data?.[plural] || []);
      if (data?.[kind]?.id) onChange(data[kind].id);   // select the new one
      setAdding(false); setName('');
    } catch (e) {
      setError(e?.response?.data?.detail || `Could not add the ${lower}.`);
    } finally {
      setBusy(false);
    }
  };

  // Deletes the CURRENTLY SELECTED entry. The server refuses (409) while anyone still has it.
  const remove = async () => {
    const current = items.find((d) => d.id === value);
    if (!current) return;
    if (!window.confirm(`Delete ${lower} "${current.name}"? It is removed for all modules.`)) return;
    setBusy(true); setError('');
    try {
      const { data } = await api.delete(`/companies/${companyId}/${plural}/${current.id}`);
      setItems(data?.[plural] || []);
      onChange('');
    } catch (e) {
      setError(e?.response?.data?.detail || `Could not delete the ${lower}.`);
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => { setAdding(false); setName(''); setError(''); };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 px-1">
        <label className={labelClassName}>{label}</label>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)] hover:underline">
            <Plus size={11} /> Add {label}
          </button>
        )}
      </div>
      {adding ? (
        <div className="flex items-center gap-1.5">
          <input autoFocus value={name} placeholder={`New ${lower} name`} className={selectClassName}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); save(); }   // never submit the member form
              if (e.key === 'Escape') cancel();
            }} />
          <button type="button" onClick={save} disabled={busy} title={`Save ${lower}`}
            className="shrink-0 p-2 rounded-lg bg-[var(--accent-indigo)] text-white disabled:opacity-50">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
          </button>
          <button type="button" onClick={cancel} disabled={busy} title="Cancel"
            className="shrink-0 p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)]">
            <X size={14} />
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-1.5">
          <select className={selectClassName} value={value || ''} onChange={(e) => { setError(''); onChange(e.target.value); }}>
            <option value="">{items.length ? `Select ${label}` : `No ${plural} yet — use Add ${label}`}</option>
            {items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          {value && canDelete && (
            <button type="button" onClick={remove} disabled={busy} title={`Delete selected ${lower}`}
              className="shrink-0 p-2 rounded-lg border border-[var(--border)] text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] disabled:opacity-50">
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            </button>
          )}
        </div>
      )}
      {error && <p className="px-1 text-[11px] font-semibold text-[var(--accent-red)]">{error}</p>}
      {adding && !error && (
        <p className="px-1 text-[10.5px] text-[var(--text-muted)]">Added to the company's {lower} list, used by all modules.</p>
      )}
    </div>
  );
};

export default MasterDepartmentSelect;
