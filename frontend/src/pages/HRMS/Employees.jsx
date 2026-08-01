import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search, UserPlus, Users, UserCheck, Clock, Building2,
  ChevronLeft, ChevronRight, X, Loader2, AlertTriangle, EyeOff,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { getEmployees, getHrmsOptions } from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { StatusBadge, Avatar, StatTile } from '../../components/hrms/hrmsUi';
import { inputCls, fmtDate } from '../../components/hrms/hrmsStyles';
import EmployeeFormModal from '../../components/hrms/EmployeeFormModal';

// HRMS ▸ Employees — the people directory.
//
// Layout follows the reference project (header ▸ KPI tiles ▸ filter bar ▸ table ▸ pagination)
// but every colour is a Sparsh CSS variable and every query is SERVER-side. The reference
// renders all rows client-side; that stops scaling past a few hundred people, so search,
// filtering, sorting and paging are all parameters on GET /hrms/employees.

const PAGE_SIZE = 25;

const Employees = () => {
  const { user } = useAuth();
  const { showError } = useNotification();
  const navigate = useNavigate();

  const canCreate = hasHrmsPermission(user, 'hrms', 'create');

  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [department, setDepartment] = useState('');
  const [status, setStatus] = useState('');
  const [includeExited, setIncludeExited] = useState(false);
  const [sort, setSort] = useState('created_desc');
  const [page, setPage] = useState(1);

  const [data, setData] = useState(null);
  const [options, setOptions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAdd, setShowAdd] = useState(false);

  // Debounce the search box so a query doesn't fire per keystroke; any change resets to page 1
  // (staying on page 6 of a narrower result set would show an empty table).
  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => { setPage(1); }, [department, status, includeExited, sort]);

  const fetchEmployees = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getEmployees({
        search: debounced || undefined,
        department: department || undefined,
        status: status || undefined,
        include_exited: includeExited || undefined,
        sort,
        page,
        limit: PAGE_SIZE,
      });
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load employees');
    } finally {
      setLoading(false);
    }
  }, [debounced, department, status, includeExited, sort, page]);

  useEffect(() => { fetchEmployees(); }, [fetchEmployees]);

  useEffect(() => {
    getHrmsOptions()
      .then((res) => setOptions(res.data))
      .catch(() => { /* pickers fall back to whatever the list returns */ });
  }, []);

  const employees = data?.employees ?? [];
  const total = data?.total ?? 0;
  const stats = data?.stats ?? { total: 0, active: 0, probation: 0, exited: 0 };
  const departments = data?.departments ?? [];
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rangeStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(page * PAGE_SIZE, total);
  const hasFilters = !!(debounced || department || status || includeExited);

  const clearFilters = () => {
    setSearch(''); setDepartment(''); setStatus(''); setIncludeExited(false);
  };

  const statuses = useMemo(() => options?.statuses ?? [], [options]);

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <Users size={20} />
          </span>
          <div>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-[var(--text-main)] leading-tight">
              Employees
            </h1>
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              People directory and records
            </p>
          </div>
        </div>
        {canCreate && (
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] transition-all"
          >
            <UserPlus size={15} /> Add Employee
          </button>
        )}
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile icon={Users} label="Total headcount" value={stats.total} loading={loading && !data} />
        <StatTile icon={UserCheck} label="Active" value={stats.active} loading={loading && !data} />
        <StatTile icon={Clock} label="Probation / notice" value={stats.probation} loading={loading && !data} />
        <StatTile icon={Building2} label="Departments" value={departments.length} loading={loading && !data} />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2.5 p-3 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, code, designation, email…"
            className={`${inputCls} pl-9`}
          />
        </div>

        <select value={department} onChange={(e) => setDepartment(e.target.value)}
          className={`${inputCls} w-auto min-w-[150px] cursor-pointer`}>
          <option value="">All departments</option>
          {departments.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>

        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className={`${inputCls} w-auto min-w-[140px] cursor-pointer`}>
          <option value="">All statuses</option>
          {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        <select value={sort} onChange={(e) => setSort(e.target.value)}
          className={`${inputCls} w-auto min-w-[150px] cursor-pointer`}>
          <option value="created_desc">Newest first</option>
          <option value="created_asc">Oldest first</option>
          <option value="name_asc">Name A–Z</option>
          <option value="name_desc">Name Z–A</option>
          <option value="joining_desc">Joined (recent)</option>
          <option value="joining_asc">Joined (earliest)</option>
        </select>

        {/* Leavers are hidden by default — the directory answers "who works here now?". */}
        <label className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--input-border)] cursor-pointer">
          <input type="checkbox" checked={includeExited}
            onChange={(e) => setIncludeExited(e.target.checked)}
            className="w-3.5 h-3.5 accent-[var(--accent-indigo)]" />
          <span className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
            Include exited
          </span>
        </label>

        {hasFilters && (
          <button onClick={clearFilters}
            className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors">
            <X size={13} /> Clear
          </button>
        )}
      </div>

      {/* Sensitive-data notice — say it plainly rather than showing blanks that read as missing data. */}
      {data && !data.sensitiveVisible && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)]">
          <EyeOff size={14} className="text-[var(--text-muted)]" />
          <span className="text-[11.5px] font-bold text-[var(--text-muted)]">
            Statutory, bank and salary details are hidden. Ask an administrator for employee-record
            permission to view them.
          </span>
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
          <table className="w-full" style={{ minWidth: 880 }}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                {['Employee', 'Code', 'Designation', 'Department', 'Joined', 'Status'].map((h) => (
                  <th key={h}
                    className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={6} className="px-4 py-14 text-center">
                    <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                      <Loader2 size={16} className="animate-spin" /> Loading employees…
                    </span>
                  </td>
                </tr>
              )}

              {!loading && employees.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-14 text-center">
                    <p className="text-[13px] font-bold text-[var(--text-main)]">No employees found.</p>
                    <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                      {hasFilters ? 'Try clearing the filters.' : 'Add your first employee to get started.'}
                    </p>
                  </td>
                </tr>
              )}

              {!loading && employees.map((e) => (
                <tr
                  key={e.employeeCode}
                  onClick={() => navigate(`/hrms/employees/${e.employeeCode}`)}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors cursor-pointer"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <Avatar name={e.fullName} photoUrl={e.photoUrl} />
                      <div className="min-w-0">
                        <div className="text-[13px] font-black text-[var(--text-main)] truncate">
                          {e.displayName || e.fullName}
                        </div>
                        <div className="text-[11.5px] font-medium text-[var(--text-muted)] truncate">
                          {e.workEmail || e.phone || '—'}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]"
                    style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {e.employeeCode}
                  </td>
                  <td className="px-4 py-3 text-[12.5px] font-semibold text-[var(--text-main)]">
                    {e.designation || '—'}
                  </td>
                  <td className="px-4 py-3 text-[12.5px] font-semibold text-[var(--text-muted)]">
                    {e.department || '—'}
                  </td>
                  <td className="px-4 py-3 text-[12.5px] font-semibold text-[var(--text-muted)]">
                    {fmtDate(e.dateOfJoining)}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={e.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {total > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-[var(--border)] bg-[var(--table-header-bg)]">
            <span className="text-[11.5px] font-bold text-[var(--text-muted)]"
              style={{ fontVariantNumeric: 'tabular-nums' }}>
              Showing {rangeStart}–{rangeEnd} of {total}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40 disabled:cursor-not-allowed hover:text-[var(--text-main)] transition-colors"
                aria-label="Previous page"
              >
                <ChevronLeft size={15} />
              </button>
              <span className="text-[11.5px] font-black text-[var(--text-main)]"
                style={{ fontVariantNumeric: 'tabular-nums' }}>
                {page} / {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40 disabled:cursor-not-allowed hover:text-[var(--text-main)] transition-colors"
                aria-label="Next page"
              >
                <ChevronRight size={15} />
              </button>
            </div>
          </div>
        )}
      </div>

      <EmployeeFormModal
        isOpen={showAdd}
        onClose={() => setShowAdd(false)}
        options={options}
        onSaved={(created) => {
          setShowAdd(false);
          if (created?.employeeCode) navigate(`/hrms/employees/${created.employeeCode}`);
          else fetchEmployees();
        }}
        onError={showError}
      />
    </div>
  );
};

export default Employees;
