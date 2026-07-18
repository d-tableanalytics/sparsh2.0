import React, { useMemo, useState } from 'react';
import {
  RefreshCw, Users, ListChecks, CheckCircle2, XCircle, Clock, Gauge, Eye,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile,
} from '../../common/dashboardKit';
import { useCompany } from '../CompanyContext';

/* ─────────────────────────────────────────────────────────────
   SMOPS ▸ Employee Task — per-employee task-activity summary for the
   SMOPS user's assigned companies (scoped by the global company
   selector). Identical look-and-feel to the Admin Employee Tasks. Mock.
   ───────────────────────────────────────────────────────────── */

const EMPLOYEES = [
  { name: 'Bhavna R.',    company: 'Acme Corp',     designation: 'Implementor', department: 'Delivery',   total: 1, completed: 1, missed: 0, pending: 0, scheduledBy: 'System' },
  { name: 'Harshit T.',   company: 'Acme Corp',     designation: 'HOD',         department: 'Operations', total: 2, completed: 1, missed: 1, pending: 0, scheduledBy: 'System' },
  { name: 'Abhigyan J.',  company: 'Nimbus Ltd',    designation: 'Implementor', department: 'Delivery',   total: 3, completed: 2, missed: 0, pending: 1, scheduledBy: 'Manual' },
  { name: 'Abhishek G.',  company: 'Nimbus Ltd',    designation: 'Implementor', department: 'Delivery',   total: 0, completed: 0, missed: 0, pending: 0, scheduledBy: 'System' },
  { name: 'Aparajita B.', company: 'Vertex Health', designation: 'Implementor', department: 'Delivery',   total: 4, completed: 4, missed: 0, pending: 0, scheduledBy: 'System' },
  { name: 'Rahul V.',     company: 'Vertex Health', designation: 'HOD',         department: 'Support',    total: 3, completed: 1, missed: 2, pending: 0, scheduledBy: 'Manual' },
  { name: 'Neha G.',      company: 'Orbit Media',   designation: 'HR',          department: 'People',     total: 2, completed: 1, missed: 0, pending: 1, scheduledBy: 'System' },
  { name: 'Vikram S.',    company: 'Cobalt Bank',   designation: 'MD',          department: 'Leadership', total: 1, completed: 1, missed: 0, pending: 0, scheduledBy: 'Manual' },
];

const score = (e) => (e.total ? Math.round((e.completed / e.total) * 100) : 0);
const scoreColor = (v) => (v >= 80 ? 'var(--accent-green)' : v >= 60 ? 'var(--accent-orange)' : v > 0 ? 'var(--accent-red)' : 'var(--text-muted)');
const ScoreBar = ({ v }) => (
  <div className="flex items-center gap-2 min-w-[130px]">
    <div className="h-2 flex-1 rounded-full bg-[var(--input-bg)] overflow-hidden">
      <div className="h-full rounded-full transition-all" style={{ width: `${v}%`, background: v ? scoreColor(v) : 'transparent' }} />
    </div>
    <span className="text-[11px] font-bold tabular-nums" style={{ color: scoreColor(v) }}>{v}%</span>
  </div>
);
const uniq = (arr) => Array.from(new Set(arr));
const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const SmopsEmployeeTask = () => {
  const { companies, setCompanyId, company, isAll } = useCompany();
  const [month, setMonth] = useState('All Months');
  const pickCompany = (name) => setCompanyId(companies.find((c) => c.name === name).id);
  const [employee, setEmployee] = useState('All Employees');
  const [designation, setDesignation] = useState('All Designations');
  const [scheduledBy, setScheduledBy] = useState('Any');

  // Company scope comes from the global selector.
  const scoped = useMemo(() => (isAll ? EMPLOYEES : EMPLOYEES.filter((e) => e.company === company.name)), [isAll, company]);

  const rows = useMemo(() => scoped.filter((e) =>
    (employee === 'All Employees' || e.name === employee) &&
    (designation === 'All Designations' || e.designation === designation) &&
    (scheduledBy === 'Any' || e.scheduledBy === scheduledBy)), [scoped, employee, designation, scheduledBy]);

  const k = useMemo(() => {
    const total = rows.reduce((a, e) => a + e.total, 0);
    const completed = rows.reduce((a, e) => a + e.completed, 0);
    const missed = rows.reduce((a, e) => a + e.missed, 0);
    const pending = rows.reduce((a, e) => a + e.pending, 0);
    const avg = rows.length ? Math.round(rows.reduce((a, e) => a + score(e), 0) / rows.length) : 0;
    return { employees: rows.length, total, completed, missed, pending, avg };
  }, [rows]);

  const clearFilters = () => { setMonth('All Months'); setEmployee('All Employees'); setDesignation('All Designations'); setScheduledBy('Any'); };

  const kpis = [
    { value: k.employees, label: 'Employees',  sub: 'In scope',        tone: 'blue',   icon: Users },
    { value: k.total,     label: 'Total Tasks', sub: 'This period',    tone: 'yellow', icon: ListChecks },
    { value: k.completed, label: 'Completed',  sub: 'Done',            tone: 'green',  icon: CheckCircle2 },
    { value: k.missed,    label: 'Missed',     sub: 'Overdue/not done',tone: k.missed ? 'red' : 'plain', icon: XCircle },
    { value: k.pending,   label: 'Pending',    sub: 'Upcoming',        tone: 'yellow', icon: Clock },
    { value: `${k.avg}%`, label: 'Avg Score',  sub: 'Across employees',tone: k.avg >= 60 ? 'green' : 'yellow', icon: Gauge },
  ];

  return (
    <div className="space-y-5">
      <DashboardHero icon={Users} title="Company Employees — Task Activity" highlight={isAll ? 'All Companies' : company.name} subtitle="Per-employee task completion & scoring">
        <HeaderSelect value={company.name} onChange={pickCompany} options={companies.map((c) => c.name)} />
        <HeaderSelect value={month} onChange={setMonth} options={['All Months', 'Jul 2026', 'Jun 2026', 'May 2026']} />
        <HeaderSelect value={employee} onChange={setEmployee} options={['All Employees', ...uniq(scoped.map((e) => e.name))]} />
        <HeaderSelect value={designation} onChange={setDesignation} options={['All Designations', ...uniq(EMPLOYEES.map((e) => e.designation))]} />
        <HeaderSelect value={scheduledBy} onChange={setScheduledBy} options={['Any', 'System', 'Manual']} />
        <button onClick={clearFilters} className="inline-flex items-center px-3.5 py-2 rounded-lg bg-white/15 text-white text-[12.5px] font-bold ring-1 ring-white/25 hover:bg-white/25 transition-all">Clear</button>
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
      </DashboardHero>

      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {kpis.map((t) => <KpiTile key={t.label} {...t} />)}
      </div>

      <Section title="Employee Activity Summary" subtitle={`${rows.length} employee${rows.length === 1 ? '' : 's'} in scope`} icon={ListChecks}>
        <TableShell minWidth={1040}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Employee</Th><Th>Designation</Th><Th>Department</Th>
              <Th align="center">Total</Th><Th align="center">Completed</Th><Th align="center">Missed</Th><Th align="center">Pending</Th>
              <Th align="center">Score</Th><Th>Progress</Th><Th align="right">Action</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e, i) => {
              const sc = score(e);
              return (
                <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>
                    <div className="flex items-center gap-2.5">
                      <span className="w-7 h-7 rounded-full text-white text-[9px] font-bold flex items-center justify-center shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                        {e.name.split(' ').map((x) => x[0]).join('')}
                      </span>
                      {e.name}
                    </div>
                  </Td>
                  <Td className="text-[var(--accent-indigo)] font-bold uppercase text-[11px] tracking-wide">{e.designation}</Td>
                  <Td className="text-[var(--text-muted)] uppercase text-[11px] tracking-wide">{e.department}</Td>
                  <Td align="center" className="tabular-nums font-bold">{e.total}</Td>
                  <Td align="center" className="font-bold text-[var(--accent-green)]">{e.completed}</Td>
                  <Td align="center" className="font-bold text-[var(--accent-red)]">{e.missed}</Td>
                  <Td align="center" className="font-bold text-[var(--accent-orange)]">{e.pending}</Td>
                  <Td align="center" className="font-extrabold" style={{ color: scoreColor(sc) }}>{sc}%</Td>
                  <Td><ScoreBar v={sc} /></Td>
                  <Td align="right">
                    <button className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] hover:border-[var(--accent-indigo-border)] transition-all">
                      <Eye size={13} /> View
                    </button>
                  </Td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td colSpan={10} className="px-5 py-12 text-center text-[13px] font-bold text-[var(--text-muted)]">No employees match your filters.</td></tr>
            )}
          </tbody>
        </TableShell>
      </Section>
    </div>
  );
};

export default SmopsEmployeeTask;
