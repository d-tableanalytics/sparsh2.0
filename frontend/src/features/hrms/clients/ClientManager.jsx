import React, { useCallback, useEffect, useState } from 'react';
import { Building, Plus, Trash2, X, Search } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getClients, createClient, updateClient, deleteClient,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ the client master (Phase 11-R, Item 4).
 *
 * Who a vacancy is being filled FOR. Confirmed with the business before it was built: this
 * deployment runs the recruitment-AGENCY model, so clients are their own entities with
 * their own contacts.
 *
 * A client is NOT a tenant. The company scope bar above still decides whose data you are
 * looking at; the client is a reporting and routing dimension inside that. Keeping those
 * two apart is deliberate — a client that became a security boundary would be a second,
 * weaker one running in parallel with the real one.
 *
 * Deletion is refused while any requisition names the client; the API says how many and
 * offers deactivation instead.
 */

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const EMPTY = {
  name: '', code: '', industry: '', contact_name: '', contact_email: '',
  contact_phone: '', address: '', notes: '', active: true,
};

const ClientManager = () => {
  const { scope, can, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const canWrite = can(CAP.CLIENT_WRITE);
  const set = (k) => (e) => setForm((f) => ({
    ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value,
  }));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { ...scope, include_inactive: true, with_stats: true };
      if (search) params.search = search;
      const { data } = await getClients(params);
      setRows(data?.clients || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load clients.');
    } finally {
      setLoading(false);
    }
  }, [companyId, search]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const openNew = () => { setForm(EMPTY); setEditing('new'); };
  const openEdit = (row) => { setForm({ ...EMPTY, ...row }); setEditing(row.client_id); };

  const save = async () => {
    if (!form.name.trim()) { showError('Give the client a name.'); return; }
    setSaving(true);
    try {
      if (editing === 'new') {
        await createClient(form, scope);
        showSuccess('Client created.');
      } else {
        await updateClient(editing, form, scope);
        showSuccess('Client updated.');
      }
      setEditing(null);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the client.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (row) => {
    try {
      await deleteClient(row.client_id, scope);
      showSuccess(`'${row.name}' was deleted.`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete the client.');
    }
  };

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Building}
        title="Clients"
        subtitle="The organisations you recruit for — named on requisitions and used across recruitment reporting"
        actions={canWrite && (
          <button
            type="button"
            onClick={openNew}
            className="h-9 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold flex items-center gap-1.5"
          >
            <Plus size={14} />
            Add client
          </button>
        )}
      />
      <HrmsScopeBar />

      <div className="relative w-64">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
        <input
          className={`${FIELD} pl-8`}
          placeholder="Search clients"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading && <HrmsLoading label="Loading clients…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && rows.length === 0 && (
        <HrmsEmpty
          icon={Building}
          title="No clients yet"
          hint="Add the organisations you recruit for. Each requisition can then name one, and the recruitment dashboard can be filtered client by client."
        />
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[820px]">
            <thead>
              <tr className="border-b border-[var(--border)] text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                <th className="text-left px-4 py-2.5">Client</th>
                <th className="text-left px-4 py-2.5">Industry</th>
                <th className="text-left px-4 py-2.5">Contact</th>
                <th className="text-right px-4 py-2.5">Requisitions</th>
                <th className="text-right px-4 py-2.5">Open</th>
                <th className="text-left px-4 py-2.5">Status</th>
                <th className="text-right px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.client_id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2.5">
                    <span className="font-semibold text-[var(--text-main)]">{row.name}</span>
                    <span className="block text-[11px] font-mono text-[var(--text-muted)]">
                      {row.client_id}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{row.industry || '—'}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">
                    {row.contact_name || '—'}
                    {row.contact_email && (
                      <span className="block text-[11px]">{row.contact_email}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right text-[var(--text-main)]">
                    {row.requisition_count ?? 0}
                  </td>
                  <td className="px-4 py-2.5 text-right text-[var(--text-main)]">
                    {row.open_requisitions ?? 0}
                  </td>
                  <td className="px-4 py-2.5">
                    {row.active
                      ? <span className="text-[var(--accent-green,var(--accent-indigo))] font-semibold">Active</span>
                      : <span className="text-[var(--text-muted)]">Inactive</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1.5">
                      {canWrite && (
                        <button
                          type="button"
                          onClick={() => openEdit(row)}
                          className="h-7 px-2.5 rounded-lg border border-[var(--border)] text-[11px] font-bold text-[var(--text-muted)] hover:text-[var(--text-main)]"
                        >
                          Edit
                        </button>
                      )}
                      {canWrite && (
                        <button
                          type="button"
                          onClick={() => remove(row)}
                          title="Delete"
                          className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--accent-red)]"
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4 overflow-y-auto">
          <div className="w-full max-w-lg my-8 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-bold text-[var(--text-main)]">
                {editing === 'new' ? 'Add client' : 'Edit client'}
              </h2>
              <button type="button" onClick={() => setEditing(null)} className="text-[var(--text-muted)]">
                <X size={17} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className={LABEL}>Client name</label>
                <input className={FIELD} value={form.name} onChange={set('name')} />
              </div>
              <div>
                <label className={LABEL}>Code</label>
                <input className={FIELD} value={form.code || ''} onChange={set('code')} />
              </div>
              <div>
                <label className={LABEL}>Industry</label>
                <input className={FIELD} value={form.industry || ''} onChange={set('industry')} />
              </div>
              <div>
                <label className={LABEL}>Contact name</label>
                <input className={FIELD} value={form.contact_name || ''} onChange={set('contact_name')} />
              </div>
              <div>
                <label className={LABEL}>Contact phone</label>
                <input className={FIELD} value={form.contact_phone || ''} onChange={set('contact_phone')} />
              </div>
              <div className="col-span-2">
                <label className={LABEL}>Contact email</label>
                <input className={FIELD} value={form.contact_email || ''} onChange={set('contact_email')} />
              </div>
              <div className="col-span-2">
                <label className={LABEL}>Address</label>
                <textarea
                  className="w-full h-16 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
                  value={form.address || ''}
                  onChange={set('address')}
                />
              </div>
              <div className="col-span-2">
                <label className={LABEL}>Notes</label>
                <textarea
                  className="w-full h-16 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
                  value={form.notes || ''}
                  onChange={set('notes')}
                />
              </div>
            </div>

            <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
              <input type="checkbox" checked={!!form.active} onChange={set('active')} />
              Active
            </label>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="h-9 px-4 rounded-lg border border-[var(--border)] text-[13px] font-bold text-[var(--text-muted)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ClientManager;
