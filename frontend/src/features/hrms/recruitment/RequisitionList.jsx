import React, { useCallback, useEffect, useState } from 'react';
import { ClipboardList, Plus, Search, ShieldCheck, Clock, FolderOpen, Layers } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getRequisitions, getRequisition, getDepartments } from '../../../services/hrmsApi';
import RequisitionFormModal from './RequisitionFormModal';
import RequisitionDrawer from './RequisitionDrawer';

/**
 * HRMS ▸ hiring requisitions (FMS).
 *
 * The recruitment entry point. Stat tiles, filters, a table, and a slide-over drawer that
 * carries the approval chain.
 *
 * The tiles come from the same server-side scoped query as the list, so the counts always
 * agree with what the user can actually see — a plain employee's tiles reflect only the
 * requisitions they raised.
 */

const APPROVAL_TONES = {
  'Pending HR Review': 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  'Pending MD Approval': 'bg-[var(--input-bg)] text-[var(--text-main)]',
  Approved: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Rejected: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};

const Pill = ({ value, tones }) => (
  <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold whitespace-nowrap ${
    (tones || {})[value] || 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
    {value || '—'}
  </span>
);

const Tile = ({ icon: Icon, label, value }) => (
  <div className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
    <div className="flex items-center gap-2 text-[var(--text-muted)]">
      <Icon size={14} />
      <span className="text-[10.5px] font-bold uppercase tracking-widest">{label}</span>
    </div>
    <p className="mt-1.5 text-[20px] font-bold text-[var(--text-main)]">{value ?? 0}</p>
  </div>
);

const RequisitionList = () => {
  const { can, scope, companyId } = useHrms();

  const [data, setData] = useState({ requisitions: [], total: 0, stats: {} });
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [approval, setApproval] = useState('');
  const [closing, setClosing] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [selected, setSelected] = useState(null);

  const canCreate = can(CAP.REQUISITION_CREATE);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getRequisitions({
        ...scope,
        search: debounced || undefined,
        approval_status: approval || undefined,
        closing_status: closing || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load requisitions.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, debounced, approval, closing]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!companyId) return;
    getDepartments(scope).then(({ data: d }) => setDepartments(d?.departments || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  // Always re-fetch the full record (with its JD) when opening the drawer — the list rows
  // are deliberately lightweight.
  const open = async (requestNo) => {
    try {
      const { data: full } = await getRequisition(requestNo, scope);
      setSelected(full);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not open that requisition.');
    }
  };

  const refresh = async () => {
    await load();
    if (selected) {
      try {
        const { data: full } = await getRequisition(selected.request_no, scope);
        setSelected(full);
      } catch { setSelected(null); }
    }
  };

  const stats = data.stats || {};

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={ClipboardList}
        title="Hiring Requisitions"
        subtitle="Raise a role, route it through HR review and MD approval."
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            {canCreate && (
              <button type="button" onClick={() => { setEditing(null); setShowForm(true); }}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
                <Plus size={14} /> New requisition
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Tile icon={Layers} label="Total" value={stats.total} />
        <Tile icon={ShieldCheck} label="Pending HR review" value={stats.pending_hr} />
        <Tile icon={Clock} label="Pending MD approval" value={stats.pending_md} />
        <Tile icon={FolderOpen} label="Open positions" value={stats.open} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by number, role or who raised it…"
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
        </div>
        <select value={approval} onChange={(e) => setApproval(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All approvals</option>
          {['Pending HR Review', 'Pending MD Approval', 'Approved', 'Rejected'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={closing} onChange={(e) => setClosing(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All statuses</option>
          {['Open', 'Hired', 'Hold', 'Closed', 'Cancel'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {loading ? (
        <HrmsLoading label="Loading requisitions…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.requisitions.length === 0 ? (
        <HrmsEmpty
          icon={ClipboardList}
          title="No requisitions match"
          hint={search || approval || closing
            ? 'Try clearing the filters.'
            : canCreate ? 'Raise your first hiring requisition to get started.' : undefined}
        />
      ) : (
        <div className="rounded-xl border border-[var(--border)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[820px]">
            <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
              <tr>
                {['Requisition', 'Department', 'Raised by', 'Vac.', 'Approval', 'Status'].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.requisitions.map((r) => (
                <tr key={r.request_no} onClick={() => open(r.request_no)}
                  className="border-t border-[var(--border)] cursor-pointer hover:bg-[var(--input-bg)] transition-colors">
                  <td className="px-4 py-2.5">
                    <div className="font-mono text-[11.5px] text-[var(--text-muted)]">{r.request_no}</div>
                    <div className="font-semibold text-[var(--text-main)]">{r.designation_name}</div>
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">{r.department_name}</td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">{r.created_by_name}</td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">{r.vacancy}</td>
                  <td className="px-4 py-2.5"><Pill value={r.approval_status} tones={APPROVAL_TONES} /></td>
                  <td className="px-4 py-2.5"><Pill value={r.closing_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <RequisitionFormModal
          existing={editing}
          onClose={() => { setShowForm(false); setEditing(null); }}
          onSaved={() => { setShowForm(false); setEditing(null); refresh(); }}
        />
      )}

      {selected && (
        <RequisitionDrawer
          requisition={selected}
          onClose={() => setSelected(null)}
          onChanged={refresh}
          onEdit={(r) => { setSelected(null); setEditing(r); setShowForm(true); }}
        />
      )}
    </div>
  );
};

export default RequisitionList;
