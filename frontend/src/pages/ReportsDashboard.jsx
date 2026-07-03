import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Users, ListTodo, CheckCircle2, Building2, Briefcase, GraduationCap,
  CalendarDays, Layers, BookOpen, Clock, Percent, Award, Search,
  RefreshCw, ArrowUpDown, FileDown, FileSpreadsheet, FileText, ChevronRight,
  Download, ChevronDown,
} from 'lucide-react';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell, Legend,
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import {
  getEnterpriseOverview, getCompanyReport, getDoers, getCompanies, getLmsList, exportReport,
} from '../services/reportApi';
import CompanyPanel from '../components/reports/CompanyPanel';
import LmsPanel from '../components/reports/LmsPanel';
import LmsListPanel from '../components/reports/LmsListPanel';
import FilterDropdown from '../components/reports/FilterDropdown';
import { truncate } from '../components/reports/chartKit';

const PERIODS = [
  { value: 'all_time', label: 'All Time' },
  { value: 'today', label: 'Today' },
  { value: 'this_week', label: 'This Week' },
  { value: 'this_month', label: 'This Month' },
  { value: 'this_year', label: 'This Year' },
  { value: 'custom', label: 'Custom Range' },
];

const tooltipStyle = {
  borderRadius: '16px', border: '1px solid var(--border)',
  background: 'var(--bg-card)', boxShadow: '0 20px 50px rgba(0,0,0,0.12)', padding: '10px 16px',
};

const ChartCard = ({ title, subtitle, children, className = '' }) => (
  <div className={`bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm flex flex-col ${className}`}>
    <div className="mb-4">
      <h3 className="text-lg font-black text-[var(--text-main)] uppercase italic tracking-tight">{title}</h3>
      {subtitle && <p className="text-[11px] text-[var(--text-muted)] font-bold uppercase tracking-wider opacity-60">{subtitle}</p>}
    </div>
    <div className="flex-1 w-full min-h-0 min-w-0">{children}</div>
  </div>
);

const KPI = ({ label, value, icon: Icon, delay }) => (
  <motion.div
    initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay }}
    className="bg-[var(--bg-card)] p-5 rounded-3xl border border-[var(--border)] shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all group"
  >
    <div className="flex items-start justify-between mb-3">
      <div className="p-2.5 rounded-2xl bg-[var(--input-bg)] text-[var(--text-main)] group-hover:bg-[var(--accent-indigo-bg)] group-hover:text-[var(--accent-indigo)] transition-colors">
        <Icon size={20} />
      </div>
    </div>
    <h3 className="text-2xl font-black text-[var(--text-main)]">{value ?? '—'}</h3>
    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider mt-1">{label}</p>
  </motion.div>
);

const RATING_COLOR = {
  Excellent: 'var(--accent-green)', Good: 'var(--accent-indigo)',
  Average: 'var(--accent-orange)', 'Needs Attention': 'var(--accent-red)',
};

const ReportsDashboard = () => {
  const { user } = useAuth();
  const { showError } = useNotification();
  const navigate = useNavigate();

  const [viewMode, setViewMode] = useState('company'); // 'company' | 'lms'
  const [period, setPeriod] = useState('this_month');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [department, setDepartment] = useState('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('score');
  const [order, setOrder] = useState('desc');
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 10;

  const [enterprise, setEnterprise] = useState(null);
  const [company, setCompany] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [selectedCompanyId, setSelectedCompanyId] = useState('');
  const [lmsList, setLmsList] = useState([]);
  const [selectedLmsId, setSelectedLmsId] = useState('');
  const [doers, setDoers] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState('');
  const [exportOpen, setExportOpen] = useState(false);
  const exportRef = useRef(null);

  // Close the export dropdown on outside click
  useEffect(() => {
    if (!exportOpen) return undefined;
    const handler = (e) => {
      if (exportRef.current && !exportRef.current.contains(e.target)) setExportOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [exportOpen]);

  // Custom range: expand the picked dates to full-day ISO bounds so same-day
  // items are included (task `start` is a full datetime string).
  const customStart = period === 'custom' && startDate ? `${startDate}T00:00:00` : undefined;
  const customEnd = period === 'custom' && endDate ? `${endDate}T23:59:59` : undefined;

  const baseParams = useMemo(() => {
    const p = { period };
    if (department) p.department = department;
    if (selectedLmsId) p.lms = selectedLmsId;
    if (period === 'custom' && customStart && customEnd) {
      p.startDate = customStart;
      p.endDate = customEnd;
    }
    return p;
  }, [period, department, selectedLmsId, customStart, customEnd]);

  const fetchTopLevel = useCallback(async () => {
    try {
      const [ov, co] = await Promise.all([
        getEnterpriseOverview(baseParams),
        getCompanyReport(baseParams),
      ]);
      setEnterprise(ov);
      setCompany(co);
    } catch (err) {
      console.error('Reports fetch error:', err);
      showError('Failed to load reports');
    }
  }, [baseParams, showError]);

  const fetchDoers = useCallback(async () => {
    try {
      const res = await getDoers({ ...baseParams, search, sort, order, skip: page * PAGE_SIZE, limit: PAGE_SIZE });
      setDoers(res);
    } catch (err) {
      console.error('Doers fetch error:', err);
    }
  }, [baseParams, search, sort, order, page]);

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchTopLevel(), fetchDoers()]).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseParams]);

  useEffect(() => { fetchDoers(); /* eslint-disable-next-line */ }, [search, sort, order, page]);

  // Reset to first page when filters change
  useEffect(() => { setPage(0); }, [period, department, search, customStart, customEnd]);

  // Company list for the drill-down selector (loaded once)
  useEffect(() => {
    getCompanies({ limit: 500 }).then((r) => setCompanies(r.items || [])).catch(() => {});
  }, []);

  // LMS (batch) list — cascades off the selected company; reset LMS when company changes
  useEffect(() => {
    setSelectedLmsId('');
    const params = { limit: 500, ...(selectedCompanyId ? { company_id: selectedCompanyId } : {}) };
    getLmsList(params).then((r) => setLmsList(r.items || [])).catch(() => setLmsList([]));
  }, [selectedCompanyId]);

  const departments = company?.departments || [];
  const topPerformers = useMemo(
    () => (company?.departments ? [...(doers.items || [])] : []).slice(0, 8)
      .map((d) => ({ name: d.name?.split(' ')[0] || d.name, score: d.score })),
    [company, doers.items]
  );

  const handleSort = (key) => {
    if (sort === key) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    else { setSort(key); setOrder('desc'); }
  };

  const doExport = async (format) => {
    setExporting(format);
    try {
      await exportReport({ format, ...baseParams });
    } catch (err) {
      showError('Export failed');
    } finally {
      setExporting('');
    }
  };

  // Admin page guard (defence in depth; sidebar already hides the link).
  if (user && !['superadmin', 'admin'].includes(user.role)) return <Navigate to="/" replace />;

  const kpis = [
    { label: 'Total Companies', value: enterprise?.totalCompanies, icon: Building2 },
    { label: 'Total Users', value: enterprise?.totalUsers, icon: Users },
    { label: 'Total Coaches', value: enterprise?.totalCoaches, icon: Briefcase },
    { label: 'Total Learners', value: enterprise?.totalLearners, icon: GraduationCap },
    { label: 'Total Sessions', value: enterprise?.totalSessions, icon: CalendarDays },
    { label: 'Total Tasks', value: enterprise?.totalTasks, icon: ListTodo },
    { label: 'Completed Tasks', value: enterprise?.completedTasks, icon: CheckCircle2 },
    { label: 'Pending Tasks', value: enterprise?.pendingTasks, icon: Clock },
    { label: 'Active Batches', value: enterprise?.activeBatches, icon: Layers },
    { label: 'Active Courses', value: enterprise?.activeCourses, icon: BookOpen },
    { label: 'Avg Performance', value: enterprise?.avgPerformanceScore, icon: Award },
    { label: 'Completion Rate', value: enterprise ? `${enterprise.completionRate}%` : null, icon: Percent },
  ];

  return (
    <div className="space-y-8 pb-16">
      {/* Header + filters */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">Reports & Analytics</h1>
          <p className="text-[14px] text-[var(--text-muted)] font-bold">Company and employee performance across all tasks.</p>
          {/* Report type switch */}
          <div className="inline-flex items-center gap-1 mt-3 bg-[var(--input-bg)] border border-[var(--border)] p-1 rounded-xl">
            {[['company', 'Company Wise'], ['lms', 'LMS Wise']].map(([v, label]) => (
              <button
                key={v}
                onClick={() => { setViewMode(v); if (v === 'company') setSelectedLmsId(''); }}
                className={`px-4 py-2 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${
                  viewMode === v ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          {/* LMS filter — only in LMS-wise mode (shown first, per spec) */}
          {viewMode === 'lms' && (
            <FilterDropdown
              value={selectedLmsId}
              onChange={setSelectedLmsId}
              icon={Layers}
              optionIcon={Layers}
              searchable
              placeholder="All LMS"
              searchPlaceholder="Search LMS..."
              options={[{ value: '', label: 'All LMS' }, ...lmsList.map((l) => ({ value: l.id, label: l.name, sublabel: l.companyCount === 1 ? l.company : undefined }))]}
            />
          )}
          <FilterDropdown
            value={selectedCompanyId}
            onChange={setSelectedCompanyId}
            icon={Building2}
            optionIcon={Building2}
            searchable
            placeholder="All Companies"
            searchPlaceholder="Search company..."
            options={[{ value: '', label: 'All Companies' }, ...companies.map((c) => ({ value: c.id, label: c.name }))]}
          />
          <FilterDropdown
            value={period}
            onChange={setPeriod}
            icon={CalendarDays}
            options={PERIODS}
          />
          {period === 'custom' && (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={startDate}
                max={endDate || undefined}
                onChange={(e) => setStartDate(e.target.value)}
                className="px-3 py-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-sm text-[13px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]"
              />
              <span className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">to</span>
              <input
                type="date"
                value={endDate}
                min={startDate || undefined}
                onChange={(e) => setEndDate(e.target.value)}
                className="px-3 py-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-sm text-[13px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]"
              />
            </div>
          )}
          <FilterDropdown
            value={department}
            onChange={setDepartment}
            icon={Users}
            optionIcon={GraduationCap}
            align="right"
            placeholder="All Departments"
            options={[{ value: '', label: 'All Departments' }, ...departments.map((d) => ({ value: d.name, label: d.name }))]}
          />
          <button onClick={() => { fetchTopLevel(); fetchDoers(); }} title="Refresh"
            className="p-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-all">
            <RefreshCw size={15} />
          </button>
          {/* Single Export dropdown — reuses doExport('csv'|'xlsx'|'pdf') unchanged */}
          <div className="relative" ref={exportRef}>
            <button onClick={() => setExportOpen((o) => !o)} disabled={!!exporting} title="Export"
              className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all disabled:opacity-50">
              <Download size={14} /> {exporting ? 'Exporting…' : 'Export'}
              <ChevronDown size={13} className={`transition-transform ${exportOpen ? 'rotate-180' : ''}`} />
            </button>
            {exportOpen && (
              <div className="absolute right-0 mt-2 w-40 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-lg z-50 overflow-hidden">
                {[['csv', 'CSV', FileDown], ['xlsx', 'Excel', FileSpreadsheet], ['pdf', 'PDF', FileText]].map(([fmt, label, Icon]) => (
                  <button key={fmt} onClick={() => { setExportOpen(false); doExport(fmt); }} disabled={!!exporting}
                    className="w-full flex items-center gap-2 px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] transition-all disabled:opacity-50">
                    <Icon size={14} /> {label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {viewMode === 'lms' ? (
        selectedLmsId ? (
          <LmsPanel
            batchId={selectedLmsId}
            period={period}
            startDate={customStart}
            endDate={customEnd}
            onOpenEmployee={(id) => navigate(`/admin/reports/employee/${id}`)}
          />
        ) : (
          <LmsListPanel companyId={selectedCompanyId} onSelect={setSelectedLmsId} />
        )
      ) : selectedCompanyId ? (
        <CompanyPanel
          companyId={selectedCompanyId}
          period={period}
          startDate={customStart}
          endDate={customEnd}
          onOpenEmployee={(id) => navigate(`/admin/reports/employee/${id}`)}
        />
      ) : (
      <>
      {/* Executive KPI cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-4">
        {kpis.map((k, i) => <KPI key={k.label} {...k} delay={i * 0.03} />)}
      </div>

      {/* Learning & engagement strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPI label="Avg Assessment Score" value={enterprise ? `${enterprise.avgAssessmentScore}%` : null} icon={Award} delay={0.02} />
        <KPI label="Attendance Rate" value={enterprise ? `${enterprise.attendanceRate}%` : null} icon={CalendarDays} delay={0.04} />
        <KPI label="Avg Task Completion" value={enterprise ? `${enterprise.completionRate}%` : null} icon={Percent} delay={0.06} />
        <KPI label="Performance Index" value={enterprise?.avgPerformanceScore} icon={Award} delay={0.08} />
      </div>

      {/* Company charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        <ChartCard title="Monthly Completion" subtitle="Assigned vs Completed" className="md:col-span-2 xl:col-span-2 h-[360px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={company?.monthly || []}>
              <defs>
                <linearGradient id="rpCompleted" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--accent-green)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--accent-green)" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="rpAssigned" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--accent-indigo)" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="var(--accent-indigo)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
              <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10, fontWeight: 900 }} dy={8} />
              <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10, fontWeight: 900 }} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '10px', fontWeight: 900, textTransform: 'uppercase' }} />
              <Area type="monotone" dataKey="assigned" stroke="var(--accent-indigo)" strokeWidth={3} fill="url(#rpAssigned)" animationDuration={1200} />
              <Area type="monotone" dataKey="completed" stroke="var(--accent-green)" strokeWidth={3} fill="url(#rpCompleted)" animationDuration={1400} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Status Distribution" subtitle="All tasks by workflow state" className="h-[360px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={company?.statusDistribution || []} innerRadius={60} outerRadius={95} paddingAngle={6} dataKey="value" stroke="none" animationDuration={1400}>
                {(company?.statusDistribution || []).map((e, i) => <Cell key={i} fill={e.color} />)}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '9px', fontWeight: 900, textTransform: 'uppercase' }} />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        <ChartCard title="Department Comparison" subtitle="Completed vs Pending by department" className="md:col-span-2 xl:col-span-2 h-[340px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={departments} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
              <XAxis dataKey="name" tick={{ fontSize: 9, fill: 'var(--text-muted)', fontWeight: 800 }} interval="preserveStartEnd" tickFormatter={(v) => truncate(v, 10)} />
              <YAxis tick={{ fontSize: 9, fill: 'var(--text-muted)' }} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '10px', fontWeight: 900, textTransform: 'uppercase' }} />
              <Bar dataKey="completed" stackId="a" fill="var(--accent-green)" />
              <Bar dataKey="pending" stackId="a" fill="var(--accent-orange)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Priority Mix" subtitle="Tasks by priority" className="h-[340px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={company?.priorityDistribution || []} innerRadius={55} outerRadius={90} paddingAngle={6} dataKey="value" stroke="none" animationDuration={1400}>
                {(company?.priorityDistribution || []).map((e, i) => <Cell key={i} fill={e.color} />)}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '9px', fontWeight: 900, textTransform: 'uppercase' }} />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <ChartCard title="Company Growth Trend" subtitle="Cumulative tasks over time" className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={company?.monthly || []}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
              <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10, fontWeight: 900 }} dy={8} />
              <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10, fontWeight: 900 }} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="cumulative" stroke="var(--accent-indigo)" strokeWidth={3} dot={{ r: 3 }} animationDuration={1400} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Top Performers" subtitle="By productivity score" className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={topPerformers} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" opacity={0.3} />
              <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 9, fill: 'var(--text-muted)' }} />
              <YAxis type="category" dataKey="name" width={90} tickFormatter={truncate} tick={{ fontSize: 10, fill: 'var(--text-muted)', fontWeight: 800 }} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'var(--input-bg)' }} />
              <Bar dataKey="score" fill="var(--accent-indigo)" radius={[0, 6, 6, 0]} animationDuration={1200} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* Doer performance table */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] overflow-hidden shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-[var(--border)]">
          <div>
            <h3 className="text-lg font-black text-[var(--text-main)] uppercase italic tracking-tight">Employee Performance</h3>
            <p className="text-[11px] text-[var(--text-muted)] font-bold uppercase tracking-wider opacity-60">Ranked by score — click a row for the full report</p>
          </div>
          <div className="relative min-w-[220px]">
            <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search employee..."
              className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[880px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                {[
                  ['rank', '#'], ['name', 'Employee'], ['department', 'Dept'],
                  ['assigned', 'Assigned'], ['completed', 'Completed'], ['pending', 'Pending'],
                  ['overdue', 'Overdue'], ['completionRate', 'Completion %'], ['avgCompletionDays', 'Avg Days'],
                  ['score', 'Score'], ['rating', 'Rating'],
                ].map(([key, label]) => (
                  <th key={key} onClick={() => handleSort(key)}
                    className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest cursor-pointer select-none hover:text-[var(--text-main)]">
                    <span className="inline-flex items-center gap-1">{label}{sort === key && <ArrowUpDown size={11} />}</span>
                  </th>
                ))}
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={12} className="px-4 py-12 text-center text-[12px] font-bold text-[var(--text-muted)]">Loading…</td></tr>
              ) : (doers.items || []).length === 0 ? (
                <tr><td colSpan={12} className="px-4 py-12 text-center text-[12px] font-bold text-[var(--text-muted)]">No employees with tasks in this period.</td></tr>
              ) : (
                doers.items.map((d) => (
                  <tr key={d.id} onClick={() => navigate(`/admin/reports/employee/${d.id}`)}
                    className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors cursor-pointer">
                    <td className="px-4 py-3 text-[13px] font-black text-[var(--text-muted)]">{d.rank}</td>
                    <td className="px-4 py-3">
                      <p className="text-[13px] font-bold text-[var(--text-main)]">{d.name}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">{d.email}</p>
                    </td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{d.department}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{d.assigned}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-green)]">{d.completed}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-orange)]">{d.pending}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-red)]">{d.overdue}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{d.completionRate}%</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-muted)]">{d.avgCompletionDays ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span className="text-[14px] font-black" style={{ color: RATING_COLOR[d.rating] }}>{d.score}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider"
                        style={{ color: RATING_COLOR[d.rating], background: 'var(--input-bg)' }}>{d.rating}</span>
                    </td>
                    <td className="px-4 py-3 text-[var(--text-muted)]"><ChevronRight size={16} /></td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {doers.total > PAGE_SIZE && (
          <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
            <p className="text-[11px] font-bold text-[var(--text-muted)]">
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, doers.total)} of {doers.total}
            </p>
            <div className="flex items-center gap-2">
              <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40 hover:text-[var(--text-main)]">Prev</button>
              <button disabled={(page + 1) * PAGE_SIZE >= doers.total} onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40 hover:text-[var(--text-main)]">Next</button>
            </div>
          </div>
        )}
      </div>
      </>
      )}
    </div>
  );
};

export default ReportsDashboard;
