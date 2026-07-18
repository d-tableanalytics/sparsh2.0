import React, { useState } from 'react';
import {
  RefreshCw, LayoutDashboard, CalendarDays, Medal, Building2, CalendarClock, CalendarX,
  Users, ClipboardList, CheckCircle2, Target, Timer, ClipboardCheck, AlertTriangle,
  Star, Sparkles, FileCheck, Trophy, Activity, Grid3x3, XCircle, Clock,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, Th, Td, Trend, StatusBadge, Progress, Fraction,
  KpiTile, HeaderSelect, TableShell,
} from '../../common/dashboardKit';

/* ─────────────────────────────────────────────────────────────
   Admin View — high-level operational dashboard (ERP-grade).
   ALL data below is placeholder mock. Colours use Sparsh tokens.
   ───────────────────────────────────────────────────────────── */

const KPIS = [
  { value: '12',  label: 'Total Clients',      sub: 'Active',                tone: 'blue',   icon: Building2 },
  { value: '8',   label: 'Planned Clients',    sub: 'Have activity',         tone: 'green',  icon: CalendarClock },
  { value: '4',   label: 'Unplanned Clients',  sub: 'No activity scheduled', tone: 'plain',  icon: CalendarX },
  { value: '5',   label: 'Total OMs',          sub: 'Across teams',          tone: 'blue',   icon: Users },
  { value: '26',  label: 'Planned Activities', sub: 'This period',           tone: 'yellow', icon: ClipboardList },
  { value: '18',  label: 'Completed',          sub: 'Activities done',       tone: 'green',  icon: CheckCircle2 },
  { value: '74%', label: 'Overall Completion', sub: 'vs 90% target',         tone: 'green',  icon: Target },
  { value: '2',   label: 'Avg Delay Days',     sub: 'Days past deadline',    tone: 'yellow', icon: Timer },
  { value: '61%', label: 'Action Closure',     sub: 'vs 95% target',         tone: 'yellow', icon: ClipboardCheck },
  { value: '3',   label: 'Active Escalations', sub: 'Need OM action',        tone: 'red',    icon: AlertTriangle },
  { value: '82%', label: 'O&A Rating',         sub: 'HODs accountability',   tone: 'green',  icon: Star },
  { value: '78%', label: 'Culture Score',      sub: 'Overall score',         tone: 'green',  icon: Sparkles },
  { value: '69%', label: 'DRM Completion',     sub: 'HODs signed-off',       tone: 'green',  icon: FileCheck },
  { value: '80%', label: 'Success Score',      sub: 'Overall avg',           tone: 'green',  icon: Trophy },
];

const CLIENT_HEALTH = [
  { client: 'Acme Corp',     om: 'R. Mehta',  done: 14, pending: 3, overdue: 1, comp: 78, actCls: 62, delay: 1, esc: 0, trend: 'up',   status: 'HEALTHY' },
  { client: 'Nimbus Ltd',    om: 'S. Kapoor', done: 9,  pending: 5, overdue: 2, comp: 64, actCls: 48, delay: 3, esc: 1, trend: 'down', status: 'AT-RISK' },
  { client: 'Vertex Health', om: 'A. Nair',   done: 21, pending: 2, overdue: 0, comp: 88, actCls: 74, delay: 0, esc: 0, trend: 'up',   status: 'HEALTHY' },
  { client: 'Orbit Media',   om: 'P. Shah',   done: 6,  pending: 4, overdue: 3, comp: 52, actCls: 40, delay: 5, esc: 2, trend: 'down', status: 'AT-RISK' },
];

const OM_PERF = [
  { om: 'A. Nair',   clients: 4, planned: 12, completed: 10, comp: 86, delay: 0, actCls: 74, esc: 0, trend: 'up' },
  { om: 'R. Mehta',  clients: 5, planned: 14, completed: 11, comp: 78, delay: 1, actCls: 62, esc: 1, trend: 'up' },
  { om: 'S. Kapoor', clients: 3, planned: 9,  completed: 6,  comp: 64, delay: 3, actCls: 48, esc: 1, trend: 'down' },
];

const DELAYED = [
  { client: 'Orbit Media', om: 'P. Shah',   delay: 5, overdue: 3, comp: 52, status: 'AT-RISK' },
  { client: 'Nimbus Ltd',  om: 'S. Kapoor', delay: 3, overdue: 2, comp: 64, status: 'AT-RISK' },
];

const ACTIVITY_STATUS = [
  { value: '26', label: 'Planned',     sub: 'This period',    tone: 'yellow', icon: CalendarClock },
  { value: '18', label: 'Completed',   sub: 'Activities done',tone: 'green',  icon: CheckCircle2 },
  { value: '2',  label: 'Lapsed',      sub: 'Auto-lapsed',    tone: 'red',    icon: XCircle },
  { value: '1',  label: 'Rescheduled', sub: 'Moved',          tone: 'blue',   icon: CalendarDays },
];

const ACTIVITY_MATRIX = [
  { client: 'Acme Corp',     org: '1/1', drm: '1/1', cal: '1/1', wrm: '1/1', mmr: '1/1', pager: '0/1', action: '1/1', done: 14 },
  { client: 'Nimbus Ltd',    org: '1/1', drm: '0/1', cal: '1/1', wrm: '0/1', mmr: '1/1', pager: '0/1', action: '0/1', done: 9  },
  { client: 'Vertex Health', org: '1/1', drm: '1/1', cal: '1/1', wrm: '1/1', mmr: '1/1', pager: '1/1', action: '1/1', done: 21 },
];

const OPEN_ACTIONS = [
  { client: 'Nimbus Ltd',  activity: 'WRM', action: 'Follow up: WRM', owner: 'Megha M.', emp: 'EMP-170', target: '2026-07-17', actual: '—', status: 'Pending', clientDelay: 'Pending',  omDelay: 'Overdue' },
  { client: 'Orbit Media', activity: 'MMR', action: 'Schedule MMR',   owner: 'Rahul V.', emp: 'EMP-204', target: '2026-07-19', actual: '—', status: 'Pending', clientDelay: 'On-track', omDelay: 'Pending' },
];

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const AdminView = () => {
  const [tab, setTab] = useState('dashboard');
  const [period, setPeriod] = useState('Jul 2026');
  const [om, setOm] = useState('All OMs');
  const [client, setClient] = useState('All Clients');

  return (
    <div className="space-y-5">
      {/* Hero header */}
      <DashboardHero icon={LayoutDashboard} title="Admin Dashboard" subtitle="Operational command centre across all OMs and clients">
        <HeaderSelect value={period} onChange={setPeriod} options={['Jul 2026', 'Jun 2026', 'Q2 2026']} />
        <HeaderSelect value={om} onChange={setOm} options={['All OMs', 'R. Mehta', 'S. Kapoor', 'A. Nair']} />
        <HeaderSelect value={client} onChange={setClient} options={['All Clients', 'Acme Corp', 'Nimbus Ltd', 'Vertex Health']} />
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
      </DashboardHero>

      {/* Tabs */}
      <div className="flex items-center gap-2">
        {[
          { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
          { key: 'calendar',  label: 'Client-wise Calendar', icon: CalendarDays },
        ].map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-bold transition-all border
              ${tab === t.key ? 'text-white border-transparent shadow-sm' : 'text-[var(--text-muted)] border-[var(--border)] bg-[var(--bg-card)] hover:bg-[var(--input-bg)]'}`}
            style={tab === t.key ? { background: 'var(--btn-primary)' } : undefined}>
            <t.icon size={15} /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'calendar' ? (
        <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--bg-card)] py-20 text-center">
          <CalendarDays size={28} className="mx-auto text-[var(--text-muted)]" />
          <p className="text-[13px] font-bold mt-3">Client-wise Calendar</p>
          <p className="text-[12px] text-[var(--text-muted)] mt-1">Calendar view coming next.</p>
        </div>
      ) : (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
            {KPIS.map((k) => <KpiTile key={k.label} {...k} />)}
          </div>

          {/* Client Health Matrix */}
          <Section title="Client Health Matrix" subtitle="Delivery health per client with trend & risk" icon={Activity}>
            <TableShell minWidth={980}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th className={stickyHead}>Client</Th><Th>OM</Th><Th align="center">Done</Th><Th align="center">Pending</Th>
                  <Th align="center">Overdue</Th><Th align="center">Completion</Th><Th>Progress</Th>
                  <Th align="center">Action Cls</Th><Th align="center">Avg Delay</Th><Th align="center">Esc</Th><Th align="center">Trend</Th><Th align="center">Status</Th>
                </tr>
              </thead>
              <tbody>
                {CLIENT_HEALTH.map((r) => (
                  <tr key={r.client} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.client}</Td>
                    <Td className="text-[var(--text-muted)]">{r.om}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-green)]">{r.done}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-orange)]">{r.pending}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.overdue}</Td>
                    <Td align="center" className="font-extrabold">{r.comp}%</Td>
                    <Td><Progress value={r.comp} /></Td>
                    <Td align="center" className="font-bold">{r.actCls}%</Td>
                    <Td align="center" className="tabular-nums">{r.delay}</Td>
                    <Td align="center" className="tabular-nums">{r.esc}</Td>
                    <Td align="center"><Trend dir={r.trend} /></Td>
                    <Td align="center"><StatusBadge value={r.status} /></Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
          </Section>

          {/* OM Performance Comparison */}
          <Section title="OM Performance Comparison" subtitle="Ranked by completion this period" icon={Trophy}>
            <TableShell minWidth={860}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th align="center">Rank</Th><Th className={stickyHead}>OM</Th><Th align="center">Clients</Th><Th align="center">Planned</Th>
                  <Th align="center">Completed</Th><Th align="center">Completion</Th><Th>Progress</Th>
                  <Th align="center">Avg Delay</Th><Th align="center">Action Cls</Th><Th align="center">Esc</Th><Th align="center">Trend</Th>
                </tr>
              </thead>
              <tbody>
                {OM_PERF.map((r, i) => (
                  <tr key={r.om} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td align="center">
                      {i === 0
                        ? <Medal size={18} className="inline" style={{ color: '#f59e0b' }} />
                        : <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-[var(--input-bg)] text-[var(--text-muted)] font-bold text-[11px]">{i + 1}</span>}
                    </Td>
                    <Td className={`font-bold ${stickyCell}`}>{r.om}</Td>
                    <Td align="center" className="tabular-nums">{r.clients}</Td>
                    <Td align="center" className="tabular-nums">{r.planned}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-green)]">{r.completed}</Td>
                    <Td align="center" className="font-extrabold">{r.comp}%</Td>
                    <Td><Progress value={r.comp} /></Td>
                    <Td align="center" className="tabular-nums">{r.delay}d</Td>
                    <Td align="center" className="font-bold">{r.actCls}%</Td>
                    <Td align="center" className="tabular-nums">{r.esc}</Td>
                    <Td align="center"><Trend dir={r.trend} /></Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
          </Section>

          {/* Top Delayed Clients */}
          <Section title="Top Delayed Clients" subtitle="Clients needing immediate attention" icon={Clock} tone="red">
            <TableShell minWidth={720}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th className={stickyHead}>Client</Th><Th>OM</Th><Th align="center">Avg Delay (days)</Th><Th align="center">Overdue</Th><Th align="center">Completion</Th><Th align="center">Status</Th>
                </tr>
              </thead>
              <tbody>
                {DELAYED.map((r) => (
                  <tr key={r.client} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.client}</Td>
                    <Td className="text-[var(--text-muted)]">{r.om}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.delay}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.overdue}</Td>
                    <Td align="center" className="font-extrabold">{r.comp}%</Td>
                    <Td align="center"><StatusBadge value={r.status} /></Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
          </Section>

          {/* OM Clients — Activity Status */}
          <Section title="OM Clients — Activity Status" subtitle="Cadence completion across governance rituals" icon={Grid3x3}>
            <div className="p-4 grid grid-cols-2 xl:grid-cols-4 gap-3">
              {ACTIVITY_STATUS.map((s) => <KpiTile key={s.label} {...s} />)}
            </div>
            <TableShell minWidth={860}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-y border-[var(--border)]">
                  <Th className={stickyHead}>Client</Th><Th align="center">Org Str</Th><Th align="center">DRM/KPI</Th><Th align="center">Cal Disc</Th>
                  <Th align="center">WRM</Th><Th align="center">MMR</Th><Th align="center">1-Pager</Th><Th align="center">Action Cls</Th><Th align="center">Done</Th>
                </tr>
              </thead>
              <tbody>
                {ACTIVITY_MATRIX.map((r) => (
                  <tr key={r.client} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.client}</Td>
                    <Td align="center"><Fraction v={r.org} /></Td>
                    <Td align="center"><Fraction v={r.drm} /></Td>
                    <Td align="center"><Fraction v={r.cal} /></Td>
                    <Td align="center"><Fraction v={r.wrm} /></Td>
                    <Td align="center"><Fraction v={r.mmr} /></Td>
                    <Td align="center"><Fraction v={r.pager} /></Td>
                    <Td align="center"><Fraction v={r.action} /></Td>
                    <Td align="center" className="font-extrabold text-[var(--accent-green)]">{r.done}</Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
          </Section>

          {/* Open Action Items */}
          <Section title="Open Action Items — My Clients" subtitle="Pending follow-ups & closures" icon={ClipboardList}>
            <TableShell minWidth={940}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th className={stickyHead}>Client</Th><Th>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Emp ID</Th>
                  <Th>Target Date</Th><Th>Actual Date</Th><Th align="center">Status</Th><Th>Client Delay</Th><Th>OM Delay</Th>
                </tr>
              </thead>
              <tbody>
                {OPEN_ACTIONS.map((r, i) => (
                  <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.client}</Td>
                    <Td className="text-[var(--text-muted)]">{r.activity}</Td>
                    <Td>{r.action}</Td>
                    <Td className="text-[var(--text-muted)]">{r.owner}</Td>
                    <Td className="tabular-nums text-[var(--text-muted)]">{r.emp}</Td>
                    <Td className="tabular-nums">{r.target}</Td>
                    <Td className="text-[var(--text-muted)]">{r.actual}</Td>
                    <Td align="center"><span className="text-[10.5px] font-bold px-2 py-1 rounded-full" style={{ color: 'var(--accent-orange)', background: 'var(--accent-orange-bg)' }}>{r.status}</span></Td>
                    <Td className="font-bold" style={{ color: r.clientDelay === 'On-track' ? 'var(--accent-green)' : 'var(--accent-orange)' }}>{r.clientDelay}</Td>
                    <Td className="font-bold" style={{ color: r.omDelay === 'Overdue' ? 'var(--accent-red)' : 'var(--accent-orange)' }}>{r.omDelay}</Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
          </Section>
        </>
      )}
    </div>
  );
};

export default AdminView;
