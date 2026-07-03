import React, { useState, useEffect, useCallback } from 'react';
import { Search, ChevronDown, ArrowUpDown, Users, ExternalLink, Loader2 } from 'lucide-react';
import { getCompanyEmployees, getEmployeeAssignments } from '../../services/reportApi';
import { fmtDate } from './reportPeriods';

const RATING_COLOR = {
  Excellent: 'var(--accent-green)', Good: 'var(--accent-indigo)',
  Average: 'var(--accent-orange)', 'Needs Attention': 'var(--accent-red)',
};
const STATUS_COLOR = {
  pending: 'var(--accent-orange)', accepted: 'var(--accent-indigo)', in_progress: 'var(--accent-indigo)',
  dependent_on_others: 'var(--accent-yellow)', blocked: 'var(--accent-red)',
  verification: 'var(--accent-yellow)', completed: 'var(--accent-green)',
};

const COLS = [
  ['name', 'Employee Name'], ['empId', 'Employee ID'], ['department', 'Department'], ['designation', 'Designation'],
  ['assigned', 'Assigned'], ['completed', 'Completed'], ['pending', 'Pending'], ['overdue', 'Overdue'],
  ['attendanceRate', 'Attendance %'], ['avgAssessment', 'Assessment'], ['coursesCompleted', 'Courses'],
  ['sessionsAttended', 'Sessions'], ['score', 'Productivity'], ['rating', 'Rating'], ['lastActivity', 'Last Activity'],
];
const SORTABLE = new Set(['assigned', 'completed', 'pending', 'overdue', 'attendanceRate', 'avgAssessment', 'score']);

const TaskRows = ({ employeeId, params }) => {
  const [tasks, setTasks] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    getEmployeeAssignments(employeeId, { ...params, limit: 50 })
      .then((r) => { if (alive) setTasks(r.items || []); })
      .catch(() => { if (alive) setTasks([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [employeeId, params]);

  if (loading) return <div className="flex items-center gap-2 py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]"><Loader2 size={14} className="animate-spin" /> Loading tasks…</div>;
  if (!tasks || tasks.length === 0) return <p className="py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]">No tasks in this period.</p>;

  return (
    <div className="overflow-x-auto bg-[var(--bg-main)] rounded-xl border border-[var(--border)] m-2">
      <table className="w-full text-left min-w-[900px]">
        <thead>
          <tr className="border-b border-[var(--border)]">
            {['Task Name', 'Module', 'Assigned', 'Due', 'Completed', 'Priority', 'Status', 'Assigned By', 'Score'].map((h) => (
              <th key={h} className="px-3 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => (
            <tr key={t.id} className="border-b border-[var(--border)] last:border-0">
              <td className="px-3 py-2 text-[12px] font-bold text-[var(--text-main)] max-w-[200px] truncate">{t.title}</td>
              <td className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{t.module}</td>
              <td className="px-3 py-2 text-[11px] text-[var(--text-muted)] whitespace-nowrap">{fmtDate(t.assignedDate)}</td>
              <td className="px-3 py-2 text-[11px] text-[var(--text-muted)] whitespace-nowrap">{fmtDate(t.dueDate)}</td>
              <td className="px-3 py-2 text-[11px] text-[var(--text-muted)] whitespace-nowrap">{fmtDate(t.completedDate)}</td>
              <td className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{t.priority}</td>
              <td className="px-3 py-2">
                <span className="px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-wider" style={{ color: STATUS_COLOR[t.status], background: 'var(--input-bg)' }}>{t.statusLabel}</span>
              </td>
              <td className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{t.assignedBy || '—'}</td>
              <td className="px-3 py-2 text-[12px] font-black text-[var(--text-main)]">{t.score ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const EmployeeTable = ({ company, params, onOpenEmployee }) => {
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('score');
  const [order, setOrder] = useState('desc');
  const [page, setPage] = useState(0);
  const [expandedEmp, setExpandedEmp] = useState(null);
  const PAGE_SIZE = 10;

  const load = useCallback(async () => {
    setLoading(true); setError(false);
    try {
      const res = await getCompanyEmployees(company.id, { ...params, search, sort, order, skip: page * PAGE_SIZE, limit: PAGE_SIZE });
      setData(res);
    } catch (e) { setError(true); }
    finally { setLoading(false); }
  }, [company.id, params, search, sort, order, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); setExpandedEmp(null); }, [company.id, params, search, sort, order]);

  const handleSort = (key) => {
    if (!SORTABLE.has(key)) return;
    if (sort === key) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    else { setSort(key); setOrder('desc'); }
  };

  const cell = 'px-3 py-3 text-[12px] font-bold text-[var(--text-main)] whitespace-nowrap';

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-[var(--border)]">
        <h3 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">
          Employee-wise Report · <span className="text-[var(--accent-indigo)]">{company.name}</span>
        </h3>
        <div className="relative min-w-[220px]">
          <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search employee..."
            className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        </div>
      </div>

      {error ? (
        <p className="px-4 py-12 text-center text-[12px] font-bold text-[var(--accent-red)]">Failed to load employees.</p>
      ) : loading ? (
        <div className="p-5 space-y-2">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-10 rounded-xl bg-[var(--input-bg)] animate-pulse" />)}</div>
      ) : (data.items || []).length === 0 ? (
        <div className="py-14 text-center"><Users size={36} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" /><p className="text-[13px] font-bold text-[var(--text-muted)]">No employees found.</p></div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1300px]">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                <th className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">#</th>
                {COLS.map(([k, label]) => (
                  <th key={k} onClick={() => handleSort(k)} className={`px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap ${SORTABLE.has(k) ? 'cursor-pointer hover:text-[var(--text-main)]' : ''}`}>
                    <span className="inline-flex items-center gap-1">{label}{sort === k && <ArrowUpDown size={10} />}</span>
                  </th>
                ))}
                <th className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest text-center">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((e, i) => {
                const isOpen = expandedEmp === e.id;
                return (
                  <React.Fragment key={e.id}>
                    <tr className={`border-b border-[var(--border)] transition-colors ${isOpen ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'}`}>
                      <td className="px-3 py-3 text-[12px] font-black text-[var(--text-muted)]">{page * PAGE_SIZE + i + 1}</td>
                      <td className={`${cell} font-black`}>{e.name}</td>
                      <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                      <td className={cell}>{e.department}</td>
                      <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                      <td className={cell}>{e.assigned}</td>
                      <td className={`${cell} text-[var(--accent-green)]`}>{e.completed}</td>
                      <td className={`${cell} text-[var(--accent-orange)]`}>{e.pending}</td>
                      <td className={`${cell} text-[var(--accent-red)]`}>{e.overdue}</td>
                      <td className={cell}>{e.attendanceRate}%</td>
                      <td className={cell}>{e.avgAssessment}%</td>
                      <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                      <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                      <td className={cell}>{e.score}%</td>
                      <td className="px-3 py-3"><span className="px-2 py-1 rounded-lg text-[10px] font-black uppercase" style={{ color: RATING_COLOR[e.rating], background: 'var(--input-bg)' }}>{e.rating}</span></td>
                      <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                      <td className="px-3 py-3 text-center whitespace-nowrap">
                        <button onClick={() => onOpenEmployee(e.id)} title="Open full report" className="p-1 text-[var(--text-muted)] hover:text-[var(--accent-indigo)]"><ExternalLink size={14} /></button>
                        <button onClick={() => setExpandedEmp(isOpen ? null : e.id)} title="Task details" className="p-1"><ChevronDown size={16} className={`text-[var(--text-muted)] transition-transform ${isOpen ? 'rotate-180 text-[var(--accent-indigo)]' : ''}`} /></button>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-[var(--bg-main)]">
                        <td colSpan={COLS.length + 2} className="p-0"><TaskRows employeeId={e.id} params={params} /></td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
          <p className="text-[11px] font-bold text-[var(--text-muted)]">Showing {page * PAGE_SIZE + 1} to {Math.min((page + 1) * PAGE_SIZE, data.total)} of {data.total} entries</p>
          <div className="flex items-center gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
            <button disabled={(page + 1) * PAGE_SIZE >= data.total} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default EmployeeTable;
