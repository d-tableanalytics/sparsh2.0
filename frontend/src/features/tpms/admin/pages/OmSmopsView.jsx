import React, { useMemo, useState } from 'react';
import {
  RefreshCw, Briefcase, Users, CalendarClock, CheckCircle2, Clock,
  AlertOctagon, Target, Timer, ClipboardCheck, AlertTriangle,
} from 'lucide-react';
import { DashboardHero, HeaderSelect, HeroButton } from '../../common/dashboardKit';
import OmDashboardBody from '../../common/OmDashboardBody';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ OM (SMOps) View — the admin's window into SMOps
   operations. Layout modelled on the reference; all data is mock.
   Header lets the admin scope by OM + period.
   ───────────────────────────────────────────────────────────── */

const MATRIX = [
  { om: 'R. Mehta',  client: 'Acme Corp',     org: '1/1', drm: '1/1', cal: '1/1', wrm: '1/1', mmr: '1/1', pager: '1/1', action: '1/1', aoRtg: '1/1', cultRtg: '1/1', done: 14 },
  { om: 'S. Kapoor', client: 'Nimbus Ltd',    org: '1/1', drm: '0/1', cal: '1/1', wrm: '0/1', mmr: '1/1', pager: '0/1', action: '0/1', aoRtg: '0/1', cultRtg: '1/1', done: 9  },
  { om: 'A. Nair',   client: 'Vertex Health', org: '1/1', drm: '1/1', cal: '1/1', wrm: '1/1', mmr: '1/1', pager: '1/1', action: '1/1', aoRtg: '1/1', cultRtg: '1/1', done: 21 },
  { om: 'P. Shah',   client: 'Orbit Media',   org: '1/1', drm: '0/1', cal: '0/1', wrm: '0/1', mmr: '1/1', pager: '0/1', action: '0/1', aoRtg: '0/1', cultRtg: '0/1', done: 6  },
];

const FIGURES = {
  'R. Mehta':  { clients: 1, planned: 5, completed: 3, pending: 2, overdue: 1, comp: 78, delay: 1, actCls: 62, esc: 0 },
  'S. Kapoor': { clients: 1, planned: 6, completed: 4, pending: 3, overdue: 2, comp: 64, delay: 3, actCls: 48, esc: 1 },
  'A. Nair':   { clients: 1, planned: 8, completed: 7, pending: 1, overdue: 0, comp: 88, delay: 0, actCls: 74, esc: 0 },
  'P. Shah':   { clients: 1, planned: 4, completed: 2, pending: 2, overdue: 3, comp: 52, delay: 5, actCls: 40, esc: 2 },
};

const ALERTS = [
  { om: 'S. Kapoor', text: 'Nimbus Ltd — WRM overdue by 1 day.' },
  { om: 'S. Kapoor', text: 'Nimbus Ltd — action "Follow up: WRM" overdue. Owner: Megha M.' },
  { om: 'P. Shah',   text: 'Orbit Media — Cal Disc not scheduled this period.' },
  { om: 'P. Shah',   text: 'Orbit Media — 3 activities overdue, needs OM action.' },
];

const ACTIONS = [
  { om: 'S. Kapoor', client: 'Nimbus Ltd',    activity: 'WRM', action: 'Follow up: WRM',   owner: 'Megha M.', emp: 'EMP-170', target: '2026-07-17', actual: '—', status: 'Pending', clientDelay: 'Pending',  omDelay: 'Overdue' },
  { om: 'P. Shah',   client: 'Orbit Media',   activity: 'MMR', action: 'Schedule MMR',     owner: 'Rahul V.', emp: 'EMP-204', target: '2026-07-19', actual: '—', status: 'Pending', clientDelay: 'On-track', omDelay: 'Pending' },
  { om: 'R. Mehta',  client: 'Acme Corp',     activity: 'DRM', action: 'Sign-off DRM/KPI', owner: 'Priya S.', emp: 'EMP-088', target: '2026-07-22', actual: '—', status: 'Pending', clientDelay: 'On-track', omDelay: 'On-track' },
];

const OMS = ['R. Mehta', 'S. Kapoor', 'A. Nair', 'P. Shah'];
const sum = (rows, k) => rows.reduce((a, r) => a + r[k], 0);
const avg = (rows, k) => (rows.length ? Math.round(rows.reduce((a, r) => a + r[k], 0) / rows.length) : 0);

const OmSmopsView = () => {
  const [om, setOm] = useState('All OMs');
  const [period, setPeriod] = useState('Jul 2026');

  const isAll = om === 'All OMs';
  const scope = (rows) => (isAll ? rows : rows.filter((r) => r.om === om));

  const figures = useMemo(() => {
    if (!isAll) return FIGURES[om];
    const all = Object.values(FIGURES);
    return {
      clients: all.length,
      planned: sum(all, 'planned'), completed: sum(all, 'completed'),
      pending: sum(all, 'pending'), overdue: sum(all, 'overdue'),
      comp: avg(all, 'comp'), delay: avg(all, 'delay'), actCls: avg(all, 'actCls'), esc: sum(all, 'esc'),
    };
  }, [om, isAll]);

  const kpis = [
    { value: figures.clients,      label: isAll ? 'Total Clients' : 'My Clients', sub: 'Assigned',    tone: 'blue',   icon: Users },
    { value: figures.planned,      label: 'Planned',            sub: 'This period',     tone: 'yellow', icon: CalendarClock },
    { value: figures.completed,    label: 'Completed',          sub: 'Activities done', tone: 'green',  icon: CheckCircle2 },
    { value: figures.pending,      label: 'Pending',            sub: 'Upcoming',        tone: 'yellow', icon: Clock },
    { value: figures.overdue,      label: 'Overdue',            sub: 'Past deadline',   tone: 'red',    icon: AlertOctagon },
    { value: `${figures.comp}%`,   label: 'Completion',         sub: 'Done ÷ planned',  tone: 'green',  icon: Target },
    { value: figures.delay,        label: 'Avg Delay Days',     sub: 'On completed',    tone: 'yellow', icon: Timer },
    { value: `${figures.actCls}%`, label: 'Action Closure',     sub: 'vs 95% target',   tone: 'green',  icon: ClipboardCheck },
    { value: figures.esc,          label: 'Active Escalations', sub: 'Need action',     tone: 'red',    icon: AlertTriangle },
  ];

  return (
    <div className="space-y-5">
      <DashboardHero icon={Briefcase} title="OM Dashboard" highlight={om} subtitle="SMOps operational performance across clients">
        <HeaderSelect value={om} onChange={setOm} options={['All OMs', ...OMS]} />
        <HeaderSelect value={period} onChange={setPeriod} options={['Jul 2026', 'Jun 2026', 'Q2 2026']} />
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
      </DashboardHero>

      <OmDashboardBody kpis={kpis} matrix={scope(MATRIX)} alerts={scope(ALERTS)} actions={scope(ACTIONS)} />
    </div>
  );
};

export default OmSmopsView;
