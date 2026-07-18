import React, { useMemo, useState } from 'react';
import {
  RefreshCw, Building2, Target, Gauge, CheckCircle2, ClipboardList, Star,
  ListChecks, AlertTriangle,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, Progress, TableShell, KpiTile,
} from '../../common/dashboardKit';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Client View — the "Client Dashboard" for a single
   client: an activity scorecard (success measures) + pending actions.
   Layout modelled on the reference; all data is placeholder mock.
   ───────────────────────────────────────────────────────────── */

const CLIENTS = ['Acme Corp', 'Nimbus Ltd', 'Vertex Health', 'Orbit Media'];

/* Per-client success-measures scorecard. */
const SCORECARD = {
  'Acme Corp': [
    { activity: 'Org Structure Rollout',   implTarget: 100, actualImpl: 100, scoreTarget: 90, actualScore: 88 },
    { activity: 'DRM / KPI Sign-off',       implTarget: 100, actualImpl: 90,  scoreTarget: 85, actualScore: 80 },
    { activity: 'Weekly Review Meetings',   implTarget: 100, actualImpl: 75,  scoreTarget: 80, actualScore: 68 },
    { activity: 'Culture Rating Survey',    implTarget: 100, actualImpl: 100, scoreTarget: 75, actualScore: 79 },
  ],
  'Nimbus Ltd': [
    { activity: 'Org Structure Rollout',   implTarget: 100, actualImpl: 100, scoreTarget: 90, actualScore: 84 },
    { activity: 'DRM / KPI Sign-off',       implTarget: 100, actualImpl: 60,  scoreTarget: 85, actualScore: 55 },
    { activity: 'Weekly Review Meetings',   implTarget: 100, actualImpl: 50,  scoreTarget: 80, actualScore: 44 },
  ],
  'Vertex Health': [
    { activity: 'Org Structure Rollout',   implTarget: 100, actualImpl: 100, scoreTarget: 90, actualScore: 92 },
    { activity: 'DRM / KPI Sign-off',       implTarget: 100, actualImpl: 100, scoreTarget: 85, actualScore: 88 },
    { activity: 'Monthly MMR',              implTarget: 100, actualImpl: 100, scoreTarget: 82, actualScore: 84 },
    { activity: 'Impact Studies',           implTarget: 100, actualImpl: 95,  scoreTarget: 80, actualScore: 81 },
  ],
  'Orbit Media': [
    { activity: 'Org Structure Rollout',   implTarget: 100, actualImpl: 80,  scoreTarget: 90, actualScore: 62 },
    { activity: 'Calendar Discipline',      implTarget: 100, actualImpl: 40,  scoreTarget: 80, actualScore: 35 },
    { activity: 'Weekly Review Meetings',   implTarget: 100, actualImpl: 55,  scoreTarget: 80, actualScore: 48 },
  ],
};

const PENDING = {
  'Acme Corp':     [{ activity: 'DRM', action: 'Sign-off DRM/KPI', owner: 'Priya S.', target: '2026-07-22', status: 'Pending', learnerDelay: 'On-track', staffDelay: 'On-track' }],
  'Nimbus Ltd':    [
    { activity: 'WRM', action: 'Follow up: WRM',       owner: 'Megha M.', target: '2026-07-17', status: 'Overdue', learnerDelay: 'Delayed',  staffDelay: 'Delayed' },
    { activity: 'DRM', action: 'Collect KPI sheets',   owner: 'Rahul V.', target: '2026-07-20', status: 'Pending', learnerDelay: 'Pending',  staffDelay: 'On-track' },
  ],
  'Vertex Health': [],
  'Orbit Media':   [
    { activity: 'Cal Disc', action: 'Schedule cadence', owner: 'P. Shah', target: '2026-07-18', status: 'Overdue', learnerDelay: 'Delayed', staffDelay: 'Pending' },
  ],
};

const achievement = (r) => Math.round(((r.actualImpl / r.implTarget) * 0.5 + (r.actualScore / r.scoreTarget) * 0.5) * 100);
const statusOf = (a) => (a >= 90 ? 'On Track' : a >= 70 ? 'Watch' : 'Behind');

const STATUS_STYLE = {
  'On Track': { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  'Watch':    { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  'Behind':   { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
};

const Pill = ({ label }) => {
  const s = STATUS_STYLE[label] || STATUS_STYLE.Watch;
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{label}
    </span>
  );
};

const delayColor = (v) => (v === 'On-track' ? 'var(--accent-green)' : v === 'Delayed' ? 'var(--accent-red)' : 'var(--accent-orange)');

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const ClientView = () => {
  const [client, setClient] = useState(CLIENTS[0]);
  const [period, setPeriod] = useState('This Month');

  const rows = SCORECARD[client] || [];
  const pending = PENDING[client] || [];

  const summary = useMemo(() => {
    const achs = rows.map(achievement);
    const avgAch = achs.length ? Math.round(achs.reduce((a, b) => a + b, 0) / achs.length) : 0;
    const onTrack = achs.filter((a) => a >= 90).length;
    const avgScore = rows.length ? Math.round(rows.reduce((a, r) => a + r.actualScore, 0) / rows.length) : 0;
    return { total: rows.length, avgAch, onTrack, avgScore, pending: pending.length };
  }, [rows, pending]);

  const kpis = [
    { value: summary.total,        label: 'Activities',     sub: 'Tracked',        tone: 'blue',   icon: ListChecks },
    { value: `${summary.avgAch}%`, label: 'Avg Achievement',sub: 'Impl + Score',   tone: summary.avgAch >= 80 ? 'green' : 'yellow', icon: Target },
    { value: summary.onTrack,      label: 'On Track',       sub: '≥ 90% achieved',  tone: 'green',  icon: CheckCircle2 },
    { value: `${summary.avgScore}%`, label: 'Avg Score',    sub: 'Actual score',    tone: 'green',  icon: Star },
    { value: summary.pending,      label: 'Pending Actions',sub: 'Open items',      tone: summary.pending ? 'red' : 'plain', icon: ClipboardList },
    { value: `${period}`,          label: 'Period',         sub: 'Reporting window',tone: 'plain',  icon: Gauge },
  ];

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={Building2} title="Client Dashboard" highlight={client} subtitle="Activity scorecard & success measures for the selected client">
        <HeaderSelect value={client} onChange={setClient} options={CLIENTS} />
        <HeaderSelect value={period} onChange={setPeriod} options={['This Month', 'Last Month', 'This Quarter']} />
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
      </DashboardHero>

      {/* Summary tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Activity Scorecard — Success Measures */}
      <Section title="Activity Scorecard — Success Measures" subtitle="Implementation vs. score performance per activity" icon={Target}
        action={<span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{rows.length} activities</span>}>
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
            {rows.map((r, i) => {
              const ach = achievement(r);
              return (
                <tr key={r.activity} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className="text-[var(--text-muted)] font-bold">{i + 1}</Td>
                  <Td className="font-bold">{r.activity}</Td>
                  <Td align="center" className="tabular-nums text-[var(--text-muted)]">{r.implTarget}%</Td>
                  <Td align="center" className="tabular-nums font-bold">{r.actualImpl}%</Td>
                  <Td align="center" className="tabular-nums text-[var(--text-muted)]">{r.scoreTarget}%</Td>
                  <Td align="center" className="tabular-nums font-bold">{r.actualScore}%</Td>
                  <Td align="center" className="font-extrabold">{ach}%</Td>
                  <Td><Progress value={ach} /></Td>
                  <Td align="center"><Pill label={statusOf(ach)} /></Td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td colSpan={9} className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No activities for this client.</td></tr>
            )}
          </tbody>
        </TableShell>
      </Section>

      {/* Pending Actions */}
      <Section title="Pending Actions" subtitle={pending.length ? `${pending.length} open item${pending.length > 1 ? 's' : ''}` : 'Nothing pending'} icon={AlertTriangle} tone="red">
        {pending.length === 0 ? (
          <div className="flex items-center gap-2.5 px-5 py-6">
            <span className="w-8 h-8 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] flex items-center justify-center"><CheckCircle2 size={16} /></span>
            <p className="text-[13px] font-bold text-[var(--accent-green)]">No pending actions for {client}.</p>
          </div>
        ) : (
          <TableShell minWidth={820}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Target Date</Th>
                <Th align="center">Status</Th><Th>Learner Delay</Th><Th>Staff Delay</Th>
              </tr>
            </thead>
            <tbody>
              {pending.map((r, i) => (
                <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>{r.activity}</Td>
                  <Td>{r.action}</Td>
                  <Td className="text-[var(--text-muted)]">{r.owner}</Td>
                  <Td className="tabular-nums">{r.target}</Td>
                  <Td align="center">
                    <span className="text-[10.5px] font-bold px-2 py-1 rounded-full" style={{
                      color: r.status === 'Overdue' ? 'var(--accent-red)' : 'var(--accent-orange)',
                      background: r.status === 'Overdue' ? 'var(--accent-red-bg)' : 'var(--accent-orange-bg)',
                    }}>{r.status}</span>
                  </Td>
                  <Td className="font-bold" style={{ color: delayColor(r.learnerDelay) }}>{r.learnerDelay}</Td>
                  <Td className="font-bold" style={{ color: delayColor(r.staffDelay) }}>{r.staffDelay}</Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>
    </div>
  );
};

export default ClientView;
