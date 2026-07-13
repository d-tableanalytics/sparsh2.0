import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  ListChecks, UserPlus, Filter as FilterIcon, Search, RefreshCw, Download,
  List as ListIcon, Table2, ArrowUpDown, Trash2, RotateCcw,
  Calendar as CalendarIcon, Eye, X, ChevronDown, Repeat,
} from 'lucide-react';
import api from '../../services/api';
import { getTasks, softDeleteTask, restoreTask, updateTaskStatus, reviseTaskDeadline } from '../../services/taskApi';
import { getTaskCategories, getTaskTags } from '../../services/taskMetaApi';
import { openTaskEventStream } from '../../services/taskEventsApi';
import { getHolidays } from '../../services/holidayApi';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { STATUS_CONFIG, LIST_CARD_ORDER, CARD_KEY_TO_STATUS, PRIORITY_CONFIG, WORKFLOW_STATUSES, statusOptions, statusOptionLabel, REASON_REQUIRED_STATUSES, VERIFICATION_ACTIONS } from './statusConfig';
import { getInitials, formatRelativeTime, formatFrequencyLabel, formatDate, exportTasksToCsv, groupTasksByRecurrence } from './taskDisplayUtils';
import StatusSummaryCards from './StatusSummaryCards';
import DateRangeFilter from './DateRangeFilter';
import TaskFormModal from './TaskFormModal';
import TaskDetailsModal from './TaskDetailsModal';
import StatusReasonModal from './StatusReasonModal';
import MiniDatePicker from './MiniDatePicker';

// One row in the card/list view. Extracted so both a standalone task and a recurring
// series' primary occurrence render identically; `groupBadge` adds the "×N / expand" control
// for the row that represents a collapsed series, and `indent` visually nests the occurrences
// once that series is expanded.
const TaskRow = ({
  task, scope, userMap, checked, onToggleSelect, onOpenDetails, onStatusChange,
  onRestore, indent, groupBadge, statusPending, isAssigner, frozenReason, isDependencyDoer,
}) => {
  const cfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending;
  const priorityCfg = PRIORITY_CONFIG[task.priority] || PRIORITY_CONFIG.Normal;
  const counterpartLabel = scope === 'delegated'
    ? `To: ${(task.assignedTo || []).map(id => userMap[id] || id).join(', ') || '—'}`
    : `From: ${userMap[task.assignedBy] || 'Someone'}`;
  // Completion lives in the status dropdown itself — on the doer's side it reads "Request for
  // Verification" when the task needs verifying (see TaskDetailsModal for the same rule).
  const isDoerSide = scope === 'my' && !isAssigner;
  // Once submitted, the task is the assigner's to approve or send back — the assignee gets a
  // read-only badge rather than a status control they aren't allowed to act on.
  const awaitingVerification = isDoerSide && task.status === 'verification';
  // The assigner's side of the same moment: the only two moves are Approve and Reopen.
  const isVerifying = !isDoerSide && task.status === 'verification';
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      className={`flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl px-4 py-3.5 hover:shadow-md transition-all ${indent ? 'ml-8' : ''}`}>
      {scope !== 'deleted' && (
        <input type="checkbox" checked={checked} onChange={onToggleSelect} className="shrink-0" />
      )}
      <div className="w-9 h-9 rounded-full flex items-center justify-center text-white font-black text-[11px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
        {getInitials(userMap[task.assignedBy] || task.title)}
      </div>

      <div className="min-w-0 flex-1 cursor-pointer" onClick={onOpenDetails}>
        <p className="text-[11px] font-bold text-[var(--text-muted)] truncate">
          {counterpartLabel} <span className="text-[13px] font-black text-[var(--text-main)] ml-1">{task.title}</span>
        </p>
        {(task.tags || []).length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {task.tags.map(tag => (
              <span key={tag} className="px-2 py-0.5 rounded-full text-[8px] font-black uppercase tracking-wider bg-[var(--accent-green-bg)] text-[var(--accent-green)] border border-[var(--accent-green-border)]">
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
        {groupBadge}
        {scope === 'deleted' || awaitingVerification ? (
          <span className="px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-wider border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>{cfg.label}</span>
        ) : frozenReason ? (
          // In-Loop observer, or an assignee waiting on a dependency doer: visible but frozen.
          <select value={task.status} disabled onClick={e => e.stopPropagation()} title={frozenReason}
            className="px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-wider border outline-none opacity-60 cursor-not-allowed"
            style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
            <option value={task.status}>{cfg.label}</option>
          </select>
        ) : isVerifying ? (
          <select value={task.status} onChange={e => onStatusChange(e.target.value)} onClick={e => e.stopPropagation()} disabled={statusPending}
            className="px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-wider border outline-none cursor-pointer disabled:opacity-60 disabled:cursor-wait"
            style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
            <option value={task.status} disabled>{cfg.label}</option>
            {VERIFICATION_ACTIONS.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
          </select>
        ) : (
          <select value={task.status} onChange={e => onStatusChange(e.target.value)} onClick={e => e.stopPropagation()} disabled={statusPending}
            className="px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-wider border outline-none cursor-pointer disabled:opacity-60 disabled:cursor-wait"
            style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
            {statusOptions(task.status, { isDependencyDoer })
              .map(s => <option key={s} value={s}>{statusOptionLabel(s, { verificationRequired: task.verificationRequired, isAssigner, isDependencyDoer, currentStatus: task.status })}</option>)}
          </select>
        )}
        <span className="px-2.5 py-1 rounded-full text-[9px] font-black uppercase tracking-wider bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)]">
          {formatFrequencyLabel(task.frequency)}
        </span>
        {task.end && (
          <span className={`flex items-center gap-1 text-[10px] font-bold ${task.isOverdue ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>
            <CalendarIcon size={11} /> {formatDate(task.end)}
          </span>
        )}
        <span className="flex items-center gap-1 text-[10px] font-bold text-[var(--text-muted)]">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: priorityCfg.color }} /> {task.priority || 'Normal'}
        </span>
        <span className="text-[10px] font-bold text-[var(--text-muted)] opacity-70">{formatRelativeTime(task.end || task.start)}</span>

        {/* Direct action buttons — the old kebab dropdown (which only held "View") is gone;
            clicking the row body opens details too, so this is just a redundant quick action. */}
        {scope === 'deleted' ? (
          <button onClick={(e) => { e.stopPropagation(); onRestore(); }} title="Restore"
            className="p-1.5 rounded-lg text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
            <RotateCcw size={15} />
          </button>
        ) : (
          <button onClick={(e) => { e.stopPropagation(); onOpenDetails(); }} title="View"
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--input-bg)]">
            <Eye size={15} />
          </button>
        )}
      </div>
    </motion.div>
  );
};

const SORT_OPTIONS = [
  { key: 'end', label: 'Target Date' },
  { key: 'createdAt', label: 'Created Date' },
  { key: 'title', label: 'Title' },
];

const TAB_KEYS = ['all', 'overdue', ...WORKFLOW_STATUSES];

// Shared list used by MyTasks, DelegatedTasks, SubscribedTasks, AllTasks and DeletedTasks —
// each just passes a different `scope` to GET /api/tasks. Visual design follows the
// reference "My Tasks" screenshot: dot-style summary cards, toolbar, scrollable status
// tabs, and avatar/badge row cards.
const TaskListView = ({ scope, heading, subheading, emptyMessage, allowCreate = true, groupId = null, embedded = false }) => {
  const { user } = useAuth();
  const isAdmin = ['superadmin', 'admin'].includes(user?.role);
  const { showSuccess, showError } = useNotification();
  const [tasks, setTasks] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [period, setPeriod] = useState('all_time');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [assignedTo, setAssignedTo] = useState('');
  const [category, setCategory] = useState('');
  const [tag, setTag] = useState('');
  const [frequency, setFrequency] = useState('');
  const [search, setSearch] = useState('');

  const [statusFilter, setStatusFilter] = useState('all');
  // Default to newest-created first so the latest task is always on top (#15). The backend
  // already returns tasks created-desc; this keeps that order as the default client sort too.
  const [sortKey, setSortKey] = useState('createdAt');
  const [sortDir, setSortDir] = useState('desc');
  const [viewMode, setViewMode] = useState('list');

  const [selected, setSelected] = useState(new Set());
  const [openMenuId, setOpenMenuId] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTask, setEditingTask] = useState(null);
  const [detailsTaskId, setDetailsTaskId] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState(new Set());
  const [completing, setCompleting] = useState(new Set()); // task ids with an in-flight status change
  const [reasonTarget, setReasonTarget] = useState(null); // { task, status } awaiting Doer Name + Reason
  const [savingReason, setSavingReason] = useState(false);
  // Reopen (assigner, from Pending Verification): the task awaiting a new deadline + reason.
  const [reopenTarget, setReopenTarget] = useState(null);
  // Holidays + Sunday weekly-off block selection in the Reopen picker, matching the create form.
  const [holidayDates, setHolidayDates] = useState([]);
  const WEEKLY_OFFS = [0];

  const userMap = useMemo(() => {
    const m = {};
    users.forEach(u => { m[u._id] = u.full_name || u.email; });
    return m;
  }, [users]);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getTasks({
        scope,
        period,
        startDate: period === 'custom' ? startDate : undefined,
        endDate: period === 'custom' ? endDate : undefined,
        assignedTo: assignedTo || undefined,
        category: category || undefined,
        tag: tag || undefined,
        frequency: frequency || undefined,
        search: search || undefined,
        groupId: groupId || undefined,
      });
      setTasks(res.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [scope, period, startDate, endDate, assignedTo, category, tag, frequency, search, groupId]);

  const [categories, setCategories] = useState([]);
  const [tagOptions, setTagOptions] = useState([]);

  // Categories/tags are persisted server-side (task_categories / task_tags collections) and
  // shared across every task view — fetched once here rather than derived from whichever
  // tasks this particular scoped/filtered list happens to have loaded.
  const fetchTaxonomy = useCallback(async () => {
    try {
      const [catRes, tagRes] = await Promise.all([getTaskCategories(), getTaskTags()]);
      setCategories((catRes.data || []).map(c => c.name));
      setTagOptions((tagRes.data || []).map(t => t.name));
    } catch {
      // Non-fatal: task list/creation still works, just without a live options list.
    }
  }, []);

  useEffect(() => {
    api.get('/tasks/assignable-users').then(res => setUsers(res.data || [])).catch(() => {});
    // Holidays block dates in the Reopen picker.
    getHolidays().then(res => setHolidayDates((res.data || []).map(h => h.holiday_date).filter(Boolean))).catch(() => setHolidayDates([]));
  }, []);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);
  useEffect(() => { fetchTaxonomy(); }, [fetchTaxonomy]);
  useEffect(() => { setSelected(new Set()); }, [scope, statusFilter]);

  // ─── Real-time: refetch (debounced) when a task involving me changes elsewhere ───
  // The server (SSE) is the source of truth, so a debounced refetch keeps the current tab
  // correct without fragile client-side list merging (no dupes; tasks that left this
  // tab drop off). Keep fetchTasks in a ref so the stream isn't reopened on every filter change.
  const fetchTasksRef = useRef(fetchTasks);
  useEffect(() => { fetchTasksRef.current = fetchTasks; }, [fetchTasks]);
  const currentUserId = user?._id || user?.id;
  useEffect(() => {
    let debounce = null;
    const TOASTS = {
      task_created: 'New task assigned',
      task_assigned: 'New task assigned',
      task_completed: 'A task was completed',
      task_deleted: 'A task was removed',
    };
    // The verification hand-off is directional: only the assigner is asked to verify, and only
    // the assignee is told their task came back for rework. Toasting either event to everyone
    // on the task (watchers, the other side) would be noise, so these are addressed explicitly.
    const directedToast = (type, data) => {
      const isAssigner = data?.assigned_by && String(data.assigned_by) === String(currentUserId);
      const isAssignee = (data?.assigned_to || []).some(id => String(id) === String(currentUserId));
      if (type === 'task_verification_requested' && isAssigner) return 'A task is awaiting your verification';
      if (type === 'task_verification_rejected' && isAssignee) return 'A task was sent back to you for rework';
      return null;
    };
    const cleanup = openTaskEventStream((type, data) => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(() => fetchTasksRef.current?.(), 300);
      // Don't toast the user for their own action (they already see the optimistic update).
      const isSelf = data?.actor_id && currentUserId && String(data.actor_id) === String(currentUserId);
      if (isSelf) return;
      const message = TOASTS[type] || directedToast(type, data);
      if (message) showSuccess(message);
    });
    return () => { if (debounce) clearTimeout(debounce); cleanup(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUserId]);

  const summary = useMemo(() => {
    const s = { totalTasks: tasks.length, overdue: 0, pending: 0, accepted: 0, dependentOnOthers: 0, blocked: 0, inProgress: 0, verification: 0, completed: 0 };
    tasks.forEach(t => {
      if (t.isOverdue) s.overdue += 1;
      const key = Object.keys(CARD_KEY_TO_STATUS).find(k => CARD_KEY_TO_STATUS[k] === t.status);
      if (key) s[key] += 1;
    });
    return s;
  }, [tasks]);

  const tabCounts = useMemo(() => {
    const c = { all: tasks.length, overdue: 0 };
    WORKFLOW_STATUSES.forEach(s => { c[s] = 0; });
    tasks.forEach(t => {
      if (t.isOverdue) c.overdue += 1;
      c[t.status] = (c[t.status] || 0) + 1;
    });
    return c;
  }, [tasks]);

  const visibleTasks = useMemo(() => {
    let rows = tasks;
    if (statusFilter === 'overdue') rows = rows.filter(t => t.isOverdue);
    else if (statusFilter !== 'all') rows = rows.filter(t => t.status === statusFilter);

    rows = [...rows].sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'title') cmp = (a.title || '').localeCompare(b.title || '');
      else {
        const av = a[sortKey] ? new Date(a[sortKey]).getTime() : 0;
        const bv = b[sortKey] ? new Date(b[sortKey]).getTime() : 0;
        cmp = av - bv;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return rows;
  }, [tasks, statusFilter, sortKey, sortDir]);

  // Collapses same-series occurrences (see groupTasksByRecurrence) into one row each,
  // preserving visibleTasks' sort order via the first-seen occurrence in each group.
  const groupedRows = useMemo(() => groupTasksByRecurrence(visibleTasks), [visibleTasks]);

  const toggleGroupExpand = (key) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const toggleGroupSelect = (group) => {
    const ids = group.items.map(t => t.id);
    const allSelected = ids.every(id => selected.has(id));
    setSelected(prev => {
      const next = new Set(prev);
      ids.forEach(id => (allSelected ? next.delete(id) : next.add(id)));
      return next;
    });
  };

  const clearFilters = () => {
    setPeriod('all_time'); setStartDate(''); setEndDate('');
    setAssignedTo(''); setCategory(''); setTag(''); setFrequency(''); setSearch('');
    setStatusFilter('all');
  };

  const hasActiveFilters = period !== 'all_time' || assignedTo || category || tag || frequency || search || statusFilter !== 'all';

  const handleRestore = async (task) => {
    setOpenMenuId(null);
    try {
      await restoreTask(task.id);
      showSuccess('Task restored');
      fetchTasks();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to restore task');
    }
  };

  // In-Loop member (a watcher who is neither the assigner nor a doer): read-only observer, so
  // every status control is frozen for them. Mirrors isPureWatcher in TaskDetailsModal; the
  // backend rejects their status writes too (only admin/creator/assignee may update).
  const isWatcherOnly = (t) => !t.isCreator
    && !(t.assignedTo || []).includes(currentUserId)
    && (t.watchers || []).includes(currentUserId);

  // Dependency doer: the task was handed to them via "Dependent on Other". They hold ONLY the
  // dependency, so their options are limited to Complete / Dependent on Other (see statusConfig).
  const isDependencyDoer = (t) => !!t.dependencyDoerId && t.dependencyDoerId === currentUserId;
  // The assignee who raised the dependency still owns the task, but can't move it until the doer
  // resolves it — their control stays visible at "Dependent on Other" but frozen.
  const isAwaitingDependency = (t) => !!t.dependencyDoerId
    && t.dependencyDoerId !== currentUserId
    && (t.assignedTo || []).includes(currentUserId);
  // Why a row's status control is frozen, or null when it's live.
  const frozenReason = (t) => {
    if (isWatcherOnly(t)) return "Read-only — In-Loop members can't change the task status";
    if (isAwaitingDependency(t)) return 'Waiting on the dependency doer to complete their part';
    return null;
  };

  // Dependent on Other / Blocked need a Doer Name + Reason first, and Reopen needs a NEW
  // deadline + a mandatory reason — both open a modal; every other status applies immediately.
  const handleStatusChange = (task, status) => {
    if (frozenReason(task)) return;
    if (REASON_REQUIRED_STATUSES.includes(status)) {
      setReasonTarget({ task, status });
      return;
    }
    if (status === 'in_progress_reopened') {
      setReopenTarget(task);
      return;
    }
    doStatusUpdate(task, status);
  };

  // Reopen (assigner, from Pending Verification): set the new deadline first, then flip the
  // status back to the assignee. The reason lands in both the deadline-revision history and
  // the status history — same flow as TaskDetailsModal.
  const handleReopenWithDeadline = async (iso, remark) => {
    const task = reopenTarget;
    setReopenTarget(null);
    if (!task) return;
    setCompleting(prev => new Set(prev).add(task.id));
    try {
      await reviseTaskDeadline(task.id, iso, remark);
      await updateTaskStatus(task.id, 'in_progress_reopened', remark);
      showSuccess('Task reopened — sent back to the assignee for rework');
      fetchTasks();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to reopen the task');
    } finally {
      setCompleting(prev => {
        const next = new Set(prev);
        next.delete(task.id);
        return next;
      });
    }
  };

  const doStatusUpdate = async (task, status, { reason, doerName, doerId } = {}) => {
    if (completing.has(task.id)) return; // guard against double-click / duplicate requests
    const prevStatus = task.status;
    // Optimistic: reflect the new status immediately, mark in-flight.
    setCompleting(prev => new Set(prev).add(task.id));
    setTasks(ts => ts.map(t => (t.id === task.id ? { ...t, status } : t)));
    if (reasonTarget) setSavingReason(true);
    try {
      await updateTaskStatus(task.id, status, reason, doerName, doerId);
      setReasonTarget(null);
      fetchTasks(); // reconcile with server (also picked up via SSE for other users)
    } catch (err) {
      // Revert optimistic change on failure.
      setTasks(ts => ts.map(t => (t.id === task.id ? { ...t, status: prevStatus } : t)));
      showError(err.response?.data?.detail || 'Failed to update status');
    } finally {
      setSavingReason(false);
      setCompleting(prev => {
        const next = new Set(prev);
        next.delete(task.id);
        return next;
      });
    }
  };

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected(prev => (prev.size === visibleTasks.length ? new Set() : new Set(visibleTasks.map(t => t.id))));
  };

  const handleBulkAction = async () => {
    const ids = Array.from(selected);
    try {
      if (scope === 'deleted') {
        await Promise.all(ids.map(id => restoreTask(id)));
        showSuccess(`Restored ${ids.length} task(s)`);
      } else {
        await Promise.all(ids.map(id => softDeleteTask(id)));
        showSuccess(`Deleted ${ids.length} task(s)`);
      }
      setSelected(new Set());
      fetchTasks();
    } catch (err) {
      showError(err.response?.data?.detail || 'Bulk action failed');
    }
  };

  return (
    <div className="space-y-5 pb-24" onClick={() => openMenuId && setOpenMenuId(null)}>
      {!embedded && (
        <>
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo)] text-white flex items-center justify-center shadow-lg shadow-[var(--accent-indigo)]/20">
              <ListChecks size={20} />
            </div>
            <div>
              <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">{heading}</h1>
              <p className="text-[12px] text-[var(--text-muted)] font-bold">{subheading}</p>
            </div>
          </div>

          {/* ─── Toolbar ─── */}
          <div className="flex flex-wrap items-center gap-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-3">
            {allowCreate && (
              <button onClick={() => { setEditingTask(null); setModalOpen(true); }}
                className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all">
                <UserPlus size={14} /> Assign Task
              </button>
            )}

            <DateRangeFilter variant="dropdown" period={period} onPeriodChange={setPeriod} startDate={startDate} endDate={endDate}
              onCustomChange={(field, value) => (field === 'startDate' ? setStartDate(value) : setEndDate(value))} />

            <button onClick={() => setFiltersOpen(o => !o)}
              className={`flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all ${filtersOpen ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)]'}`}>
              <FilterIcon size={14} /> Filter
            </button>

            <div className="relative flex-1 min-w-[160px]">
              <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder={`Search ${heading.toLowerCase()}...`}
                className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
            </div>

            <button onClick={fetchTasks} title="Refresh" className="p-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-all">
              <RefreshCw size={15} />
            </button>

            <button onClick={() => exportTasksToCsv(visibleTasks, userMap, `${heading.toLowerCase().replace(/\s+/g, '-')}.csv`)}
              className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all">
              <Download size={14} /> Export
            </button>

            <div className="flex items-center gap-1 bg-[var(--input-bg)] border border-[var(--border)] p-1 rounded-xl">
              <button onClick={() => setViewMode('list')} title="List view" className={`p-2 rounded-lg transition-all ${viewMode === 'list' ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)]'}`}>
                <ListIcon size={15} />
              </button>
              <button onClick={() => setViewMode('table')} title="Table view" className={`p-2 rounded-lg transition-all ${viewMode === 'table' ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)]'}`}>
                <Table2 size={15} />
              </button>
            </div>

            <select value={sortKey} onChange={e => setSortKey(e.target.value)}
              className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
              {SORT_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
            </select>
            <button onClick={() => setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))} title="Toggle sort direction"
              className="p-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-all">
              <ArrowUpDown size={15} />
            </button>
          </div>

          {filtersOpen && (
            <div className="flex flex-wrap items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4">
              <select value={assignedTo} onChange={e => setAssignedTo(e.target.value)}
                className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
                <option value="">Assigned To</option>
                {users.map(u => <option key={u._id} value={u._id}>{u.full_name || u.email}</option>)}
              </select>
              <select value={category} onChange={e => setCategory(e.target.value)}
                className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
                <option value="">Category</option>
                {categories.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={tag} onChange={e => setTag(e.target.value)}
                className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
                <option value="">Tag</option>
                {tagOptions.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
              <select value={frequency} onChange={e => setFrequency(e.target.value)}
                className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
                <option value="">Frequency</option>
                {['Does not repeat', 'Daily', 'Weekly', 'Monthly', 'Yearly'].map(f => <option key={f} value={f}>{f}</option>)}
              </select>
              {hasActiveFilters && (
                <button onClick={clearFilters} className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)]">
                  <X size={13} /> Clear
                </button>
              )}
            </div>
          )}
        </>
      )}

      <StatusSummaryCards cardOrder={LIST_CARD_ORDER} summary={summary} activeKey={null} />

      {/* ─── Status Tabs ─── */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1 no-scrollbar">
        {TAB_KEYS.map(key => {
          const cfg = key === 'all' ? null : (key === 'overdue' ? { color: 'var(--accent-red)' } : STATUS_CONFIG[key]);
          const label = key === 'all' ? 'All' : (key === 'overdue' ? 'Overdue' : STATUS_CONFIG[key].label);
          const isActive = statusFilter === key;
          return (
            <button key={key} onClick={() => setStatusFilter(key)}
              className={`flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-[10px] font-black uppercase tracking-wider whitespace-nowrap transition-all border ${
                isActive ? 'bg-[var(--accent-indigo-bg)] border-[var(--accent-indigo)] text-[var(--accent-indigo)]' : 'border-transparent text-[var(--text-muted)] hover:bg-[var(--input-bg)]'
              }`}>
              {cfg && <span className="w-1.5 h-1.5 rounded-full" style={{ background: cfg.color }} />}
              {label} — {tabCounts[key] || 0}
            </button>
          );
        })}
      </div>

      {/* ─── Bulk action bar ─── */}
      {selected.size > 0 && (
        <div className="flex items-center justify-between bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] rounded-xl px-4 py-2.5">
          <span className="text-[11px] font-black text-[var(--accent-indigo)] uppercase tracking-wider">{selected.size} selected</span>
          <button onClick={handleBulkAction} className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest">
            {scope === 'deleted' ? <><RotateCcw size={12} /> Restore</> : <><Trash2 size={12} /> Delete</>}
          </button>
        </div>
      )}

      {/* ─── List ─── */}
      {loading ? (
        <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px]">Loading tasks...</div>
      ) : error ? (
        <div className="p-16 text-center text-[var(--accent-red)] text-[12px] font-bold bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px]">{error}</div>
      ) : visibleTasks.length === 0 ? (
        <div className="p-16 flex flex-col items-center justify-center text-[var(--text-muted)] bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px]">
          <ListChecks size={40} className="mb-3 opacity-30" />
          <p className="text-[12px] font-bold">{emptyMessage || 'No tasks found.'}</p>
        </div>
      ) : viewMode === 'table' ? (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-[var(--border)]">
                {['', 'Title', 'Category', 'Assigned To', 'Due', 'Status', ''].map(h => (
                  <th key={h} className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groupedRows.map(group => {
                const task = group.primary;
                const isSeries = group.items.length > 1;
                const cfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending;
                return (
                  <tr key={group.key} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                    <td className="px-4 py-3">
                      <input type="checkbox" checked={isSeries ? group.items.every(t => selected.has(t.id)) : selected.has(task.id)}
                        onChange={() => (isSeries ? toggleGroupSelect(group) : toggleSelect(task.id))} />
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-[13px] font-bold text-[var(--text-main)] flex items-center gap-1.5">
                        {task.title}
                        {isSeries && (
                          <span title={`Recurring series: ${group.items.length} occurrences`}
                            className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-wider bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border border-[var(--accent-indigo-border)]">
                            <Repeat size={10} /> ×{group.items.length}
                          </span>
                        )}
                      </p>
                      {task.isOverdue && <span className="text-[9px] font-black text-[var(--accent-red)] uppercase tracking-widest">Overdue</span>}
                    </td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{task.category || '—'}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{(task.assignedTo || []).map(id => userMap[id] || id).join(', ') || 'Myself'}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{task.end ? formatDate(task.end) : '—'}</td>
                    <td className="px-4 py-3">
                      {scope === 'deleted' ? (
                        <span className="px-3 py-1.5 rounded-lg text-[10px] font-black border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>{cfg.label}</span>
                      ) : (() => {
                        const rowIsAssigner = task.isCreator || isAdmin;
                        const rowIsDoerSide = scope === 'my' && !rowIsAssigner;
                        // In-Loop observer, or an assignee waiting on a dependency doer: frozen.
                        const rowFrozenReason = frozenReason(task);
                        if (rowFrozenReason) {
                          return (
                            <select value={task.status} disabled title={rowFrozenReason}
                              className="px-3 py-1.5 rounded-lg text-[10px] font-black border outline-none opacity-60 cursor-not-allowed"
                              style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                              <option value={task.status}>{cfg.label}</option>
                            </select>
                          );
                        }
                        // Submitted for verification → the assigner's call, so read-only here.
                        if (rowIsDoerSide && task.status === 'verification') {
                          return (
                            <span className="px-3 py-1.5 rounded-lg text-[10px] font-black border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>{cfg.label}</span>
                          );
                        }
                        // The assigner's side of verification: Approve or Reopen, nothing else.
                        if (task.status === 'verification') {
                          return (
                            <select value={task.status} onChange={e => handleStatusChange(task, e.target.value)} disabled={completing.has(task.id)}
                              className="px-3 py-1.5 rounded-lg text-[10px] font-black border outline-none cursor-pointer disabled:opacity-60 disabled:cursor-wait"
                              style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                              <option value={task.status} disabled>{cfg.label}</option>
                              {VERIFICATION_ACTIONS.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
                            </select>
                          );
                        }
                        const rowIsDependencyDoer = isDependencyDoer(task);
                        return (
                          <select value={task.status} onChange={e => handleStatusChange(task, e.target.value)} disabled={completing.has(task.id)}
                            className="px-3 py-1.5 rounded-lg text-[10px] font-black border outline-none cursor-pointer disabled:opacity-60 disabled:cursor-wait"
                            style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                            {statusOptions(task.status, { isDependencyDoer: rowIsDependencyDoer })
                              .map(s => <option key={s} value={s}>{statusOptionLabel(s, { verificationRequired: task.verificationRequired, isAssigner: rowIsAssigner, isDependencyDoer: rowIsDependencyDoer, currentStatus: task.status })}</option>)}
                          </select>
                        );
                      })()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {scope === 'deleted' ? (
                        <button onClick={() => handleRestore(task)} className="p-2 rounded-lg text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]" title="Restore"><RotateCcw size={14} /></button>
                      ) : (
                        <button onClick={() => setDetailsTaskId(task.id)} className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]" title="View"><Eye size={14} /></button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-2">
          <label className="flex items-center gap-2 px-1 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
            <input type="checkbox" checked={selected.size === visibleTasks.length} onChange={toggleSelectAll} /> Select All
          </label>
          {groupedRows.map(group => {
            const isSeries = group.items.length > 1;
            const isExpanded = expandedGroups.has(group.key);
            const rowProps = (task, { indent = false } = {}) => ({
              task, scope, userMap, indent,
              statusPending: completing.has(task.id),
              isAssigner: task.isCreator || isAdmin,
              frozenReason: frozenReason(task),
              isDependencyDoer: isDependencyDoer(task),
              checked: selected.has(task.id),
              onToggleSelect: () => toggleSelect(task.id),
              onOpenDetails: () => setDetailsTaskId(task.id),
              onStatusChange: (status) => handleStatusChange(task, status),
              onRestore: () => handleRestore(task),
            });
            return (
              <React.Fragment key={group.key}>
                <TaskRow
                  {...rowProps(group.primary)}
                  checked={isSeries ? group.items.every(t => selected.has(t.id)) : selected.has(group.primary.id)}
                  onToggleSelect={() => (isSeries ? toggleGroupSelect(group) : toggleSelect(group.primary.id))}
                  groupBadge={isSeries && (
                    <button onClick={(e) => { e.stopPropagation(); toggleGroupExpand(group.key); }} title="This is a recurring series — click to see/track each day"
                      className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[9px] font-black uppercase tracking-wider bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border border-[var(--accent-indigo-border)]">
                      <Repeat size={11} /> ×{group.items.length}
                      <ChevronDown size={12} className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                    </button>
                  )}
                />
                {isSeries && isExpanded && group.items.map(task => (
                  <TaskRow key={task.id} {...rowProps(task, { indent: true })} />
                ))}
              </React.Fragment>
            );
          })}
        </div>
      )}

      <TaskFormModal isOpen={modalOpen} onClose={() => setModalOpen(false)} task={editingTask} onSaved={fetchTasks}
        categories={categories} tags={tagOptions} onTaxonomyChanged={fetchTaxonomy} groupId={groupId} />
      <TaskDetailsModal isOpen={!!detailsTaskId} taskId={detailsTaskId} scope={scope} onClose={() => setDetailsTaskId(null)} onChanged={fetchTasks}
        onEdit={(t) => { setDetailsTaskId(null); setEditingTask(t); setModalOpen(true); }} />
      {/* Reopen (from Pending Verification): a NEW deadline + a mandatory reason, then the task
          goes back to the assignee for rework. */}
      <MiniDatePicker
        isOpen={!!reopenTarget}
        onClose={() => setReopenTarget(null)}
        value={reopenTarget?.end}
        title="Reopen Task"
        onApply={(iso, remark) => handleReopenWithDeadline(iso, remark)}
        holidayDates={holidayDates} weeklyOffs={WEEKLY_OFFS} onBlocked={showError}
        disablePast
        remarkLabel="Reason for Reopening" remarkRequired
      />
      {/* Doer Name + Reason capture for Dependent on Other / Blocked (from either list dropdown). */}
      <StatusReasonModal
        isOpen={!!reasonTarget}
        status={reasonTarget?.status}
        users={users}
        saving={savingReason}
        onClose={() => setReasonTarget(null)}
        onSubmit={({ reason, doerName, doerId }) => doStatusUpdate(reasonTarget.task, reasonTarget.status, { reason, doerName, doerId })}
      />
    </div>
  );
};

export default TaskListView;
