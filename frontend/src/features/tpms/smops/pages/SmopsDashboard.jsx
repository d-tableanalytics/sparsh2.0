import React, { useMemo, useState } from 'react';
import {
  RefreshCw, Briefcase, Users, CalendarClock, CheckCircle2, Clock,
  AlertOctagon, Target, Timer, ClipboardCheck, AlertTriangle,
} from 'lucide-react';
import { useCompany } from '../CompanyContext';
import { DashboardHero, HeaderSelect, HeroButton } from '../../common/dashboardKit';
import OmDashboardBody from '../../common/OmDashboardBody';

/* ─────────────────────────────────────────────────────────────
   SMOPS panel Dashboard — the OM Dashboard scoped to the SMOPS user's
   companies via the global company selector. Shares OmDashboardBody with
   the Admin panel's OM (SMOps) View. All data is placeholder mock.
   ───────────────────────────────────────────────────────────── */

const MATRIX = [
  { companyId: 'acme',   client: 'Acme Corp',     org: '1/1', drm: '1/1', cal: '1/1', wrm: '1/1', mmr: '1/1', pager: '1/1', action: '1/1', aoRtg: '1/1', cultRtg: '1/1', done: 14 },
  { companyId: 'nimbus', client: 'Nimbus Ltd',    org: '1/1', drm: '0/1', cal: '1/1', wrm: '0/1', mmr: '1/1', pager: '0/1', action: '0/1', aoRtg: '0/1', cultRtg: '1/1', done: 9  },
  { companyId: 'vertex', client: 'Vertex Health', org: '1/1', drm: '1/1', cal: '1/1', wrm: '1/1', mmr: '1/1', pager: '1/1', action: '1/1', aoRtg: '1/1', cultRtg: '1/1', done: 21 },
  { companyId: 'orbit',  client: 'Orbit Media',   org: '1/1', drm: '0/1', cal: '0/1', wrm: '0/1', mmr: '1/1', pager: '0/1', action: '0/1', aoRtg: '0/1', cultRtg: '0/1', done: 6  },
  { companyId: 'cobalt', client: 'Cobalt Bank',   org: '1/1', drm: '1/1', cal: '1/1', wrm: '1/1', mmr: '1/1', pager: '1/1', action: '1/1', aoRtg: '1/1', cultRtg: '1/1', done: 11 },
];

const FIGURES = {
  acme:   { clients: 1, planned: 5, completed: 3, pending: 2, overdue: 1, comp: 78, delay: 1, actCls: 62, esc: 0 },
  nimbus: { clients: 1, planned: 6, completed: 4, pending: 3, overdue: 2, comp: 64, delay: 3, actCls: 48, esc: 1 },
  vertex: { clients: 1, planned: 8, completed: 7, pending: 1, overdue: 0, comp: 88, delay: 0, actCls: 74, esc: 0 },
  orbit:  { clients: 1, planned: 4, completed: 2, pending: 2, overdue: 3, comp: 52, delay: 5, actCls: 40, esc: 2 },
  cobalt: { clients: 1, planned: 3, completed: 2, pending: 1, overdue: 0, comp: 67, delay: 0, actCls: 50, esc: 0 },
};

const ALERTS = [
  { companyId: 'nimbus', text: 'Nimbus Ltd — WRM overdue by 1 day.' },
  { companyId: 'nimbus', text: 'Nimbus Ltd — action "Follow up: WRM" overdue. Owner: Megha M.' },
  { companyId: 'orbit',  text: 'Orbit Media — Cal Disc not scheduled this period.' },
  { companyId: 'orbit',  text: 'Orbit Media — 3 activities overdue, needs OM action.' },
];

const ACTIONS = [
  { companyId: 'nimbus', client: 'Nimbus Ltd',  activity: 'WRM', action: 'Follow up: WRM',   owner: 'Megha M.', emp: 'EMP-170', target: '2026-07-17', actual: '—', status: 'Pending', clientDelay: 'Pending',  omDelay: 'Overdue' },
  { companyId: 'orbit',  client: 'Orbit Media', activity: 'MMR', action: 'Schedule MMR',     owner: 'Rahul V.', emp: 'EMP-204', target: '2026-07-19', actual: '—', status: 'Pending', clientDelay: 'On-track', omDelay: 'Pending' },
  { companyId: 'acme',   client: 'Acme Corp',   activity: 'DRM', action: 'Sign-off DRM/KPI', owner: 'Priya S.', emp: 'EMP-088', target: '2026-07-22', actual: '—', status: 'Pending', clientDelay: 'On-track', omDelay: 'On-track' },
];

const sum = (rows, k) => rows.reduce((a, r) => a + r[k], 0);
const avg = (rows, k) => (rows.length ? Math.round(rows.reduce((a, r) => a + r[k], 0) / rows.length) : 0);

const SmopsDashboard = () => {
  const { companies, companyId, setCompanyId, isAll, company } = useCompany();
  const [period, setPeriod] = useState('Jul 2026');
  const pickCompany = (name) => setCompanyId(companies.find((c) => c.name === name).id);

  const scope = (rows) => (isAll ? rows : rows.filter((r) => r.companyId === companyId));

  const figures = useMemo(() => {
    if (!isAll) return FIGURES[companyId];
    const all = Object.values(FIGURES);
    return {
      clients: all.length,
      planned: sum(all, 'planned'), completed: sum(all, 'completed'),
      pending: sum(all, 'pending'), overdue: sum(all, 'overdue'),
      comp: avg(all, 'comp'), delay: avg(all, 'delay'), actCls: avg(all, 'actCls'), esc: sum(all, 'esc'),
    };
  }, [companyId, isAll]);

  const kpis = [
    { value: figures.clients,      label: 'My Clients',         sub: 'Assigned',        tone: 'blue',   icon: Users },
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
      <DashboardHero icon={Briefcase} title="OM Dashboard" highlight={isAll ? 'All Companies' : company.name} subtitle="Your operational performance across assigned companies">
        <HeaderSelect value={company.name} onChange={pickCompany} options={companies.map((c) => c.name)} />
        <HeaderSelect value={period} onChange={setPeriod} options={['Jul 2026', 'Jun 2026', 'Q2 2026']} />
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
      </DashboardHero>

      <OmDashboardBody kpis={kpis} matrix={scope(MATRIX)} alerts={scope(ALERTS)} actions={scope(ACTIONS)} />
    </div>
  );
};

export default SmopsDashboard;
