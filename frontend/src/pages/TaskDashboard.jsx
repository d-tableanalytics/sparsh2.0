import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Table2, BarChart3 as BarChartIcon, Plus, ListChecks, Search } from 'lucide-react';
import api from '../services/api';
import { getTaskDashboard, getTasks } from '../services/taskApi';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import DateRangeFilter from '../components/tasks/DateRangeFilter';
import TaskFormModal from '../components/tasks/TaskFormModal';
import StatusSummaryCards from '../components/tasks/StatusSummaryCards';
import StackedReportPanel from '../components/tasks/StackedReportPanel';
import { SUMMARY_CARD_ORDER, STATUS_CONFIG, CARD_KEY_TO_STATUS } from '../components/tasks/statusConfig';

const ADMIN_ROLES = ['superadmin', 'admin', 'coach', 'staff'];

// Every task falls into exactly one of these 4 buckets for the stacked "X Wise" report
// panels — keeps the stacked bar segments mutually exclusive (no double-counting).
const bucketOf = (t) => {
  if (t.isOverdue) return 'overdue';
  if (t.status === 'completed') return 'completed';
  if (t.status === 'in_progress') return 'inProgress';
  return 'pending';
};

const TABS = [
  { key: 'employees', label: 'Employees', groupBy: 'assignee' },
  { key: 'groups', label: 'Groups', groupBy: 'category' }, // no distinct "group" entity in the data model yet; grouped by category as the nearest analog
  { key: 'my_report', label: 'My Report', scope: 'my' },
  { key: 'delegated', label: 'Delegated', scope: 'delegated' },
  { key: 'daily', label: 'Daily', groupBy: 'day' },
  { key: 'monthly', label: 'Monthly' },
  { key: 'overdue', label: 'Overdue', scope: 'all', filterOverdue: true },
  { key: 'tags', label: 'Tags', groupBy: 'tags' },
  { key: 'categories', label: 'Categories', groupBy: 'category' },
];

const emptyFilters = { assignedTo: '', category: '', tag: '', frequency: '' };

const TaskDashboard = () => {
  const { user } = useAuth();
  const { showError } = useNotification();
  const [period, setPeriod] = useState('this_month');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [filters, setFilters] = useState(emptyFilters);
  const [search, setSearch] = useState('');
  const [activeCardKey, setActiveCardKey] = useState(null);
  const activeStatus = activeCardKey === 'overdue' ? 'overdue' : (CARD_KEY_TO_STATUS[activeCardKey] || null);
  const [activeTab, setActiveTab] = useState('monthly');
  const [viewType, setViewType] = useState('table');

  const [users, setUsers] = useState([]);
  const [dashboard, setDashboard] = useState({ summary: null, monthly: [] });
  const [tabTasks, setTabTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    api.get('/users?active_only=true').then(res => setUsers(res.data || [])).catch(() => {});
  }, []);

  const userMap = useMemo(() => {
    const m = {};
    users.forEach(u => { m[u._id] = u.full_name || u.email; });
    return m;
  }, [users]);

  const queryParams = useMemo(() => ({
    period,
    startDate: period === 'custom' ? startDate : undefined,
    endDate: period === 'custom' ? endDate : undefined,
    assignedTo: filters.assignedTo || undefined,
    category: filters.category || undefined,
    tag: filters.tag || undefined,
    frequency: filters.frequency || undefined,
    search: search || undefined,
  }), [period, startDate, endDate, filters, search]);

  const tab = TABS.find(t => t.key === activeTab);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const dashRes = await getTaskDashboard({ ...queryParams, viewType, reportType: activeTab });
      setDashboard(dashRes.data);

      if (activeTab !== 'monthly') {
        const listRes = await getTasks({ ...queryParams, scope: tab.scope || 'all' });
        setTabTasks(listRes.data || []);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load dashboard');
      showError(err.response?.data?.detail || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryParams, viewType, activeTab]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const categories = useMemo(() => {
    const set = new Set();
    tabTasks.forEach(t => t.category && set.add(t.category));
    return Array.from(set);
  }, [tabTasks]);

  const tags = useMemo(() => {
    const set = new Set();
    tabTasks.forEach(t => (t.tags || []).forEach(tg => set.add(tg)));
    return Array.from(set);
  }, [tabTasks]);

  const clearFilters = () => {
    setFilters(emptyFilters);
    setSearch('');
    setActiveCardKey(null);
  };

  // ─── Grouped rows for Employees / Groups / Daily / Tags / Categories tabs ───
  const groupedRows = useMemo(() => {
    if (!tab?.groupBy) return [];
    let source = tabTasks;
    if (tab.filterOverdue) source = source.filter(t => t.isOverdue);
    if (activeStatus) source = source.filter(t => t.status === activeStatus || (activeStatus === 'overdue' && t.isOverdue));

    const groupByFn = (t) => {
      if (tab.groupBy === 'assignee') return (t.assignedTo?.length ? t.assignedTo.map(id => userMap[id] || id) : ['Unassigned']);
      if (tab.groupBy === 'category') return [t.category || 'Uncategorized'];
      if (tab.groupBy === 'tags') return (t.tags?.length ? t.tags : ['Untagged']);
      if (tab.groupBy === 'day') return [t.start ? new Date(t.start).toLocaleDateString() : 'No Date'];
      return ['—'];
    };

    const map = new Map();
    source.forEach(t => {
      groupByFn(t).forEach(key => {
        if (!map.has(key)) map.set(key, { label: key, total: 0, pending: 0, inProgress: 0, completed: 0, overdue: 0 });
        const row = map.get(key);
        row.total += 1;
        if (t.status === 'pending') row.pending += 1;
        if (t.status === 'in_progress') row.inProgress += 1;
        if (t.status === 'completed') row.completed += 1;
        if (t.isOverdue) row.overdue += 1;
      });
    });
    return Array.from(map.values()).sort((a, b) => b.total - a.total);
  }, [tab, tabTasks, activeStatus, userMap]);

  // Flat task rows for My Report / Delegated / Overdue tabs
  const flatRows = useMemo(() => {
    if (tab?.groupBy) return [];
    let rows = tabTasks;
    if (tab?.filterOverdue) rows = rows.filter(t => t.isOverdue);
    if (activeStatus) rows = rows.filter(t => t.status === activeStatus || (activeStatus === 'overdue' && t.isOverdue));
    return rows;
  }, [tab, tabTasks, activeStatus]);

  // ─── Bar Chart view: multi-panel stacked reports (Employee/Category/Daily/Monthly/Delegated) ───
  const isAdminRole = ADMIN_ROLES.includes(user?.role?.toLowerCase());
  const [chartAllTasks, setChartAllTasks] = useState([]);
  const [chartDelegatedTasks, setChartDelegatedTasks] = useState([]);
  const [chartLoading, setChartLoading] = useState(false);

  useEffect(() => {
    if (viewType !== 'chart') return;
    let cancelled = false;
    setChartLoading(true);
    Promise.all([
      getTasks({ ...queryParams, scope: isAdminRole ? 'all' : 'my' }),
      getTasks({ ...queryParams, scope: 'delegated' }),
    ]).then(([allRes, delRes]) => {
      if (cancelled) return;
      setChartAllTasks(allRes.data || []);
      setChartDelegatedTasks(delRes.data || []);
    }).catch(() => { if (!cancelled) showError('Failed to load chart reports'); })
      .finally(() => { if (!cancelled) setChartLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewType, queryParams, isAdminRole]);

  const groupStacked = (tasks, labelFn) => {
    const map = new Map();
    tasks.forEach(t => {
      const label = labelFn(t);
      if (!label) return;
      if (!map.has(label)) map.set(label, { label, pending: 0, overdue: 0, inProgress: 0, completed: 0, total: 0, sortKey: label });
      const row = map.get(label);
      row[bucketOf(t)] += 1;
      row.total += 1;
    });
    return map;
  };

  const employeeRows = useMemo(() => {
    const map = groupStacked(chartAllTasks, t => (t.assignedTo?.length ? (userMap[t.assignedTo[0]] || 'Unknown') : 'Myself'));
    return Array.from(map.values()).sort((a, b) => b.total - a.total);
  }, [chartAllTasks, userMap]);

  const categoryRows = useMemo(() => {
    const map = groupStacked(chartAllTasks, t => t.category || 'Uncategorized');
    return Array.from(map.values()).sort((a, b) => b.total - a.total);
  }, [chartAllTasks]);

  const dailyRows = useMemo(() => {
    const map = new Map();
    chartAllTasks.forEach(t => {
      if (!t.start) return;
      const d = new Date(t.start);
      const key = d.toISOString().slice(0, 10);
      if (!map.has(key)) map.set(key, { label: d.toLocaleDateString(undefined, { day: '2-digit', month: 'long', year: 'numeric' }), sortKey: key, pending: 0, overdue: 0, inProgress: 0, completed: 0, total: 0 });
      const row = map.get(key);
      row[bucketOf(t)] += 1;
      row.total += 1;
    });
    return Array.from(map.values()).sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  }, [chartAllTasks]);

  const monthlyChartRows = useMemo(() => {
    const map = new Map();
    chartAllTasks.forEach(t => {
      if (!t.start) return;
      const d = new Date(t.start);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      if (!map.has(key)) map.set(key, { label: d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' }), sortKey: key, pending: 0, overdue: 0, inProgress: 0, completed: 0, total: 0 });
      const row = map.get(key);
      row[bucketOf(t)] += 1;
      row.total += 1;
    });
    return Array.from(map.values()).sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  }, [chartAllTasks]);

  const delegatedChartRows = useMemo(() => {
    const map = groupStacked(chartDelegatedTasks, t => (t.assignedTo?.length ? (userMap[t.assignedTo[0]] || 'Unknown') : 'Unassigned'));
    return Array.from(map.values()).sort((a, b) => b.total - a.total);
  }, [chartDelegatedTasks, userMap]);

  return (
    <div className="space-y-6 pb-24">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">Task Dashboard</h1>
          <p className="text-[13px] text-[var(--text-muted)] font-bold">Organization task performance overview</p>
        </div>
      </div>

      <DateRangeFilter
        period={period}
        onPeriodChange={setPeriod}
        startDate={startDate}
        endDate={endDate}
        onCustomChange={(field, value) => (field === 'startDate' ? setStartDate(value) : setEndDate(value))}
      />

      {/* ─── Summary Cards ─── */}
      <StatusSummaryCards
        cardOrder={SUMMARY_CARD_ORDER}
        summary={dashboard.summary}
        activeKey={activeCardKey}
        onSelect={(key) => setActiveCardKey(prev => (prev === key ? null : key))}
        columnsClass="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-4"
      />

      {/* ─── Filters ─── */}
      <div className="flex flex-wrap items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4">
        <div className="relative flex-1 min-w-[180px]">
          <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search tasks..."
            className="w-full pl-10 pr-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        </div>
        <select value={filters.assignedTo} onChange={e => setFilters({ ...filters, assignedTo: e.target.value })}
          className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
          <option value="">Assigned To</option>
          {users.map(u => <option key={u._id} value={u._id}>{u.full_name || u.email}</option>)}
        </select>
        <select value={filters.category} onChange={e => setFilters({ ...filters, category: e.target.value })}
          className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
          <option value="">Category</option>
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={filters.tag} onChange={e => setFilters({ ...filters, tag: e.target.value })}
          className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
          <option value="">Tag</option>
          {tags.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={filters.frequency} onChange={e => setFilters({ ...filters, frequency: e.target.value })}
          className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
          <option value="">Frequency</option>
          {['Does not repeat', 'Daily', 'Weekly', 'Monthly', 'Yearly'].map(f => <option key={f} value={f}>{f}</option>)}
        </select>
        {(search || filters.assignedTo || filters.category || filters.tag || filters.frequency || activeCardKey) && (
          <button onClick={clearFilters}
            className="px-4 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)]">
            Clear
          </button>
        )}

        <div className="ml-auto flex items-center gap-1 bg-[var(--input-bg)] border border-[var(--border)] p-1 rounded-xl">
          <button onClick={() => setViewType('table')} className={`p-2 rounded-lg transition-all ${viewType === 'table' ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)]'}`}>
            <Table2 size={16} />
          </button>
          <button onClick={() => setViewType('chart')} className={`p-2 rounded-lg transition-all ${viewType === 'chart' ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)]'}`}>
            <BarChartIcon size={16} />
          </button>
        </div>
      </div>

      {viewType === 'chart' ? (
        /* ─── Bar Chart view: one stacked-bar panel per report, all shown together ─── */
        chartLoading ? (
          <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px]">Loading reports...</div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <StackedReportPanel title="Employee Wise" axisLabel="Employee Name" rows={employeeRows} />
            <StackedReportPanel title="Category Wise" axisLabel="Category Name" rows={categoryRows} />
            <StackedReportPanel title="Daily Report" axisLabel="Date" rows={dailyRows} />
            <StackedReportPanel title="Monthly Report" axisLabel="Month" rows={monthlyChartRows} />
            <StackedReportPanel title="Delegated Tasks Report" axisLabel="Assigned To" rows={delegatedChartRows} />
          </div>
        )
      ) : (
        <>
          {/* ─── Tabs ─── */}
          <div className="flex flex-wrap bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl shadow-sm gap-1">
            {TABS.map(t => (
              <button key={t.key} onClick={() => setActiveTab(t.key)}
                className={`px-4 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${
                  activeTab === t.key ? 'bg-[var(--accent-indigo)] text-white shadow-md' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
                }`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* ─── Content ─── */}
          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] overflow-hidden shadow-sm">
            {loading ? (
              <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold">Loading dashboard...</div>
            ) : error ? (
              <div className="p-16 text-center text-[var(--accent-red)] text-[12px] font-bold">{error}</div>
            ) : activeTab === 'monthly' ? (
              dashboard.monthly.length === 0 ? (
                <div className="p-16 flex flex-col items-center justify-center text-[var(--text-muted)]">
                  <ListChecks size={40} className="mb-3 opacity-30" />
                  <p className="text-[12px] font-bold">No monthly data for the selected filters.</p>
                </div>
              ) : (
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-[var(--border)]">
                      {['Month', 'Total', 'Score', 'Overdue', 'Pending', 'In-Progress', 'In Time', 'Delayed'].map(h => (
                        <th key={h} className="px-5 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dashboard.monthly.map(row => (
                      <tr key={row.month} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                        <td className="px-5 py-3.5 text-[13px] font-bold text-[var(--text-main)]">{row.month}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{row.total}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{row.score}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-red)]">{row.overdue}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-yellow)]">{row.pending}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-indigo)]">{row.inProgress}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-green)]">{row.inTime}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-red)]">{row.delayed}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            ) : (tab?.groupBy ? groupedRows.length === 0 : flatRows.length === 0) ? (
              <div className="p-16 flex flex-col items-center justify-center text-[var(--text-muted)]">
                <ListChecks size={40} className="mb-3 opacity-30" />
                <p className="text-[12px] font-bold">No tasks found for the selected filters.</p>
              </div>
            ) : tab?.groupBy ? (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    {[tab.label.replace(/s$/, ''), 'Total', 'Pending', 'In Progress', 'Completed', 'Overdue'].map(h => (
                      <th key={h} className="px-5 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {groupedRows.map(row => (
                    <tr key={row.label} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                      <td className="px-5 py-3.5 text-[13px] font-bold text-[var(--text-main)]">{row.label}</td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{row.total}</td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-yellow)]">{row.pending}</td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-indigo)]">{row.inProgress}</td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-green)]">{row.completed}</td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-red)]">{row.overdue}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    {['Title', 'Category', 'Assigned To', 'Due', 'Status'].map(h => (
                      <th key={h} className="px-5 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {flatRows.map(t => {
                    const cfg = STATUS_CONFIG[t.status] || STATUS_CONFIG.pending;
                    return (
                      <tr key={t.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                        <td className="px-5 py-3.5">
                          <p className="text-[13px] font-bold text-[var(--text-main)]">{t.title}</p>
                          {t.isOverdue && <span className="text-[9px] font-black text-[var(--accent-red)] uppercase tracking-widest">Overdue</span>}
                        </td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{t.category || '—'}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{(t.assignedTo || []).map(id => userMap[id] || id).join(', ') || 'Myself'}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{t.end ? new Date(t.end).toLocaleDateString() : '—'}</td>
                        <td className="px-5 py-3.5">
                          <span className="px-3 py-1.5 rounded-lg text-[10px] font-black border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>{cfg.label}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      <button onClick={() => setModalOpen(true)}
        className="fixed bottom-8 right-8 w-14 h-14 rounded-full bg-[var(--accent-indigo)] text-white flex items-center justify-center shadow-2xl hover:scale-110 active:scale-95 transition-all z-40">
        <Plus size={24} />
      </button>
      <TaskFormModal isOpen={modalOpen} onClose={() => setModalOpen(false)} onSaved={fetchAll} />
    </div>
  );
};

export default TaskDashboard;
