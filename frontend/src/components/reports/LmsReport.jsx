import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  BookOpen, CheckCircle2, Clock, Users, UserCheck, Award, Percent, Layers,
  Search, ChevronDown, Loader2, GraduationCap, BadgeCheck, CalendarDays,
} from 'lucide-react';
import { getLmsList, getLmsEmployees } from '../../services/reportApi';
import { fmtDate } from './reportPeriods';

const RATING_COLOR = {
  Excellent: 'var(--accent-green)', Good: 'var(--accent-indigo)',
  Average: 'var(--accent-orange)', 'Needs Attention': 'var(--accent-red)',
};

const Kpi = ({ label, value, icon: Icon }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 shadow-sm">
    <div className="flex items-center gap-1.5 mb-2">
      <Icon size={14} className="text-[var(--accent-indigo)]" />
      <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider truncate">{label}</span>
    </div>
    <p className="text-2xl font-black text-[var(--text-main)]">{value ?? '—'}</p>
  </div>
);

// Learner rows shown when a course (LMS/batch) is expanded.
const LearnerRows = ({ courseId, params }) => {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let alive = true;
    getLmsEmployees(courseId, { ...params, limit: 50 })
      .then((r) => { if (alive) setRows(r.items || []); })
      .catch(() => { if (alive) setRows([]); });
    return () => { alive = false; };
  }, [courseId, params]);

  if (rows === null) return <div className="flex items-center gap-2 py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]"><Loader2 size={14} className="animate-spin" /> Loading learners…</div>;
  if (rows.length === 0) return <p className="py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]">No learners in this course.</p>;

  return (
    <div className="overflow-x-auto bg-[var(--bg-main)] rounded-xl border border-[var(--border)] m-2">
      <table className="w-full text-left min-w-[900px]">
        <thead>
          <tr className="border-b border-[var(--border)]">
            {['Learner', 'Department', 'Assigned', 'Completed', 'Pending', 'Completion %', 'Attendance %', 'Assessment', 'Score', 'Certificate'].map((h) => (
              <th key={h} className="px-3 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id} className="border-b border-[var(--border)] last:border-0">
              <td className="px-3 py-2 text-[12px] font-bold text-[var(--text-main)]">{e.name}<span className="block text-[10px] text-[var(--text-muted)]">{e.email}</span></td>
              <td className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.department}</td>
              <td className="px-3 py-2 text-[12px] font-bold text-[var(--text-main)]">{e.assigned}</td>
              <td className="px-3 py-2 text-[12px] font-bold text-[var(--accent-green)]">{e.completed}</td>
              <td className="px-3 py-2 text-[12px] font-bold text-[var(--accent-orange)]">{e.pending}</td>
              <td className="px-3 py-2 text-[12px] font-bold text-[var(--text-main)]">{e.completionRate}%</td>
              <td className="px-3 py-2 text-[12px] font-bold text-[var(--text-main)]">{e.attendanceRate}%</td>
              <td className="px-3 py-2 text-[12px] font-bold text-[var(--text-main)]">{e.avgAssessment}%</td>
              <td className="px-3 py-2 text-[13px] font-black" style={{ color: RATING_COLOR[e.rating] }}>{e.score}</td>
              <td className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">—</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const LmsReport = ({ params }) => {
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 10;

  const load = useCallback(async () => {
    setLoading(true); setError(false);
    try {
      const res = await getLmsList({ ...params, search, limit: 300 });
      setCourses(res.items || []);
    } catch (e) { setError(true); }
    finally { setLoading(false); }
  }, [params, search]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); setExpanded(null); }, [params, search]);

  // LMS summary cards — aggregated client-side from the real course list (no new API).
  const summary = useMemo(() => {
    const totalCourses = courses.reduce((s, c) => s + (c.coursesAssigned || 0), 0);
    const completedCourses = courses.reduce((s, c) => s + (c.coursesCompleted || 0), 0);
    const totalLearners = courses.reduce((s, c) => s + (c.totalUsers || 0), 0);
    const activeLearners = courses.reduce((s, c) => s + (c.activeUsers || 0), 0);
    const withScore = courses.filter((c) => c.avgScore != null);
    const avgScore = withScore.length ? Math.round(withScore.reduce((s, c) => s + c.avgScore, 0) / withScore.length) : 0;
    return {
      totalCourses,
      activeCourses: courses.filter((c) => c.status === 'active').length,
      completedCourses,
      inProgress: Math.max(0, totalCourses - completedCourses),
      totalLearners,
      activeLearners,
      avgScore,
      completionRate: totalCourses ? Math.round((completedCourses / totalCourses) * 100) : 0,
    };
  }, [courses]);

  const paged = courses.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const cell = 'px-3 py-3 text-[12px] font-bold text-[var(--text-main)] whitespace-nowrap';

  const cards = [
    { label: 'Total Courses', value: summary.totalCourses, icon: BookOpen },
    { label: 'Active Courses', value: summary.activeCourses, icon: Layers },
    { label: 'Completed Courses', value: summary.completedCourses, icon: CheckCircle2 },
    { label: 'In Progress', value: summary.inProgress, icon: Clock },
    { label: 'Total Learners', value: summary.totalLearners, icon: Users },
    { label: 'Active Learners', value: summary.activeLearners, icon: UserCheck },
    { label: 'Completed Assessments', value: '—', icon: Award },
    { label: 'Pending Assessments', value: '—', icon: Clock },
    { label: 'Avg Assessment', value: `${summary.avgScore}%`, icon: Award },
    { label: 'Certificates', value: '—', icon: BadgeCheck },
    { label: 'Sessions Conducted', value: summary.totalCourses, icon: CalendarDays },
    { label: 'Completion Rate', value: `${summary.completionRate}%`, icon: Percent },
  ];

  return (
    <div className="space-y-5">
      {/* LMS summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
        {cards.map((c) => <Kpi key={c.label} {...c} />)}
      </div>

      {/* Course-wise report */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-[var(--border)]">
          <h3 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">Course-wise Report</h3>
          <div className="relative min-w-[220px]">
            <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search course..."
              className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
          </div>
        </div>

        {error ? (
          <p className="px-4 py-12 text-center text-[12px] font-bold text-[var(--accent-red)]">Failed to load LMS report.</p>
        ) : loading ? (
          <div className="p-5 space-y-2">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-10 rounded-xl bg-[var(--input-bg)] animate-pulse" />)}</div>
        ) : courses.length === 0 ? (
          <div className="py-16 text-center"><GraduationCap size={38} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" /><p className="text-[13px] font-bold text-[var(--text-muted)]">No courses for this period.</p></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[1000px]">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                  <th className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">#</th>
                  {['Course Name', 'Total Learners', 'Active Learners', 'Completed', 'Completion %', 'Avg Score', 'Trainer', 'Total Sessions'].map((h) => (
                    <th key={h} className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap">{h}</th>
                  ))}
                  <th className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest text-center">Action</th>
                </tr>
              </thead>
              <tbody>
                {paged.map((c, i) => {
                  const isOpen = expanded === c.id;
                  return (
                    <React.Fragment key={c.id}>
                      <tr onClick={() => setExpanded(isOpen ? null : c.id)}
                        className={`border-b border-[var(--border)] cursor-pointer transition-colors ${isOpen ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'}`}>
                        <td className="px-3 py-3 text-[12px] font-black text-[var(--text-muted)]">{page * PAGE_SIZE + i + 1}</td>
                        <td className={`${cell} font-black`}>{c.name}</td>
                        <td className={cell}>{c.totalUsers}</td>
                        <td className={cell}>{c.activeUsers}</td>
                        <td className={`${cell} text-[var(--accent-green)]`}>{c.coursesCompleted}</td>
                        <td className={cell}>{c.completionRate}%</td>
                        <td className={cell}>{c.avgScore}%</td>
                        <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                        <td className={cell}>{c.coursesAssigned}</td>
                        <td className="px-3 py-3 text-center"><ChevronDown size={16} className={`inline text-[var(--text-muted)] transition-transform ${isOpen ? 'rotate-180 text-[var(--accent-indigo)]' : ''}`} /></td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-[var(--bg-main)]"><td colSpan={10} className="p-0"><LearnerRows courseId={c.id} params={params} /></td></tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {courses.length > PAGE_SIZE && (
          <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
            <p className="text-[11px] font-bold text-[var(--text-muted)]">Showing {page * PAGE_SIZE + 1} to {Math.min((page + 1) * PAGE_SIZE, courses.length)} of {courses.length} entries</p>
            <div className="flex items-center gap-2">
              <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
              <button disabled={(page + 1) * PAGE_SIZE >= courses.length} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default LmsReport;
