import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  ListChecks, UserPlus, Filter as FilterIcon, Search, RefreshCw, Download,
  List as ListIcon, Table2, ArrowUpDown, Trash2, RotateCcw, MoreVertical,
  Calendar as CalendarIcon, Pencil, X, Info,
} from 'lucide-react';
import api from '../../services/api';
import { getTasks, softDeleteTask, restoreTask, updateTaskStatus } from '../../services/taskApi';
import { useNotification } from '../../context/NotificationContext';
import { STATUS_CONFIG, LIST_CARD_ORDER, CARD_KEY_TO_STATUS, PRIORITY_CONFIG, WORKFLOW_STATUSES } from './statusConfig';
import { getInitials, formatRelativeTime, formatFrequencyLabel, exportTasksToCsv } from './taskDisplayUtils';
import StatusSummaryCards from './StatusSummaryCards';
import DateRangeFilter from './DateRangeFilter';
import TaskFormModal from './TaskFormModal';
import TaskDetailsModal from './TaskDetailsModal';

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
const TaskListView = ({ scope, heading, subheading, emptyMessage, allowCreate = true }) => {
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
  const [sortKey, setSortKey] = useState('end');
  const [sortDir, setSortDir] = useState('asc');
  const [viewMode, setViewMode] = useState('list');

  const [selected, setSelected] = useState(new Set());
  const [openMenuId, setOpenMenuId] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTask, setEditingTask] = useState(null);
  const [detailsTaskId, setDetailsTaskId] = useState(null);

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
      });
      setTasks(res.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [scope, period, startDate, endDate, assignedTo, category, tag, frequency, search]);

  useEffect(() => {
    api.get('/users?active_only=true').then(res => setUsers(res.data || [])).catch(() => {});
  }, []);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);
  useEffect(() => { setSelected(new Set()); }, [scope, statusFilter]);

  const categories = useMemo(() => Array.from(new Set(tasks.map(t => t.category).filter(Boolean))), [tasks]);
  const tagOptions = useMemo(() => Array.from(new Set(tasks.flatMap(t => t.tags || []))), [tasks]);

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

  const clearFilters = () => {
    setPeriod('all_time'); setStartDate(''); setEndDate('');
    setAssignedTo(''); setCategory(''); setTag(''); setFrequency(''); setSearch('');
    setStatusFilter('all');
  };

  const hasActiveFilters = period !== 'all_time' || assignedTo || category || tag || frequency || search || statusFilter !== 'all';

  const handleDelete = async (task) => {
    setOpenMenuId(null);
    try {
      await softDeleteTask(task.id);
      showSuccess('Task moved to Deleted Tasks');
      fetchTasks();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to delete task');
    }
  };

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

  const handleStatusChange = async (task, status) => {
    try {
      await updateTaskStatus(task.id, status);
      fetchTasks();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update status');
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
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo)] text-white flex items-center justify-center shadow-lg shadow-[var(--accent-indigo)]/20">
          <ListChecks size={20} />
        </div>
        <div>
          <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">{heading}</h1>
          <p className="text-[12px] text-[var(--text-muted)] font-bold">{subheading}</p>
        </div>
      </div>

      <StatusSummaryCards cardOrder={LIST_CARD_ORDER} summary={summary} activeKey={null} />

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
              {visibleTasks.map(task => {
                const cfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending;
                return (
                  <tr key={task.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                    <td className="px-4 py-3"><input type="checkbox" checked={selected.has(task.id)} onChange={() => toggleSelect(task.id)} /></td>
                    <td className="px-4 py-3">
                      <p className="text-[13px] font-bold text-[var(--text-main)]">{task.title}</p>
                      {task.isOverdue && <span className="text-[9px] font-black text-[var(--accent-red)] uppercase tracking-widest">Overdue</span>}
                    </td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{task.category || '—'}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{(task.assignedTo || []).map(id => userMap[id] || id).join(', ') || 'Myself'}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{task.end ? new Date(task.end).toLocaleDateString() : '—'}</td>
                    <td className="px-4 py-3">
                      {scope === 'deleted' ? (
                        <span className="px-3 py-1.5 rounded-lg text-[10px] font-black border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>{cfg.label}</span>
                      ) : (
                        <select value={task.status} onChange={e => handleStatusChange(task, e.target.value)}
                          className="px-3 py-1.5 rounded-lg text-[10px] font-black border outline-none cursor-pointer"
                          style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                          {WORKFLOW_STATUSES.map(s => <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>)}
                        </select>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {scope === 'deleted' ? (
                        <button onClick={() => handleRestore(task)} className="p-2 rounded-lg text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]" title="Restore"><RotateCcw size={14} /></button>
                      ) : task.isCreator ? (
                        <div className="flex items-center justify-end gap-1">
                          <button onClick={() => { setEditingTask(task); setModalOpen(true); }} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]" title="Edit"><Pencil size={13} /></button>
                          <button onClick={() => handleDelete(task)} className="p-2 rounded-lg text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]" title="Delete"><Trash2 size={13} /></button>
                        </div>
                      ) : null}
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
          {visibleTasks.map(task => {
            const cfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending;
            const priorityCfg = PRIORITY_CONFIG[task.priority] || PRIORITY_CONFIG.Normal;
            const counterpartLabel = scope === 'delegated'
              ? `To: ${(task.assignedTo || []).map(id => userMap[id] || id).join(', ') || '—'}`
              : `From: ${userMap[task.assignedBy] || 'Someone'}`;
            return (
              <motion.div key={task.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl px-4 py-3.5 hover:shadow-md transition-all">
                {scope !== 'deleted' && (
                  <input type="checkbox" checked={selected.has(task.id)} onChange={() => toggleSelect(task.id)} className="shrink-0" />
                )}
                <div className="w-9 h-9 rounded-full flex items-center justify-center text-white font-black text-[11px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                  {getInitials(userMap[task.assignedBy] || task.title)}
                </div>

                <div className="min-w-0 flex-1 cursor-pointer" onClick={() => setDetailsTaskId(task.id)}>
                  <p className="text-[11px] font-bold text-[var(--text-muted)] truncate">
                    {counterpartLabel} <span className="text-[13px] font-black text-[var(--text-main)] ml-1">{task.title}</span>
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
                  {scope === 'deleted' ? (
                    <span className="px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-wider border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>{cfg.label}</span>
                  ) : (
                    <select value={task.status} onChange={e => handleStatusChange(task, e.target.value)} onClick={e => e.stopPropagation()}
                      className="px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-wider border outline-none cursor-pointer"
                      style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                      {WORKFLOW_STATUSES.map(s => <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>)}
                    </select>
                  )}
                  <span className="px-2.5 py-1 rounded-full text-[9px] font-black uppercase tracking-wider bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)]">
                    {formatFrequencyLabel(task.frequency)}
                  </span>
                  {task.end && (
                    <span className={`flex items-center gap-1 text-[10px] font-bold ${task.isOverdue ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>
                      <CalendarIcon size={11} /> {new Date(task.end).toLocaleDateString(undefined, { day: '2-digit', month: 'short' })}
                    </span>
                  )}
                  <span className="flex items-center gap-1 text-[10px] font-bold text-[var(--text-muted)]">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: priorityCfg.color }} /> {task.priority || 'Normal'}
                  </span>
                  <span className="text-[10px] font-bold text-[var(--text-muted)] opacity-70">{formatRelativeTime(task.end || task.start)}</span>

                  <div className="relative">
                    <button onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === task.id ? null : task.id); }}
                      className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
                      <MoreVertical size={15} />
                    </button>
                    {openMenuId === task.id && (
                      <div onClick={e => e.stopPropagation()}
                        className="absolute right-0 top-full mt-1 w-36 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-xl z-20 overflow-hidden">
                        <button onClick={() => { setDetailsTaskId(task.id); setOpenMenuId(null); }} className="w-full flex items-center gap-2 px-3 py-2.5 text-[11px] font-bold text-[var(--text-main)] hover:bg-[var(--input-bg)]">
                          <Info size={13} /> Details
                        </button>
                        {scope === 'deleted' ? (
                          <button onClick={() => handleRestore(task)} className="w-full flex items-center gap-2 px-3 py-2.5 text-[11px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--input-bg)]">
                            <RotateCcw size={13} /> Restore
                          </button>
                        ) : task.isCreator ? (
                          <>
                            <button onClick={() => { setEditingTask(task); setModalOpen(true); setOpenMenuId(null); }} className="w-full flex items-center gap-2 px-3 py-2.5 text-[11px] font-bold text-[var(--text-main)] hover:bg-[var(--input-bg)]">
                              <Pencil size={13} /> Edit
                            </button>
                            <button onClick={() => handleDelete(task)} className="w-full flex items-center gap-2 px-3 py-2.5 text-[11px] font-bold text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]">
                              <Trash2 size={13} /> Delete
                            </button>
                          </>
                        ) : null}
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}

      <TaskFormModal isOpen={modalOpen} onClose={() => setModalOpen(false)} task={editingTask} onSaved={fetchTasks} categories={categories} tags={tagOptions} />
      <TaskDetailsModal isOpen={!!detailsTaskId} taskId={detailsTaskId} onClose={() => setDetailsTaskId(null)} onChanged={fetchTasks} />
    </div>
  );
};

export default TaskListView;
