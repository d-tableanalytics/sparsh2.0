import React, { useMemo, useState } from 'react';
import {
  RefreshCw, UserCog, ListChecks, CheckCircle2, XCircle, Clock, Target,
  ClipboardList, ClipboardCheck, AlertTriangle, Mail, IdCard, Building2,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile,
} from '../../common/dashboardKit';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ HOD View — per-HOD activity dashboard: identity,
   activity scoring (per activity × month), occurrence tracker,
   needs-attention and open action items. All data is placeholder mock.
   ───────────────────────────────────────────────────────────── */

const HODS = [
  {
    name: 'Ananya Rao', id: 'EMP-171', company: 'Acme Corp', role: 'MD', email: 'ananya@acme.co', actionClosure: 88,
    scoring: [
      { month: 'Jul', activity: 'WRM', completed: 3, total: 4, missed: 1, pending: 0, score: 82 },
      { month: 'Jul', activity: 'MMR', completed: 1, total: 1, missed: 0, pending: 0, score: 88 },
      { month: 'Jul', activity: 'DRM', completed: 2, total: 2, missed: 0, pending: 0, score: 90 },
    ],
    occ: [
      { date: '2026-07-03', month: 'Jul', activity: 'WRM', status: 'Completed' },
      { date: '2026-07-10', month: 'Jul', activity: 'WRM', status: 'Completed' },
      { date: '2026-07-17', month: 'Jul', activity: 'WRM', status: 'Missed' },
      { date: '2026-07-15', month: 'Jul', activity: 'MMR', status: 'Completed' },
    ],
    needs: ['WRM occurrence on 17 Jul missed — reschedule required.'],
    actions: [{ activity: 'WRM', action: 'Reschedule missed WRM', owner: 'Ananya Rao', emp: 'EMP-171', target: '2026-07-22', status: 'Pending', clientDelay: 'Pending', omDelay: 'On-track', followup: 'Call scheduled' }],
  },
  {
    name: 'Rahul Verma', id: 'EMP-204', company: 'Nimbus Ltd', role: 'HOD', email: 'rahul@nimbus.in', actionClosure: 61,
    scoring: [
      { month: 'Jul', activity: 'WRM', completed: 2, total: 4, missed: 2, pending: 0, score: 55 },
      { month: 'Jul', activity: 'Cal Disc', completed: 1, total: 2, missed: 1, pending: 0, score: 48 },
    ],
    occ: [
      { date: '2026-07-04', month: 'Jul', activity: 'WRM', status: 'Completed' },
      { date: '2026-07-11', month: 'Jul', activity: 'WRM', status: 'Missed' },
      { date: '2026-07-18', month: 'Jul', activity: 'WRM', status: 'Missed' },
      { date: '2026-07-14', month: 'Jul', activity: 'Cal Disc', status: 'Pending' },
    ],
    needs: ['2 WRM occurrences missed this month.', 'Action "Follow up: WRM" overdue by 1 day.'],
    actions: [{ activity: 'WRM', action: 'Follow up: WRM', owner: 'Megha M.', emp: 'EMP-170', target: '2026-07-17', status: 'Overdue', clientDelay: 'Delayed', omDelay: 'Pending', followup: 'Email sent' }],
  },
  {
    name: 'Deepak Joshi', id: 'EMP-233', company: 'Vertex Health', role: 'HR', email: 'deepak@vertex.io', actionClosure: 96,
    scoring: [
      { month: 'Jul', activity: 'WRM', completed: 4, total: 4, missed: 0, pending: 0, score: 92 },
      { month: 'Jul', activity: 'MMR', completed: 1, total: 1, missed: 0, pending: 0, score: 90 },
      { month: 'Jul', activity: 'Imp Stats', completed: 1, total: 1, missed: 0, pending: 0, score: 85 },
    ],
    occ: [
      { date: '2026-07-02', month: 'Jul', activity: 'WRM', status: 'Completed' },
      { date: '2026-07-09', month: 'Jul', activity: 'WRM', status: 'Completed' },
      { date: '2026-07-16', month: 'Jul', activity: 'WRM', status: 'Completed' },
    ],
    needs: [],
    actions: [],
  },
];

const COMPANIES = ['All Companies', ...Array.from(new Set(HODS.map((h) => h.company)))];

const OCC = {
  Completed: { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Missed:    { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  Pending:   { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
};
const OccPill = ({ v }) => {
  const s = OCC[v];
  return <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}><span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{v}</span>;
};
const scoreColor = (v) => (v >= 80 ? 'var(--accent-green)' : v >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)');
const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const HodView = () => {
  const [company, setCompany] = useState('All Companies');
  const [period, setPeriod] = useState('This Month');

  const list = company === 'All Companies' ? HODS : HODS.filter((h) => h.company === company);
  const [hodId, setHodId] = useState(HODS[0].id);
  const hod = list.find((h) => h.id === hodId) || list[0] || HODS[0];

  const figures = useMemo(() => {
    const s = hod.scoring;
    const total = s.reduce((a, r) => a + r.total, 0);
    const completed = s.reduce((a, r) => a + r.completed, 0);
    const missed = s.reduce((a, r) => a + r.missed, 0);
    const pending = s.reduce((a, r) => a + r.pending, 0);
    return {
      total, completed, missed, pending,
      completion: total ? Math.round((completed / total) * 100) : 0,
      openActions: hod.actions.length,
      actionClosure: hod.actionClosure,
    };
  }, [hod]);

  const kpis = [
    { value: figures.total,             label: 'Activities',    sub: 'This period',   tone: 'blue',   icon: ListChecks },
    { value: figures.completed,         label: 'Completed',     sub: 'Done',          tone: 'green',  icon: CheckCircle2 },
    { value: figures.missed,            label: 'Missed',        sub: 'Not done',      tone: figures.missed ? 'red' : 'plain', icon: XCircle },
    { value: figures.pending,           label: 'Pending',       sub: 'Upcoming',      tone: 'yellow', icon: Clock },
    { value: `${figures.completion}%`,  label: 'Completion',    sub: 'Done ÷ total',  tone: figures.completion >= 80 ? 'green' : 'yellow', icon: Target },
    { value: figures.openActions,       label: 'Open Actions',  sub: 'To close',      tone: figures.openActions ? 'red' : 'plain', icon: ClipboardList },
    { value: `${figures.actionClosure}%`, label: 'Action Closure', sub: 'vs 95% target', tone: figures.actionClosure >= 95 ? 'green' : 'yellow', icon: ClipboardCheck },
  ];

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={UserCog} title="HOD Activity" highlight={hod.name} subtitle="Per-HOD activity scoring & accountability">
        <HeaderSelect value={company} onChange={(v) => { setCompany(v); const f = v === 'All Companies' ? HODS : HODS.filter((h) => h.company === v); if (f[0]) setHodId(f[0].id); }} options={COMPANIES} />
        <HeaderSelect value={hod.id} onChange={setHodId} options={list.map((h) => h.id)} />
        <HeaderSelect value={period} onChange={setPeriod} options={['This Month', 'Last Month', 'This Quarter']} />
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
      </DashboardHero>

      {/* Identity bar */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm px-4 py-3 flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-2.5">
          <span className="w-9 h-9 rounded-xl text-white font-bold text-[12px] flex items-center justify-center" style={{ background: 'var(--avatar-bg)' }}>
            {hod.name.split(' ').map((x) => x[0]).join('')}
          </span>
          <span className="text-[14px] font-extrabold tracking-tight">{hod.name}</span>
        </div>
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-muted)]"><IdCard size={14} /> {hod.id}</span>
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-muted)]"><Building2 size={14} /> {hod.company}</span>
        <span className="inline-flex items-center text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded-md bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">{hod.role}</span>
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-muted)]"><Mail size={14} /> {hod.email}</span>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Activity Scoring */}
      <Section title="Activity Scoring — Per Activity × Month" subtitle="Completion & score per governance ritual" icon={Target}>
        {hod.scoring.length === 0 ? (
          <div className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No activities tracked this period.</div>
        ) : (
          <TableShell minWidth={860}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Month</Th><Th>Activity</Th><Th align="center">Completed</Th><Th align="center">Total</Th>
                <Th align="center">Missed</Th><Th align="center">Pending</Th><Th align="center">Score</Th><Th align="center">%</Th>
              </tr>
            </thead>
            <tbody>
              {hod.scoring.map((r, i) => {
                const pct = r.total ? Math.round((r.completed / r.total) * 100) : 0;
                return (
                  <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.month}</Td>
                    <Td className="font-medium">{r.activity}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-green)]">{r.completed}</Td>
                    <Td align="center" className="tabular-nums">{r.total}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.missed}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-orange)]">{r.pending}</Td>
                    <Td align="center" className="font-extrabold" style={{ color: scoreColor(r.score) }}>{r.score}</Td>
                    <Td align="center" className="font-extrabold tabular-nums">{pct}%</Td>
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
        )}
      </Section>

      {/* Activity Tracker — Occurrences */}
      <Section title="Activity Tracker — Occurrences" subtitle="Every scheduled occurrence and its outcome" icon={ListChecks}>
        {hod.occ.length === 0 ? (
          <div className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No tracked occurrences this period.</div>
        ) : (
          <TableShell minWidth={640}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Date</Th><Th>Month</Th><Th>Activity</Th><Th align="center">Status</Th>
              </tr>
            </thead>
            <tbody>
              {hod.occ.map((r, i) => (
                <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`tabular-nums font-bold ${stickyCell}`}>{r.date}</Td>
                  <Td className="text-[var(--text-muted)]">{r.month}</Td>
                  <Td className="font-medium">{r.activity}</Td>
                  <Td align="center"><OccPill v={r.status} /></Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>

      {/* Needs Attention */}
      <Section title="Needs Attention" subtitle={hod.needs.length ? `${hod.needs.length} item${hod.needs.length > 1 ? 's' : ''}` : 'On track'} icon={AlertTriangle} tone="red">
        {hod.needs.length === 0 ? (
          <div className="flex items-center gap-2.5 px-5 py-6">
            <span className="w-8 h-8 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] flex items-center justify-center"><CheckCircle2 size={16} /></span>
            <p className="text-[13px] font-bold text-[var(--accent-green)]">Nothing urgent. On track.</p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {hod.needs.map((t, i) => (
              <div key={i} className="flex items-start gap-3 px-5 py-3.5 hover:bg-[var(--table-hover)] transition-colors">
                <span className="w-6 h-6 rounded-lg bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center mt-0.5 shrink-0"><AlertTriangle size={13} /></span>
                <span className="text-[12.5px] font-medium">{t}</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Open Action Items */}
      <Section title="Open Action Items" subtitle={hod.actions.length ? `${hod.actions.length} open` : 'Nothing open'} icon={ClipboardList}>
        {hod.actions.length === 0 ? (
          <div className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No open action items.</div>
        ) : (
          <TableShell minWidth={980}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Emp ID</Th><Th>Target Date</Th>
                <Th align="center">Status</Th><Th>Client Delay</Th><Th>OM Delay</Th><Th>Follow-up</Th>
              </tr>
            </thead>
            <tbody>
              {hod.actions.map((r, i) => (
                <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>{r.activity}</Td>
                  <Td>{r.action}</Td>
                  <Td className="text-[var(--text-muted)]">{r.owner}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.emp}</Td>
                  <Td className="tabular-nums">{r.target}</Td>
                  <Td align="center"><span className="text-[10.5px] font-bold px-2 py-1 rounded-full" style={{ color: r.status === 'Overdue' ? 'var(--accent-red)' : 'var(--accent-orange)', background: r.status === 'Overdue' ? 'var(--accent-red-bg)' : 'var(--accent-orange-bg)' }}>{r.status}</span></Td>
                  <Td className="font-bold" style={{ color: r.clientDelay === 'On-track' ? 'var(--accent-green)' : r.clientDelay === 'Delayed' ? 'var(--accent-red)' : 'var(--accent-orange)' }}>{r.clientDelay}</Td>
                  <Td className="font-bold" style={{ color: r.omDelay === 'On-track' ? 'var(--accent-green)' : r.omDelay === 'Delayed' ? 'var(--accent-red)' : 'var(--accent-orange)' }}>{r.omDelay}</Td>
                  <Td className="text-[var(--text-muted)]">{r.followup}</Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>
    </div>
  );
};

export default HodView;
