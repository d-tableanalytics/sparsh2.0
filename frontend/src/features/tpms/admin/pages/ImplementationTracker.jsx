import React, { useMemo, useState } from 'react';
import {
  RefreshCw, GitBranch, CheckCircle2, CircleDashed, XCircle, Gauge, Target,
  Info, Grid3x3, MousePointerClick,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, Progress, TableShell, KpiTile,
} from '../../common/dashboardKit';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Implementation Tracker — per-client activity scorecard
   + client × activity score matrix. Layout modelled on the reference;
   all data is placeholder mock.

   Scoring model:
     • Impl. Target %  = 100 (default cadence expectation)
     • Actual Impl. %  = 100 if the occurrence happened this period, else 0
     • Achievement %   = Actual Score ÷ Score Target × 100
     • Status          = Met ≥100% · Partial 50–99% · Not Met <50%
   ───────────────────────────────────────────────────────────── */

const ACTIVITIES = [
  'Org Str', 'DRM/KPI', 'Cal Disc', 'WRM', 'MMR', '1-Pager', 'Action Closure',
  'A&O Rtg', 'Cult Rtg', 'RRO', 'Imp Stats', 'TEI', 'CSI', 'ORM',
];
const TARGET = [90, 85, 80, 80, 82, 80, 85, 88, 75, 80, 80, 82, 80, 85];

const CLIENTS = [
  { name: 'Acme Corp',     om: 'R. Mehta',  scores: [88, 80, 68, 79, 84, 60, 72, 90, 85, 70, 66, 78, 82, 74] },
  { name: 'Nimbus Ltd',    om: 'S. Kapoor', scores: [84, 55, 44, 60, 70, 40, 50, 62, 58, 48, 45, 66, 55, 52] },
  { name: 'Vertex Health', om: 'A. Nair',   scores: [92, 88, 84, 90, 86, 82, 88, 94, 90, 80, 85, 89, 91, 87] },
  { name: 'Orbit Media',   om: 'P. Shah',   scores: [62, 35, 48, 40, 55, 30, 42, 50, 45, 38, 33, 47, 44, 41] },
];

const rowsForClient = (c) => ACTIVITIES.map((activity, i) => {
  const actualScore = c.scores[i];
  const scoreTarget = TARGET[i];
  const actualImpl = actualScore >= 40 ? 100 : 0;                 // occurrence completed? 100 : 0
  const achievement = Math.round((actualScore / scoreTarget) * 100);
  return { activity, implTarget: 100, actualImpl, scoreTarget, actualScore, achievement };
});

const statusOf = (a) => (a >= 100 ? 'Met' : a >= 50 ? 'Partial' : 'Not Met');
const STATUS = {
  'Met':     { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  'Partial': { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  'Not Met': { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
};
const Pill = ({ label }) => {
  const s = STATUS[label];
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{label}
    </span>
  );
};
const scoreColor = (v) => (v >= 80 ? 'var(--accent-green)' : v >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)');

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const ImplementationTracker = () => {
  const [clientName, setClientName] = useState('All Clients');
  const [om, setOm] = useState('All OMs');
  const [period, setPeriod] = useState('Jul 2026');

  const isAll = clientName === 'All Clients';
  const selected = CLIENTS.find((c) => c.name === clientName);

  // KPI tiles: for a selected client → its 14 activities; for All → every client×activity.
  const allRows = useMemo(() => {
    if (selected) return rowsForClient(selected);
    return CLIENTS.flatMap(rowsForClient);
  }, [selected]);

  const stats = useMemo(() => {
    const total = allRows.length;
    const done = allRows.filter((r) => statusOf(r.achievement) === 'Met').length;
    const partial = allRows.filter((r) => statusOf(r.achievement) === 'Partial').length;
    const notDone = allRows.filter((r) => statusOf(r.achievement) === 'Not Met').length;
    const avg = total ? Math.round(allRows.reduce((a, r) => a + r.actualScore, 0) / total) : 0;
    return { total, done, partial, notDone, avg };
  }, [allRows]);

  const matrix = om === 'All OMs' ? CLIENTS : CLIENTS.filter((c) => c.om === om);

  const kpis = [
    { value: `${stats.done}/${stats.total}`,    label: 'Activity Done',  sub: 'Met ≥100%',       tone: 'green',  icon: CheckCircle2 },
    { value: `${stats.partial}/${stats.total}`, label: 'Partially Done', sub: 'Partial 50–99%',  tone: 'yellow', icon: CircleDashed },
    { value: `${stats.notDone}/${stats.total}`, label: 'Not Done',       sub: 'Not Met <50%',    tone: 'red',    icon: XCircle },
    { value: `${stats.avg}%`,                   label: 'Avg Score',      sub: 'Across activities',tone: 'blue',  icon: Gauge },
    { value: '100%',                            label: 'Target',         sub: 'Default cadence',  tone: 'blue',   icon: Target },
  ];

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={GitBranch} title="Implementation Tracker" highlight={clientName} subtitle="Deployment scoring across success measures">
        <HeaderSelect value={period} onChange={setPeriod} options={['Jul 2026', 'Jun 2026', 'Q2 2026']} />
        <HeaderSelect value={om} onChange={setOm} options={['All OMs', 'R. Mehta', 'S. Kapoor', 'A. Nair', 'P. Shah']} />
        <HeaderSelect value={clientName} onChange={setClientName} options={['All Clients', ...CLIENTS.map((c) => c.name)]} />
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
      </DashboardHero>

      {/* Scoring legend */}
      <div className="rounded-2xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-4 py-3 flex items-start gap-2.5">
        <span className="w-7 h-7 rounded-lg bg-[var(--bg-card)] text-[var(--accent-orange)] flex items-center justify-center shrink-0 shadow-sm"><Info size={15} /></span>
        <p className="text-[12px] font-medium text-[var(--text-main)] leading-relaxed">
          <b>Impl. Target</b> = 100% default · <b>Actual Impl. %</b> = 100 if the occurrence completed this period, else 0 ·
          <b> Achievement %</b> = Actual Score ÷ Score Target × 100 —
          <span className="text-[var(--accent-green)] font-bold"> Met ≥100%</span> ·
          <span className="text-[var(--accent-orange)] font-bold"> Partial 50–99%</span> ·
          <span className="text-[var(--accent-red)] font-bold"> Not Met &lt;50%</span>.
        </p>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Activity Scorecard */}
      <Section title="Activity Scorecard" subtitle={selected ? `Success measures for ${selected.name}` : 'Detailed success measures & uploads'} icon={Target}
        action={selected && <span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{allRows.length} activities</span>}>
        {!selected ? (
          <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center"><MousePointerClick size={22} /></span>
            <p className="text-[13px] font-bold">Select a client to view its scorecard</p>
            <p className="text-[12px] text-[var(--text-muted)]">Pick a client from the header to see detailed success measures & uploads.</p>
          </div>
        ) : (
          <TableShell minWidth={980}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>#</Th><Th>Activity Name</Th>
                <Th align="center">Impl. Target %</Th><Th align="center">Actual Impl. %</Th>
                <Th align="center">Score Target %</Th><Th align="center">Actual Score %</Th>
                <Th align="center">Achievement %</Th><Th>Progress</Th><Th align="center">Status</Th>
              </tr>
            </thead>
            <tbody>
              {allRows.map((r, i) => (
                <tr key={r.activity} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className="text-[var(--text-muted)] font-bold">{i + 1}</Td>
                  <Td className="font-bold">{r.activity}</Td>
                  <Td align="center" className="tabular-nums text-[var(--text-muted)]">{r.implTarget}%</Td>
                  <Td align="center" className="tabular-nums font-bold" style={{ color: r.actualImpl ? 'var(--accent-green)' : 'var(--accent-red)' }}>{r.actualImpl}%</Td>
                  <Td align="center" className="tabular-nums text-[var(--text-muted)]">{r.scoreTarget}%</Td>
                  <Td align="center" className="tabular-nums font-bold">{r.actualScore}%</Td>
                  <Td align="center" className="font-extrabold">{r.achievement}%</Td>
                  <Td><Progress value={Math.min(r.achievement, 100)} /></Td>
                  <Td align="center"><Pill label={statusOf(r.achievement)} /></Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>

      {/* Client × Activity Score Matrix */}
      <Section title="Client × Activity Score Matrix" subtitle="Actual score % per activity, all clients" icon={Grid3x3}
        action={<span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{matrix.length} clients</span>}>
        <TableShell minWidth={1240}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Client</Th><Th>OM</Th>
              {ACTIVITIES.map((a) => <Th key={a} align="center">{a}</Th>)}
            </tr>
          </thead>
          <tbody>
            {matrix.map((c) => (
              <tr key={c.name} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                <Td className={`font-bold ${stickyCell}`}>{c.name}</Td>
                <Td className="text-[var(--text-muted)]">{c.om}</Td>
                {c.scores.map((s, i) => (
                  <Td key={i} align="center" className="tabular-nums font-bold" style={{ color: scoreColor(s) }}>{s}%</Td>
                ))}
              </tr>
            ))}
          </tbody>
        </TableShell>
      </Section>
    </div>
  );
};

export default ImplementationTracker;
