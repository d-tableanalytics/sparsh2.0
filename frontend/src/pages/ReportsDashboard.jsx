import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import {
  CalendarDays, Users, Download, ChevronDown, FileDown, FileSpreadsheet, FileText, RotateCcw,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import FilterDropdown from '../components/reports/FilterDropdown';
import SummaryCards from '../components/reports/SummaryCards';
import CompanyTable from '../components/reports/CompanyTable';
import EmployeeTable from '../components/reports/EmployeeTable';
import LmsReport from '../components/reports/LmsReport';
import { PERIOD_OPTIONS, rangeParams } from '../components/reports/reportPeriods';
import { getDepartmentsReport, exportReport } from '../services/reportApi';

const PILLS = ['today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month'];

// Calendar-wise Report: sticky filters → summary cards → expandable company table →
// employee table (expand → task details). Tables only, no charts. Superadmin + Admin.
const ReportsDashboard = () => {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [reportType, setReportType] = useState('calendar'); // 'calendar' | 'lms'
  const [period, setPeriod] = useState('this_month');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [department, setDepartment] = useState('');
  const [departments, setDepartments] = useState([]);
  const [expandedCompany, setExpandedCompany] = useState(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState('');
  const exportRef = useRef(null);

  const baseParams = useMemo(() => {
    const p = { ...rangeParams(period, startDate, endDate) };
    if (department) p.department = department;
    return p;
  }, [period, startDate, endDate, department]);

  const loadDepartments = useCallback(async () => {
    try {
      const res = await getDepartmentsReport(rangeParams(period, startDate, endDate));
      setDepartments((res.departments || []).map((d) => d.name).filter(Boolean));
    } catch (e) { /* handled globally */ }
  }, [period, startDate, endDate]);

  useEffect(() => { loadDepartments(); }, [loadDepartments]);
  useEffect(() => { setExpandedCompany(null); }, [period, startDate, endDate, department]);

  useEffect(() => {
    if (!exportOpen) return undefined;
    const h = (e) => { if (exportRef.current && !exportRef.current.contains(e.target)) setExportOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [exportOpen]);

  if (user && !['superadmin', 'admin'].includes(user.role)) return <Navigate to="/" replace />;

  const reset = () => { setPeriod('this_month'); setStartDate(''); setEndDate(''); setDepartment(''); };

  const doExport = async (format) => {
    setExportOpen(false); setExporting(format);
    try { await exportReport({ format, ...baseParams }); }
    catch (e) { /* handled globally */ }
    finally { setExporting(''); }
  };

  const pillCls = (active) => `px-3.5 py-2 rounded-xl text-[11px] font-black uppercase tracking-wider transition-all ${
    active ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)] hover:text-[var(--text-main)]'
  }`;

  return (
    <div className="space-y-5 pb-16">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-black text-[var(--text-main)] tracking-tight">Reports &amp; Analytics</h1>
          <div className="inline-flex items-center gap-1 mt-2 bg-[var(--input-bg)] border border-[var(--border)] p-1 rounded-xl">
            {[['calendar', 'Calendar-wise Report'], ['lms', 'LMS-wise Report']].map(([v, label]) => (
              <button key={v} onClick={() => setReportType(v)}
                className={`px-4 py-2 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${
                  reportType === v ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
                }`}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="relative" ref={exportRef}>
          <button onClick={() => setExportOpen((o) => !o)} disabled={!!exporting}
            className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all disabled:opacity-50">
            <Download size={14} /> {exporting ? 'Exporting…' : 'Export'} <ChevronDown size={13} className={`transition-transform ${exportOpen ? 'rotate-180' : ''}`} />
          </button>
          {exportOpen && (
            <div className="absolute right-0 mt-2 w-40 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-lg z-50 overflow-hidden">
              {[['xlsx', 'Excel', FileSpreadsheet], ['pdf', 'PDF', FileText], ['csv', 'CSV', FileDown]].map(([fmt, label, Icon]) => (
                <button key={fmt} onClick={() => doExport(fmt)} className="w-full flex items-center gap-2 px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] transition-all">
                  <Icon size={14} /> {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Sticky filters */}
      <div className="sticky top-0 z-30 -mx-4 sm:-mx-6 px-4 sm:px-6 py-3 bg-[var(--bg-main)]/95 backdrop-blur border-y border-[var(--border)]">
        <div className="flex flex-wrap items-center gap-2">
          {PILLS.map((p) => (
            <button key={p} onClick={() => setPeriod(p)} className={pillCls(period === p)}>
              {(PERIOD_OPTIONS.find((o) => o.value === p) || {}).label}
            </button>
          ))}
          <button onClick={() => setPeriod('custom')} className={pillCls(period === 'custom')}>
            <CalendarDays size={12} className="inline mr-1 -mt-0.5" /> Custom Range
          </button>
          {period === 'custom' && (
            <div className="flex items-center gap-2">
              <input type="date" value={startDate} max={endDate || undefined} onChange={(e) => setStartDate(e.target.value)}
                className="px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl text-[12px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]" />
              <span className="text-[11px] font-black text-[var(--text-muted)]">to</span>
              <input type="date" value={endDate} min={startDate || undefined} onChange={(e) => setEndDate(e.target.value)}
                className="px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl text-[12px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]" />
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            <FilterDropdown value={department} onChange={setDepartment} icon={Users} align="right"
              placeholder="All Departments"
              options={[{ value: '', label: 'All Departments' }, ...departments.map((d) => ({ value: d, label: d }))]} />
            <button onClick={reset} title="Reset filters"
              className="flex items-center gap-1.5 px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] transition-all">
              <RotateCcw size={13} /> Reset
            </button>
          </div>
        </div>
      </div>

      {reportType === 'lms' ? (
        <LmsReport params={baseParams} />
      ) : (
        <>
          {/* Summary KPI cards (period-scoped, no charts) */}
          <SummaryCards params={baseParams} />

          {/* Company-wise report (expand → employee table) */}
          <CompanyTable params={baseParams} expandedId={expandedCompany?.id} onToggle={setExpandedCompany} />

          {expandedCompany && (
            <EmployeeTable company={expandedCompany} params={baseParams} onOpenEmployee={(id) => navigate(`/admin/reports/employee/${id}`)} />
          )}
        </>
      )}
    </div>
  );
};

export default ReportsDashboard;
