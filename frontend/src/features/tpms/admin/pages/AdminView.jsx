import React, { useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, LayoutDashboard, CalendarDays, Medal, Building2, CalendarClock, CalendarX,
  Users, ClipboardList, CheckCircle2, Target, Timer, ClipboardCheck, AlertTriangle,
  Star, Sparkles, FileCheck, Trophy, Activity, Clock,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, Th, Td, Trend, StatusBadge, Progress,
  KpiTile, HeaderSelect, TableShell,
} from '../../common/dashboardKit';
import { useAuth } from '../../../../context/AuthContext';
import { getAnalyticsDashboard, currentPeriod, periodLabel } from '../../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   Admin View — high-level operational dashboard (ERP-grade).
   Wired to GET /tpms/dashboards/analytics (getAnalyticsDashboard).
   Filters (period / OM / company) are applied server-side.
   ───────────────────────────────────────────────────────────── */

// Last 12 months as { value: 'YYYY-MM', label: 'Jul26' } — the canonical token the backend expects.
const monthOptions = () => {
  const out = [];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    out.push({ id: value, name: periodLabel(value) || value });
  }
  return out;
};

// Backend trend is 'Up' / 'Down' / 'Flat'; the Trend component expects lowercase.
const trendDir = (t) => String(t || '').toLowerCase();
const pctCell = (v) => (v === '' || v == null ? '—' : `${v}%`);

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const AdminView = () => {
  const { user } = useAuth();
  const months = useMemo(() => monthOptions(), []);

  const [tab, setTab] = useState('dashboard');
  const [period, setPeriod] = useState(currentPeriod());
  const [om, setOm] = useState('');
  const [client, setClient] = useState('');

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const res = await getAnalyticsDashboard({
          period: period || undefined,
          om_id: om || undefined,
          company_id: client || undefined,
        });
        if (alive) setData(res.data);
      } catch (e) {
        if (alive) { setData(null); setError(e.response?.data?.detail || 'Failed to load dashboard'); }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [period, om, client, refreshKey]);

  const reload = () => setRefreshKey((k) => k + 1);

  const cards = data?.cards || {};
  const clients = data?.clients || [];
  const oms = data?.oms || [];
  const topDelayed = data?.top_delayed || [];

  const omOpts = useMemo(
    () => [{ id: '', name: 'All OMs' }, ...(data?.filters?.oms || [])], [data]);
  const clientOpts = useMemo(
    () => [{ id: '', name: 'All Clients' }, ...(data?.filters?.companies || [])], [data]);

  const kpis = [
    { value: cards.total_clients ?? 0,      label: 'Total Clients',      sub: 'In scope',              tone: 'blue',   icon: Building2 },
    { value: cards.planned_clients ?? 0,    label: 'Planned Clients',    sub: 'Have activity',         tone: 'green',  icon: CalendarClock },
    { value: cards.unplanned_clients ?? 0,  label: 'Unplanned Clients',  sub: 'No activity scheduled', tone: 'plain',  icon: CalendarX },
    { value: cards.total_oms ?? 0,          label: 'Total OMs',          sub: 'Across teams',          tone: 'blue',   icon: Users },
    { value: cards.planned ?? 0,            label: 'Planned Activities', sub: 'This period',           tone: 'yellow', icon: ClipboardList },
    { value: cards.completed ?? 0,          label: 'Completed',          sub: 'Activities done',       tone: 'green',  icon: CheckCircle2 },
    { value: `${cards.completion ?? 0}%`,   label: 'Overall Completion', sub: 'Done ÷ planned',        tone: 'green',  icon: Target },
    { value: cards.avg_delay ?? 0,          label: 'Avg Delay Days',     sub: 'Days past deadline',    tone: 'yellow', icon: Timer },
    { value: `${cards.action_closure ?? 0}%`, label: 'Action Closure',   sub: 'Closed ÷ total',        tone: 'yellow', icon: ClipboardCheck },
    { value: cards.escalations ?? 0,        label: 'Active Escalations', sub: 'Need OM action',        tone: cards.escalations ? 'red' : 'plain', icon: AlertTriangle },
    { value: `${cards.oa_rating ?? 0}%`,    label: 'O&A Rating',         sub: 'HODs accountability',   tone: 'green',  icon: Star },
    { value: `${cards.culture_score ?? 0}%`, label: 'Culture Score',     sub: 'Overall score',         tone: 'green',  icon: Sparkles },
    { value: `${cards.drm_completion ?? 0}%`, label: 'DRM Completion',   sub: 'HODs signed-off',       tone: 'green',  icon: FileCheck },
    { value: `${cards.success_score ?? 0}%`, label: 'Success Score',     sub: 'Overall avg',           tone: 'green',  icon: Trophy },
  ];

  return (
    <div className="space-y-5">
      {/* Hero header */}
      <DashboardHero icon={LayoutDashboard} title="Admin Dashboard"
        subtitle={`Operational command centre${user?.full_name ? ` · ${user.full_name}` : ''}`}>
        <HeaderSelect value={period} onChange={setPeriod} options={months} />
        <HeaderSelect value={om} onChange={setOm} options={omOpts} />
        <HeaderSelect value={client} onChange={setClient} options={clientOpts} />
        <HeroButton icon={RefreshCw} onClick={reload}>Refresh</HeroButton>
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

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {tab === 'calendar' ? (
        <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--bg-card)] py-20 text-center">
          <CalendarDays size={28} className="mx-auto text-[var(--text-muted)]" />
          <p className="text-[13px] font-bold mt-3">Client-wise Calendar</p>
          <p className="text-[12px] text-[var(--text-muted)] mt-1">Calendar view coming next.</p>
        </div>
      ) : loading && !data ? (
        <div className="py-24 flex flex-col items-center justify-center text-[var(--text-muted)]">
          <RefreshCw size={26} className="animate-spin mb-3 opacity-60" />
          <p className="text-[13px] font-bold">Loading dashboard…</p>
        </div>
      ) : !data ? (
        <div className="py-24 flex flex-col items-center justify-center text-[var(--text-muted)] rounded-2xl border border-dashed border-[var(--border)]">
          <AlertTriangle size={30} className="mb-3 opacity-40" />
          <p className="text-[13px] font-bold">Could not load dashboard data.</p>
        </div>
      ) : (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
            {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
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
                {clients.length === 0 ? (
                  <tr><Td className="text-center text-[var(--text-muted)]" align="center"><span className="block py-8">No clients for this selection.</span></Td></tr>
                ) : clients.map((r) => (
                  <tr key={r.company_id || r.company} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.company}</Td>
                    <Td className="text-[var(--text-muted)]">{r.om || '—'}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-green)]">{r.done ?? 0}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-orange)]">{r.pending ?? 0}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.overdue ?? 0}</Td>
                    <Td align="center" className="font-extrabold">{r.completion ?? 0}%</Td>
                    <Td><Progress value={r.completion ?? 0} /></Td>
                    <Td align="center" className="font-bold">{pctCell(r.action_closure)}</Td>
                    <Td align="center" className="tabular-nums">{r.avg_delay ?? 0}</Td>
                    <Td align="center" className="tabular-nums">{r.escalations ?? 0}</Td>
                    <Td align="center"><Trend dir={trendDir(r.trend)} /></Td>
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
                {oms.length === 0 ? (
                  <tr><Td className="text-center text-[var(--text-muted)]" align="center"><span className="block py-8">No OM data for this selection.</span></Td></tr>
                ) : oms.map((r, i) => (
                  <tr key={r.om_id || r.om} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td align="center">
                      {i === 0
                        ? <Medal size={18} className="inline" style={{ color: '#f59e0b' }} />
                        : <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-[var(--input-bg)] text-[var(--text-muted)] font-bold text-[11px]">{i + 1}</span>}
                    </Td>
                    <Td className={`font-bold ${stickyCell}`}>{r.om || '—'}</Td>
                    <Td align="center" className="tabular-nums">{r.clients ?? 0}</Td>
                    <Td align="center" className="tabular-nums">{r.planned ?? 0}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-green)]">{r.done ?? 0}</Td>
                    <Td align="center" className="font-extrabold">{r.completion ?? 0}%</Td>
                    <Td><Progress value={r.completion ?? 0} /></Td>
                    <Td align="center" className="tabular-nums">{r.avg_delay ?? 0}d</Td>
                    <Td align="center" className="font-bold">{pctCell(r.action_closure)}</Td>
                    <Td align="center" className="tabular-nums">{r.escalations ?? 0}</Td>
                    <Td align="center"><Trend dir={trendDir(r.trend)} /></Td>
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
                {topDelayed.length === 0 ? (
                  <tr><Td className="text-center text-[var(--text-muted)]" align="center"><span className="block py-8">No delayed clients 🎉</span></Td></tr>
                ) : topDelayed.map((r) => (
                  <tr key={r.company_id || r.company} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.company}</Td>
                    <Td className="text-[var(--text-muted)]">{r.om || '—'}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.avg_delay ?? 0}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.overdue ?? 0}</Td>
                    <Td align="center" className="font-extrabold">{r.completion ?? 0}%</Td>
                    <Td align="center"><StatusBadge value={r.status} /></Td>
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
