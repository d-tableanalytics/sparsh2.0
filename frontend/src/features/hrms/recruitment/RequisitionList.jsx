import React, { useCallback, useEffect, useState } from 'react';
import {
  Briefcase, Plus, Search, ShieldCheck, Clock, Building2, ClipboardList,
  User, Eye, Pencil, Trash2, CheckCircle2, XCircle, X,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getRequisitions, getRequisition, getDepartments, deleteRequisition,
} from '../../../services/hrmsApi';
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
 *
 * Row actions are gated on exactly the conditions the drawer (and therefore the server)
 * uses. A control that appears here and 403s when pressed is the precise failure the
 * module's access design exists to prevent, so the two must not drift: edit follows
 * `requisition.write` + an editable stage, delete follows `requisition.write` + not yet
 * approved, and Review appears only for the role that owns the CURRENT stage.
 */

/** The approval chain's own vocabulary is long; the table shows the stage, not the
 *  sentence. The full wording still appears in the drawer and the filter. */
const APPROVAL_LABEL = {
  'Pending HR Review': 'HR Review',
  // Phase 11-R, Item 7 — the over-sanction detour between HR and MD.
  'Pending Escalation': 'Escalation',
  'Pending MD Approval': 'MD Approval',
};

const APPROVAL_STYLE = {
  'Pending HR Review': {
    icon: ShieldCheck,
    cls: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]',
  },
  'Pending Escalation': {
    icon: Clock,
    cls: 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)] border-[var(--accent-orange-border)]',
  },
  'Pending MD Approval': {
    icon: Clock,
    cls: 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)] border-[var(--accent-orange-border)]',
  },
  Approved: {
    icon: CheckCircle2,
    cls: 'bg-[var(--accent-green-bg)] text-[var(--accent-green)] border-[var(--accent-green-border)]',
  },
  Rejected: {
    icon: XCircle,
    cls: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)] border-[var(--accent-red-border)]',
  },
};

const CLOSING_STYLE = {
  Open: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]',
  Hired: 'bg-[var(--accent-green-bg)] text-[var(--accent-green)] border-[var(--accent-green-border)]',
  Hold: 'bg-[var(--accent-yellow-bg)] text-[var(--accent-yellow)] border-[var(--accent-yellow-border)]',
  Closed: 'bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--border)]',
  Cancel: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)] border-[var(--accent-red-border)]',
};

const URGENCY_STYLE = {
  High: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Medium: 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]',
  Low: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

const TILE_TONES = {
  indigo: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  orange: 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]',
  yellow: 'bg-[var(--accent-yellow-bg)] text-[var(--accent-yellow)]',
  green: 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]',
};

const raisedOn = (value) => {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

const ctcLabel = (value) =>
  value == null || value === '' ? '—' : `₹${Number(value).toLocaleString('en-IN')}`;

/** Label above value, icon pushed to the far edge. A tile is mostly empty space when the
 *  count is a single digit; anchoring the icon right uses that width instead of leaving a
 *  gap, and label-then-number is the order the eye needs when scanning four of them. */
const Tile = ({ icon: Icon, label, value, tone }) => (
  <div className="p-4 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] flex items-center justify-between gap-3 transition-colors hover:border-[var(--accent-indigo)]">
    <div className="min-w-0">
      <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] truncate">
        {label}
      </p>
      <p className="mt-1.5 text-[24px] font-bold leading-none text-[var(--text-main)]">{value ?? 0}</p>
    </div>
    <div className={`h-10 w-10 rounded-xl grid place-items-center shrink-0 ${TILE_TONES[tone]}`}>
      <Icon size={18} />
    </div>
  </div>
);

const StatusPill = ({ label, cls, icon: Icon }) => (
  <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-[11px] font-bold whitespace-nowrap ${
    cls || 'bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--border)]'}`}>
    {Icon && <Icon size={11} />}
    {label || '—'}
  </span>
);

const IconAction = ({ icon: Icon, title, onClick, tone = 'indigo' }) => (
  <button
    type="button"
    title={title}
    aria-label={title}
    onClick={onClick}
    className={`p-1.5 rounded-lg text-[var(--text-muted)] transition-colors ${
      tone === 'red'
        ? 'hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]'
        : 'hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]'}`}
  >
    <Icon size={15} />
  </button>
);

const RequisitionList = () => {
  const { can, scope, companyId, companies } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState({ requisitions: [], total: 0, stats: {} });
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [department, setDepartment] = useState('');
  const [approval, setApproval] = useState('');
  const [closing, setClosing] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [selected, setSelected] = useState(null);

  const canCreate = can(CAP.REQUISITION_CREATE);
  const canWrite = can(CAP.REQUISITION_WRITE);

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
        department_id: department || undefined,
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
  }, [companyId, debounced, department, approval, closing]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!companyId) return;
    setDepartment('');
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

  // Edit from a row must load the FULL record first. A list row carries no `jd`, and the
  // form seeds its JD fields from `existing.jd` — opening it from a row would show an empty
  // job description and save that emptiness over the real one. The drawer has always passed
  // the full record for exactly this reason; the row now does the same.
  const edit = async (requestNo) => {
    try {
      const { data: full } = await getRequisition(requestNo, scope);
      setEditing(full);
      setShowForm(true);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not open that requisition.');
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

  // Same wording and the same irreversible-action confirmation as the drawer's delete, so
  // a requisition removed from the row and one removed from the drawer behave identically.
  const remove = async (r) => {
    if (!window.confirm(`Delete requisition ${r.request_no}? This cannot be undone.`)) return;
    try {
      await deleteRequisition(r.request_no, scope);
      showSuccess(`${r.request_no} deleted`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete.');
    }
  };

  const editable = (r) => canWrite
    && ['Pending HR Review', 'Pending Escalation', 'Pending MD Approval']
      .includes(r.approval_status);
  const deletable = (r) => canWrite && r.approval_status !== 'Approved';
  /** Is THIS user the one who owes the current stage an answer?
   *  Phase 11-R adds the escalation rung, which is held by MANAGER and MD. */
  const reviewable = (r) =>
    (r.approval_status === 'Pending HR Review' && can(CAP.REQUISITION_REVIEW_HR))
    || (r.approval_status === 'Pending Escalation' && can(CAP.REQUISITION_ESCALATE))
    || (r.approval_status === 'Pending MD Approval' && can(CAP.REQUISITION_APPROVE_MD));

  const companyName = (id) => companies.find((c) => String(c.id) === String(id))?.name;

  const stats = data.stats || {};
  const filtered = !!(search || department || approval || closing);

  const selectCls = 'h-10 px-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] '
    + 'text-[12.5px] font-semibold text-[var(--text-main)] outline-none '
    + 'focus:border-[var(--accent-indigo)] transition-colors';

  return (
    <div className="space-y-5">
      {/* Page title row */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h1 className="text-[20px] font-bold tracking-tight text-[var(--text-main)]">
            Hiring Requisition (FMS)
          </h1>
          <p className="text-[12px] text-[var(--text-muted)] mt-0.5">
            {loading
              ? 'Loading…'
              : `${data.total || 0} ${data.total === 1 ? 'requisition' : 'requisitions'}${
                filtered ? ' matching your filters' : ''}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <HrmsScopeBar />
          {canCreate && (
            <button
              type="button"
              onClick={() => { setEditing(null); setShowForm(true); }}
              className="h-10 px-4 rounded-xl bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold flex items-center gap-1.5 shadow-sm hover:opacity-90 transition-opacity"
            >
              <Plus size={15} /> New Requisition
            </button>
          )}
        </div>
      </div>

      {/* Stat tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3.5">
        <Tile icon={Briefcase} tone="indigo" label="Total requisitions" value={stats.total} />
        <Tile icon={ShieldCheck} tone="orange" label="Pending HR review" value={stats.pending_hr} />
        <Tile icon={Clock} tone="yellow" label="Pending MD approval" value={stats.pending_md} />
        <Tile icon={Building2} tone="green" label="Open positions" value={stats.open} />
      </div>

      {/* Filters. The three selects share a fixed basis and the search takes the remainder,
          so the row wraps as a block instead of letting the last select run off the edge on
          a narrow viewport. */}
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative flex-1 basis-[280px] min-w-[220px]">
          <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by request no, designation or who raised it…"
            className="w-full h-10 pl-10 pr-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] text-[13px] text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] transition-colors placeholder:text-[var(--text-muted)]"
          />
        </div>
        <select value={department} onChange={(e) => setDepartment(e.target.value)} className={selectCls}>
          <option value="">All Departments</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select value={approval} onChange={(e) => setApproval(e.target.value)} className={selectCls}>
          <option value="">All Approvals</option>
          {['Pending HR Review', 'Pending MD Approval', 'Approved', 'Rejected'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={closing} onChange={(e) => setClosing(e.target.value)} className={selectCls}>
          <option value="">All Statuses</option>
          {['Open', 'Hired', 'Hold', 'Closed', 'Cancel'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {filtered && (
          <button
            type="button"
            onClick={() => { setSearch(''); setDepartment(''); setApproval(''); setClosing(''); }}
            className="h-10 px-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] text-[12px] font-bold text-[var(--text-muted)] hover:text-[var(--text-main)] hover:border-[var(--accent-indigo)] transition-colors flex items-center gap-1.5"
          >
            <X size={13} /> Clear
          </button>
        )}
      </div>

      {loading ? (
        // The three states live inside the same framed surface the table occupies, so the
        // page keeps its shape while loading or empty instead of collapsing to a bare void.
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)]">
          <HrmsLoading label="Loading requisitions…" />
        </div>
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.requisitions.length === 0 ? (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)]">
          <HrmsEmpty
            icon={ClipboardList}
            title={filtered ? 'No requisitions match' : 'No requisitions yet'}
            hint={filtered
              ? 'Nothing matches the current filters — clear them to see everything.'
              : canCreate
                ? 'Raise a role, route it through HR review and MD approval.'
                : 'Requisitions you raise will appear here.'}
            action={filtered ? (
              <button
                type="button"
                onClick={() => { setSearch(''); setDepartment(''); setApproval(''); setClosing(''); }}
                className="h-9 px-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] text-[12px] font-bold text-[var(--text-muted)] hover:text-[var(--text-main)] hover:border-[var(--accent-indigo)] transition-colors"
              >
                Clear filters
              </button>
            ) : canCreate ? (
              <button
                type="button"
                onClick={() => { setEditing(null); setShowForm(true); }}
                className="h-9 px-4 rounded-xl bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 shadow-sm hover:opacity-90 transition-opacity"
              >
                <Plus size={14} /> New Requisition
              </button>
            ) : undefined}
          />
        </div>
      ) : (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[1040px]">
            <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
              <tr>
                {['Requisition', 'Department', 'Raised by', 'Vacancy', 'Offered CTC',
                  'MD Approval', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-widest whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.requisitions.map((r) => {
                const approvalStyle = APPROVAL_STYLE[r.approval_status] || {};
                const raised = raisedOn(r.created_at);
                const company = companyName(r.company_id);
                return (
                  <tr
                    key={r.request_no}
                    onClick={() => open(r.request_no)}
                    className="border-t border-[var(--border)] cursor-pointer hover:bg-[var(--input-bg)] transition-colors"
                  >
                    <td className="px-4 py-3 align-top">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-[var(--accent-indigo)]">
                          {r.request_no}
                        </span>
                        {r.urgency_level && (
                          <span className={`px-1.5 py-0.5 rounded-md text-[9.5px] font-bold uppercase tracking-wider ${
                            URGENCY_STYLE[r.urgency_level] || URGENCY_STYLE.Low}`}>
                            {r.urgency_level}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 font-bold text-[13.5px] text-[var(--text-main)]">
                        {r.designation_name}
                      </div>
                      {raised && (
                        <div className="mt-0.5 text-[10.5px] font-medium text-[var(--text-muted)]">
                          Raised {raised}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <div className="font-semibold text-[var(--text-main)]">{r.department_name}</div>
                      {company && (
                        <div className="mt-0.5 text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                          {company}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span className="inline-flex items-center gap-1.5 text-[var(--text-main)]">
                        <User size={13} className="text-[var(--text-muted)]" />
                        {r.created_by_name}
                      </span>
                    </td>
                    <td className="px-4 py-3 align-top font-semibold text-[var(--text-main)]">{r.vacancy}</td>
                    <td className="px-4 py-3 align-top text-[var(--text-main)]">{ctcLabel(r.offering_ctc)}</td>
                    <td className="px-4 py-3 align-top">
                      <StatusPill
                        label={APPROVAL_LABEL[r.approval_status] || r.approval_status}
                        cls={approvalStyle.cls}
                        icon={approvalStyle.icon}
                      />
                      {/* ── Phase 11-R badges ── each renders only when it is true, so an
                          ordinary requisition looks exactly as it did before this phase. */}
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {r.requisition_type === 'Replacement' && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[var(--input-bg)] text-[var(--text-muted)]">
                            Replacement
                          </span>
                        )}
                        {r.sanction_snapshot?.is_over_sanction && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]">
                            Over-sanction
                          </span>
                        )}
                        {r.budget_status === 'Mismatch' && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[var(--accent-red-bg)] text-[var(--accent-red)]">
                            Budget mismatch
                          </span>
                        )}
                        {r.budget_status === 'Pending' && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[var(--input-bg)] text-[var(--text-muted)]">
                            Budget pending
                          </span>
                        )}
                        {r.client_name && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
                            {r.client_name}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <StatusPill label={r.closing_status} cls={CLOSING_STYLE[r.closing_status]} />
                    </td>
                    <td className="px-4 py-3 align-top" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-1">
                        {reviewable(r) && (
                          <button
                            type="button"
                            onClick={() => open(r.request_no)}
                            className="h-7 px-3 rounded-lg bg-[var(--accent-indigo)] text-white text-[11px] font-bold flex items-center gap-1.5 hover:opacity-90 transition-opacity"
                          >
                            <ShieldCheck size={12} /> Review
                          </button>
                        )}
                        <IconAction icon={Eye} title="View" onClick={() => open(r.request_no)} />
                        {editable(r) && (
                          <IconAction icon={Pencil} title="Edit" onClick={() => edit(r.request_no)} />
                        )}
                        {deletable(r) && (
                          <IconAction icon={Trash2} title="Delete" tone="red" onClick={() => remove(r)} />
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
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
