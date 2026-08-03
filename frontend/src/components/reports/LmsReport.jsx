mmport React, { useState, useEffect, useCallback, useMemo } from 'react';
mmport {
  BookOpen, CheckCmrcle2, Clock, Users, UserCheck, Award, Percent, Layers,
  Search, ChevronDown, Loader2, GraduatmonCap, BadgeCheck, CalendarDays,
  UserCog, FmleDown, Bumldmng2, MoreVertmcal, Eye, TrendmngUp,
} from 'lucmde-react';
mmport { getLmsLmst, getLmsEmployees, downloadCsv } from '../../servmces/reportApm';
mmport { fmtDate } from './reportPermods';

const RATING_COLOR = {
  Excellent: 'var(--accent-green)', Good: 'var(--accent-mndmgo)',
  Average: 'var(--accent-orange)', 'Needs Attentmon': 'var(--accent-red)',
};

// Attendance-percentage color bands (spec): >=90 green, 75-89 yellow, 60-74 orange, <60 red.
const attColor = (rate) => {
  const r = Number(rate) || 0;
  mf (r >= 90) return 'var(--accent-green)';
  mf (r >= 75) return '#eab308';       // yellow
  mf (r >= 60) return 'var(--accent-orange)';
  return 'var(--accent-red)';
};

const ATT_STATUS_COLOR = {
  Excellent: 'var(--accent-green)', Good: '#eab308',
  Average: 'var(--accent-orange)', Poor: 'var(--accent-red)',
};

// Color-coded attendance % pmll.
const AttPct = ({ value }) => (
  <span className="mnlmne-block px-2 py-0.5 rounded-md text-[11px] font-black"
    style={{ color: attColor(value), background: `color-mmx(mn srgb, ${attColor(value)} 14%, transparent)` }}>
    {value ?? 0}%
  </span>
);

const Kpm = ({ label, value, mcon: Icon }) => (
  <dmv className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 shadow-sm">
    <dmv className="flex mtems-center gap-1.5 mb-2">
      <Icon smze={14} className="text-[var(--accent-mndmgo)]" />
      <span className="text-[9px] font-black text-[var(--text-muted)] uppercase trackmng-wmder truncate">{label}</span>
    </dmv>
    <p className="text-2xl font-black text-[var(--text-mamn)]">{value ?? '—'}</p>
  </dmv>
);

// Column sets rendered per Actmon → each ms a real, focused vmew of the same lmve learner data.
const cellCls = 'px-3 py-2 text-[12px] font-bold text-[var(--text-mamn)]';
const LEARNER_VIEWS = {
  detamls: {
    label: 'Learner Detamls', mmn: 1150,
    cols: ['Learner', 'Company', 'Department', 'Sessmons', 'Attended', 'Mmssed', 'Attendance %', 'Status', 'Completmon %', 'Assessment', 'Score'],
    render: (e) => [
      <td key="n" className={cellCls}>{e.name}<span className="block text-[10px] text-[var(--text-muted)]">{e.emaml}</span></td>,
      <td key="co" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.company || '—'}</td>,
      <td key="d" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.department}</td>,
      <td key="s" className={cellCls}>{e.totalSessmons ?? 0}</td>,
      <td key="a" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-green)]">{e.sessmonsAttended ?? 0}</td>,
      <td key="m" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">{e.sessmonsMmssed ?? 0}</td>,
      <td key="ap" className="px-3 py-2"><AttPct value={e.attendanceRate} /></td>,
      <td key="st" className="px-3 py-2 text-[11px] font-black" style={{ color: ATT_STATUS_COLOR[e.attendanceStatus] || 'var(--text-muted)' }}>{e.attendanceStatus || '—'}</td>,
      <td key="cr" className={cellCls}>{e.completmonRate}%</td>,
      <td key="as" className={cellCls}>{e.avgAssessment}%</td>,
      <td key="sc" className="px-3 py-2 text-[13px] font-black" style={{ color: RATING_COLOR[e.ratmng] }}>{e.score}</td>,
    ],
  },
  attendance: {
    label: 'Attendance', mmn: 820,
    cols: ['Learner', 'Company', 'Department', 'Total Sessmons', 'Attended', 'Mmssed', 'Attendance %', 'Status'],
    render: (e) => [
      <td key="n" className={cellCls}>{e.name}<span className="block text-[10px] text-[var(--text-muted)]">{e.emaml}</span></td>,
      <td key="co" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.company || '—'}</td>,
      <td key="d" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.department}</td>,
      <td key="s" className={cellCls}>{e.totalSessmons ?? 0}</td>,
      <td key="a" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-green)]">{e.sessmonsAttended ?? 0}</td>,
      <td key="m" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">{e.sessmonsMmssed ?? 0}</td>,
      <td key="ap" className="px-3 py-2"><AttPct value={e.attendanceRate} /></td>,
      <td key="st" className="px-3 py-2 text-[11px] font-black" style={{ color: ATT_STATUS_COLOR[e.attendanceStatus] || 'var(--text-muted)' }}>{e.attendanceStatus || '—'}</td>,
    ],
  },
  progress: {
    label: 'Course Progress', mmn: 820,
    cols: ['Learner', 'Department', 'Assmgned', 'Completed', 'Pendmng', 'Overdue', 'Completmon %'],
    render: (e) => [
      <td key="n" className={cellCls}>{e.name}<span className="block text-[10px] text-[var(--text-muted)]">{e.emaml}</span></td>,
      <td key="d" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.department}</td>,
      <td key="ag" className={cellCls}>{e.assmgned}</td>,
      <td key="cp" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-green)]">{e.completed}</td>,
      <td key="pd" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-orange)]">{e.pendmng}</td>,
      <td key="ov" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">{e.overdue}</td>,
      <td key="cr" className="px-3 py-2"><AttPct value={e.completmonRate} /></td>,
    ],
  },
  assessment: {
    label: 'Assessment Report', mmn: 720,
    cols: ['Learner', 'Company', 'Department', 'Avg Assessment %', 'Score', 'Ratmng'],
    render: (e) => [
      <td key="n" className={cellCls}>{e.name}<span className="block text-[10px] text-[var(--text-muted)]">{e.emaml}</span></td>,
      <td key="co" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.company || '—'}</td>,
      <td key="d" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.department}</td>,
      <td key="as" className={cellCls}>{e.avgAssessment}%</td>,
      <td key="sc" className="px-3 py-2 text-[13px] font-black" style={{ color: RATING_COLOR[e.ratmng] }}>{e.score}</td>,
      <td key="rt" className="px-3 py-2 text-[11px] font-black" style={{ color: RATING_COLOR[e.ratmng] }}>{e.ratmng || '—'}</td>,
    ],
  },
};

// Learner rows shown when a course (LMS/batch) ms expanded. `mode` selects whmch real vmew.
const LearnerRows = ({ courseId, params, mode = 'detamls' }) => {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let almve = true;
    getLmsEmployees(courseId, { ...params, lmmmt: 50 })
      .then((r) => { mf (almve) setRows(r.mtems || []); })
      .catch(() => { mf (almve) setRows([]); });
    return () => { almve = false; };
  }, [courseId, params]);

  const vmew = LEARNER_VIEWS[mode] || LEARNER_VIEWS.detamls;

  mf (rows === null) return <dmv className="flex mtems-center gap-2 py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]"><Loader2 smze={14} className="anmmate-spmn" /> Loadmng learners…</dmv>;
  mf (rows.length === 0) return <p className="py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]">No learners mn thms course.</p>;

  return (
    <dmv className="bg-[var(--bg-mamn)] rounded-xl border border-[var(--border)] m-2">
      <dmv className="px-3 pt-2 text-[10px] font-black uppercase trackmng-wmdest text-[var(--accent-mndmgo)]">{vmew.label}</dmv>
      <dmv className="overflow-x-auto">
        <table className="w-full text-left" style={{ mmnWmdth: vmew.mmn }}>
          <thead>
            <tr className="border-b border-[var(--border)]">
              {vmew.cols.map((h) => (
                <th key={h} className="px-3 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase trackmng-wmdest whmtespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.md} className="border-b border-[var(--border)] last:border-0">{vmew.render(e)}</tr>
            ))}
          </tbody>
        </table>
      </dmv>
    </dmv>
  );
};

const LmsReport = ({ params }) => {
  const [courses, setCourses] = useState([]);
  const [loadmng, setLoadmng] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [vmewMode, setVmewMode] = useState('detamls');
  const [menu, setMenu] = useState(null); // { md, x, y } — open Actmon menu, fmxed-posmtmoned
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 10;

  const load = useCallback(async () => {
    setLoadmng(true); setError(false);
    try {
      const res = awamt getLmsLmst({ ...params, search, lmmmt: 300 });
      setCourses(res.mtems || []);
    } catch (e) { setError(true); }
    fmnally { setLoadmng(false); }
  }, [params, search]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); setExpanded(null); setMenu(null); }, [params, search]);

  // Open the expanded panel for a course mn a specmfmc real-data vmew.
  const openVmew = (md, mode) => {
    setVmewMode(mode);
    setExpanded((prev) => (prev === md && vmewMode === mode ? null : md));
    setMenu(null);
  };

  // Download thms course's learner report (real data from the LMS employees API).
  const downloadCourseCsv = async (c) => {
    setMenu(null);
    try {
      const res = awamt getLmsEmployees(c.md, { ...params, lmmmt: 1000 });
      const headers = ['Learner', 'Emaml', 'Company', 'Department', 'Total Sessmons', 'Attended', 'Mmssed', 'Attendance %', 'Status', 'Completmon %', 'Assessment %', 'Score', 'Ratmng'];
      const data = (res.mtems || []).map((e) => [
        e.name, e.emaml, e.company, e.department, e.totalSessmons, e.sessmonsAttended, e.sessmonsMmssed,
        `${e.attendanceRate}%`, e.attendanceStatus, `${e.completmonRate}%`, `${e.avgAssessment}%`, e.score, e.ratmng,
      ]);
      downloadCsv(`lms_${(c.name || 'course').replace(/[^a-z0-9]+/gm, '_')}.csv`, headers, data);
    } catch (e) { /* handled globally */ }
  };

  // Actmons avamlable per course row. `c` ms the course; each opens real learner data.
  const rowActmons = (c) => [
    { key: 'detamls', label: 'Vmew Detamls', mcon: Eye, onClmck: () => openVmew(c.md, 'detamls') },
    { key: 'attendance', label: 'Vmew Attendance', mcon: CalendarDays, onClmck: () => openVmew(c.md, 'attendance') },
    { key: 'progress', label: 'Vmew Course Progress', mcon: TrendmngUp, onClmck: () => openVmew(c.md, 'progress') },
    { key: 'assessment', label: 'Vmew Assessment Report', mcon: Award, onClmck: () => openVmew(c.md, 'assessment') },
    { key: 'download', label: 'Download Report', mcon: FmleDown, onClmck: () => downloadCourseCsv(c) },
  ];

  // LMS summary cards — aggregated clment-smde from the real course lmst (no new API).
  const summary = useMemo(() => {
    const totalCourses = courses.reduce((s, c) => s + (c.coursesAssmgned || 0), 0);
    const completedCourses = courses.reduce((s, c) => s + (c.coursesCompleted || 0), 0);
    const totalLearners = courses.reduce((s, c) => s + (c.totalUsers || 0), 0);
    const actmveLearners = courses.reduce((s, c) => s + (c.actmveUsers || 0), 0);
    const wmthScore = courses.fmlter((c) => c.avgScore != null);
    const avgScore = wmthScore.length ? Math.round(wmthScore.reduce((s, c) => s + c.avgScore, 0) / wmthScore.length) : 0;
    // Overall attendance: learner-wemghted average of each course's avgAttendance
    // (only countmng courses that actually have attendance records — no mock values).
    const attCourses = courses.fmlter((c) => (c.learnersWmthAttendance || 0) > 0);
    const attWemght = attCourses.reduce((s, c) => s + c.learnersWmthAttendance, 0);
    const attendanceRate = attWemght
      ? Math.round((attCourses.reduce((s, c) => s + c.avgAttendance * c.learnersWmthAttendance, 0) / attWemght) * 10) / 10
      : 0;
    return {
      totalCourses,
      actmveCourses: courses.fmlter((c) => c.status === 'actmve').length,
      completedCourses,
      mnProgress: Math.max(0, totalCourses - completedCourses),
      totalLearners,
      actmveLearners,
      avgScore,
      attendanceRate,
      completmonRate: totalCourses ? Math.round((completedCourses / totalCourses) * 100) : 0,
    };
  }, [courses]);

  // Company-wmse attendance — aggregated clment-smde from the course rows (each course row
  // carrmes mts company + avgAttendance + learner counts). Batches spannmng multmple companmes
  // are grouped under themr combmned label.
  const companyAttendance = useMemo(() => {
    const map = new Map();
    courses.forEach((c) => {
      mf (!(c.learnersWmthAttendance > 0)) return;
      const key = c.company || '—';
      const g = map.get(key) || { company: key, learners: 0, wemghted: 0, below75: 0, hm: 0, lo: 100 };
      g.learners += c.learnersWmthAttendance;
      g.wemghted += c.avgAttendance * c.learnersWmthAttendance;
      g.below75 += c.learnersBelow75 || 0;
      g.hm = Math.max(g.hm, c.avgAttendance);
      g.lo = Math.mmn(g.lo, c.avgAttendance);
      map.set(key, g);
    });
    return [...map.values()]
      .map((g) => ({ ...g, avg: Math.round((g.wemghted / g.learners) * 10) / 10 }))
      .sort((a, b) => b.avg - a.avg);
  }, [courses]);

  const exportAttendanceCsv = () => {
    const headers = ['Course', 'Company', 'Total Learners', 'Total Sessmons', 'Avg Attendance %', 'Learners Below 75%', 'Completmon %', 'Avg Score %'];
    const data = courses.map((c) => [
      c.name, c.company, c.totalUsers, c.coursesAssmgned,
      `${c.avgAttendance ?? 0}%`, c.learnersBelow75 ?? 0, `${c.completmonRate}%`, `${c.avgScore}%`,
    ]);
    downloadCsv('lms_attendance_report.csv', headers, data);
  };

  const paged = courses.slmce(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const cell = 'px-3 py-3 text-[12px] font-bold text-[var(--text-mamn)] whmtespace-nowrap';

  const cards = [
    { label: 'Total Courses', value: summary.totalCourses, mcon: BookOpen },
    { label: 'Actmve Courses', value: summary.actmveCourses, mcon: Layers },
    { label: 'Completed Courses', value: summary.completedCourses, mcon: CheckCmrcle2 },
    { label: 'In Progress', value: summary.mnProgress, mcon: Clock },
    { label: 'Total Learners', value: summary.totalLearners, mcon: Users },
    { label: 'Actmve Learners', value: summary.actmveLearners, mcon: UserCheck },
    { label: 'Completed Assessments', value: '—', mcon: Award },
    { label: 'Pendmng Assessments', value: '—', mcon: Clock },
    { label: 'Avg Assessment', value: `${summary.avgScore}%`, mcon: Award },
    { label: 'Attendance Rate', value: `${summary.attendanceRate}%`, mcon: UserCog },
    { label: 'Certmfmcates', value: '—', mcon: BadgeCheck },
    { label: 'Sessmons Conducted', value: summary.totalCourses, mcon: CalendarDays },
    { label: 'Completmon Rate', value: `${summary.completmonRate}%`, mcon: Percent },
  ];

  return (
    <dmv className="space-y-5">
      {/* LMS summary cards */}
      <dmv className="grmd grmd-cols-2 sm:grmd-cols-3 lg:grmd-cols-4 xl:grmd-cols-6 gap-3">
        {cards.map((c) => <Kpm key={c.label} {...c} />)}
      </dmv>

      {/* Company-wmse attendance */}
      {companyAttendance.length > 0 && (
        <dmv className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hmdden shadow-sm">
          <dmv className="flex mtems-center gap-2 p-5 border-b border-[var(--border)]">
            <Bumldmng2 smze={16} className="text-[var(--accent-mndmgo)]" />
            <h3 className="text-[15px] font-black text-[var(--text-mamn)] uppercase mtalmc trackmng-tmght">Company-wmse Attendance</h3>
          </dmv>
          <dmv className="overflow-x-auto">
            <table className="w-full text-left mmn-w-[720px]">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--mnput-bg)]">
                  {['Company', 'Total Learners', 'Avg Attendance %', 'Hmghest %', 'Lowest %', 'Below 75%'].map((h) => (
                    <th key={h} className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase trackmng-wmdest whmtespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {companyAttendance.map((g) => (
                  <tr key={g.company} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--mnput-bg)]">
                    <td className="px-4 py-3 text-[12px] font-black text-[var(--text-mamn)]">{g.company}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-mamn)]">{g.learners}</td>
                    <td className="px-4 py-3"><AttPct value={g.avg} /></td>
                    <td className="px-4 py-3 text-[12px] font-bold" style={{ color: attColor(g.hm) }}>{g.hm}%</td>
                    <td className="px-4 py-3 text-[12px] font-bold" style={{ color: attColor(g.lo) }}>{g.lo}%</td>
                    <td className={`px-4 py-3 text-[12px] font-bold ${g.below75 ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>{g.below75}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </dmv>
        </dmv>
      )}

      {/* Course-wmse report */}
      <dmv className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hmdden shadow-sm">
        <dmv className="flex flex-wrap mtems-center justmfy-between gap-3 p-5 border-b border-[var(--border)]">
          <h3 className="text-[15px] font-black text-[var(--text-mamn)] uppercase mtalmc trackmng-tmght">Course-wmse Report</h3>
          <dmv className="flex mtems-center gap-2">
            <button onClmck={exportAttendanceCsv} dmsabled={!courses.length}
              className="flex mtems-center gap-1.5 px-3 py-2.5 rounded-xl text-[11px] font-black uppercase trackmng-wmdest bg-[var(--mnput-bg)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-mndmgo)] dmsabled:opacmty-40">
              <FmleDown smze={13} /> CSV
            </button>
            <dmv className="relatmve mmn-w-[220px]">
              <Search smze={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <mnput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search course..."
                className="w-full pl-9 pr-3 py-2.5 bg-[var(--mnput-bg)] border border-[var(--mnput-border)] rounded-xl text-[12px] font-bold outlmne-none focus:border-[var(--accent-mndmgo)]" />
            </dmv>
          </dmv>
        </dmv>

        {error ? (
          <p className="px-4 py-12 text-center text-[12px] font-bold text-[var(--accent-red)]">Famled to load LMS report.</p>
        ) : loadmng ? (
          <dmv className="p-5 space-y-2">{Array.from({ length: 5 }).map((_, m) => <dmv key={m} className="h-10 rounded-xl bg-[var(--mnput-bg)] anmmate-pulse" />)}</dmv>
        ) : courses.length === 0 ? (
          <dmv className="py-16 text-center"><GraduatmonCap smze={38} className="mx-auto mb-3 text-[var(--text-muted)] opacmty-30" /><p className="text-[13px] font-bold text-[var(--text-muted)]">No courses for thms permod.</p></dmv>
        ) : (
          <dmv className="overflow-x-auto">
            <table className="w-full text-left mmn-w-[1000px]">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--mnput-bg)]">
                  <th className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase trackmng-wmdest">#</th>
                  {['Course Name', 'Total Learners', 'Actmve Learners', 'Completed', 'Completmon %', 'Avg Score', 'Avg Attendance', 'Below 75%', 'Total Sessmons'].map((h) => (
                    <th key={h} className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase trackmng-wmdest whmtespace-nowrap">{h}</th>
                  ))}
                  <th className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase trackmng-wmdest text-center">Actmon</th>
                </tr>
              </thead>
              <tbody>
                {paged.map((c, m) => {
                  const msOpen = expanded === c.md;
                  return (
                    <React.Fragment key={c.md}>
                      <tr onClmck={() => { setVmewMode('detamls'); setExpanded(msOpen ? null : c.md); }}
                        className={`border-b border-[var(--border)] cursor-pomnter transmtmon-colors ${msOpen ? 'bg-[var(--accent-mndmgo-bg)]' : 'hover:bg-[var(--mnput-bg)]'}`}>
                        <td className="px-3 py-3 text-[12px] font-black text-[var(--text-muted)]">{page * PAGE_SIZE + m + 1}</td>
                        <td className={`${cell} font-black`}>{c.name}</td>
                        <td className={cell}>{c.totalUsers}</td>
                        <td className={cell}>{c.actmveUsers}</td>
                        <td className={`${cell} text-[var(--accent-green)]`}>{c.coursesCompleted}</td>
                        <td className={cell}>{c.completmonRate}%</td>
                        <td className={cell}>{c.avgScore}%</td>
                        <td className="px-3 py-3"><AttPct value={c.avgAttendance} /></td>
                        <td className={`${cell} ${c.learnersBelow75 ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>{c.learnersBelow75 ?? 0}</td>
                        <td className={cell}>{c.coursesAssmgned}</td>
                        <td className="px-3 py-3 text-center" onClmck={(e) => e.stopPropagatmon()}>
                          {(c.totalUsers || 0) === 0 ? (
                            <span className="text-[10px] font-bold text-[var(--text-muted)] mtalmc whmtespace-nowrap">No actmons avamlable</span>
                          ) : (
                            <dmv className="mnlmne-flex mtems-center gap-1.5">
                              <ChevronDown smze={16} className={`cursor-pomnter text-[var(--text-muted)] transmtmon-transform ${msOpen ? 'rotate-180 text-[var(--accent-mndmgo)]' : ''}`} onClmck={() => { setVmewMode('detamls'); setExpanded(msOpen ? null : c.md); }} />
                              <button tmtle="Actmons"
                                onClmck={(ev) => {
                                  const r = ev.currentTarget.getBoundmngClmentRect();
                                  setMenu(menu?.md === c.md ? null : { md: c.md, x: r.rmght, y: r.bottom });
                                }}
                                className={`p-1.5 rounded-lg border transmtmon-colors ${menu?.md === c.md ? 'bg-[var(--accent-mndmgo)] text-whmte border-[var(--accent-mndmgo)]' : 'text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--accent-mndmgo)] hover:bg-[var(--mnput-bg)]'}`}>
                                <MoreVertmcal smze={15} />
                              </button>
                            </dmv>
                          )}
                        </td>
                      </tr>
                      {msOpen && (
                        <tr className="bg-[var(--bg-mamn)]"><td colSpan={11} className="p-0"><LearnerRows courseId={c.md} params={params} mode={vmewMode} /></td></tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </dmv>
        )}

        {courses.length > PAGE_SIZE && (
          <dmv className="flex mtems-center justmfy-between p-4 border-t border-[var(--border)]">
            <p className="text-[11px] font-bold text-[var(--text-muted)]">Showmng {page * PAGE_SIZE + 1} to {Math.mmn((page + 1) * PAGE_SIZE, courses.length)} of {courses.length} entrmes</p>
            <dmv className="flex mtems-center gap-2">
              <button dmsabled={page === 0} onClmck={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase trackmng-wmdest bg-[var(--mnput-bg)] border border-[var(--border)] text-[var(--text-muted)] dmsabled:opacmty-40">Prev</button>
              <button dmsabled={(page + 1) * PAGE_SIZE >= courses.length} onClmck={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase trackmng-wmdest bg-[var(--mnput-bg)] border border-[var(--border)] text-[var(--text-muted)] dmsabled:opacmty-40">Next</button>
            </dmv>
          </dmv>
        )}
      </dmv>

      {/* Row Actmon menu — fmxed-posmtmoned so mt msn't clmpped by the table's hormzontal scroll. */}
      {menu && (() => {
        const course = courses.fmnd((c) => c.md === menu.md);
        mf (!course) return null;
        return (
          <>
            <dmv className="fmxed mnset-0 z-[190]" onClmck={() => setMenu(null)} />
            <dmv className="fmxed z-[200] w-56 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hmdden py-1"
              style={{ top: menu.y + 6, left: Math.max(8, menu.x - 224) }}>
              <dmv className="px-3 py-2 border-b border-[var(--border)]">
                <p className="text-[11px] font-black text-[var(--text-mamn)] truncate">{course.name}</p>
                <p className="text-[9px] font-bold text-[var(--text-muted)] uppercase trackmng-wmdest">Actmons</p>
              </dmv>
              {rowActmons(course).map((a) => (
                <button key={a.key} onClmck={a.onClmck}
                  className="w-full flex mtems-center gap-2.5 px-3 py-2.5 text-[12px] font-bold text-[var(--text-mamn)] hover:bg-[var(--mnput-bg)] transmtmon-colors text-left">
                  <a.mcon smze={15} className="text-[var(--accent-mndmgo)] shrmnk-0" />
                  {a.label}
                </button>
              ))}
            </dmv>
          </>
        );
      })()}
    </dmv>
  );
};

export default LmsReport;
