import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, Users, ListChecks, CheckCircle2, XCircle, Clock, Gauge, Eye,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile,
} from '../../common/dashboardKit';
import { getEmployeeActivityDashboard, currentPeriod, periodLabel } from '../../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   SMOPS ▸ Employee Task — per-employee task-activity summary for the
   SMOPS user's assigned companies. Scoping (which companies/employees
   the caller may see) is enforced server-side from the auth token;
   the selectors below apply the same filters the backend supports.
   ───────────────────────────────────────────────────────────── */

const scoreColor = (v) => (v >= 80 ? 'var(--accent-green)' : v >= 60 ? 'var(--accent-orange)' : v > 0 ? 'var(--accent-red)' : 'var(--text-muted)');
const ScoreBar = ({ v }) => (
  <div className="flex items-center gap-2 min-w-[130px]">
    <div className="h-2 flex-1 rounded-full bg-[var(--input-bg)] overflow-hidden">
      <div className="h-full rounded-full transition-all" style={{ width: `${v}%`, background: v ? scoreColor(v) : 'transparent' }} />
    </div>
    <span className="text-[11px] font-bold tabular-nums" style={{ color: scoreColor(v) }}>{v}%</span>
  </div>
);
const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const SmopsEmployeeTask = () => {
  // All filters are applied SERVER-side (like the Admin Escalations page), so the
  // KPI cards and rows always reflect the current selection.
  const [period, setPeriod] = useState(() => currentPeriod());
  const [companyId, setCompanyId] = useState('');
  const [member, setMember] = useState('');
  const [designation, setDesignation] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getEmployeeActivityDashboard({
        period: period || undefined,
        company_id: companyId || undefined,
        member_id: member || undefined,
        designation: designation || undefined,
      });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load employee activity');
    } finally {
      setLoading(false);
    }
  }, [period, companyId, member, designation]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.rows || [];
  const cards = data?.cards || {};
  const canPickCompany = data?.can_pick_company ?? true;

  const companyOpts = useMemo(
    () => [{ id: '', name: 'All Companies' }, ...(data?.company_options || [])], [data]);
  const memberOpts = useMemo(
    () => [{ id: '', name: 'All Employees' }, ...(data?.member_options || [])], [data]);
  const designationOpts = useMemo(
    () => [{ id: '', name: 'All Designations' }, ...(data?.designation_options || []).map((d) => ({ id: d, name: d }))], [data]);
  const periodOpts = useMemo(() => {
    const opts = data?.period_options || [];
    return opts.some((o) => String(o.id) === period)
      ? opts
      : [{ id: period, name: periodLabel(period) || period }, ...opts];
  }, [data, period]);

  const clearFilters = () => { setPeriod(currentPeriod()); setCompanyId(''); setMember(''); setDesignation(''); };

  const kpis = [
    { value: cards.total_employees ?? 0,  label: 'Employees',   sub: 'In scope',         tone: 'blue',   icon: Users },
    { value: cards.total_activities ?? 0, label: 'Total Tasks', sub: 'This period',      tone: 'yellow', icon: ListChecks },
    { value: cards.completed ?? 0,        label: 'Completed',   sub: 'Done',             tone: 'green',  icon: CheckCircle2 },
    { value: cards.missed ?? 0,           label: 'Missed',      sub: 'Overdue/not done', tone: cards.missed ? 'red' : 'plain', icon: XCircle },
    { value: cards.pending ?? 0,          label: 'Pending',     sub: 'Upcoming',         tone: 'yellow', icon: Clock },
    { value: `${cards.avg_score ?? 0}%`,  label: 'Avg Score',   sub: 'Across employees', tone: (cards.avg_score ?? 0) >= 60 ? 'green' : 'yellow', icon: Gauge },
  ];

  return (
    <div className="space-y-5">
      <DashboardHero icon={Users} title="Company Employees — Task Activity" highlight={data?.company || 'All Companies'} subtitle="Per-employee task completion & scoring">
        {canPickCompany && <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOpts} />}
        <HeaderSelect value={period} onChange={setPeriod} options={periodOpts} />
        <HeaderSelect value={member} onChange={setMember} options={memberOpts} />
        <HeaderSelect value={designation} onChange={setDesignation} options={designationOpts} />
        <button onClick={clearFilters} className="inline-flex items-center px-3.5 py-2 rounded-lg bg-white/15 text-white text-[12.5px] font-bold ring-1 ring-white/25 hover:bg-white/25 transition-all">Clear</button>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {kpis.map((t) => <KpiTile key={t.label} {...t} />)}
      </div>

      <Section title="Employee Activity Summary" subtitle={loading ? 'Loading…' : `${rows.length} employee${rows.length === 1 ? '' : 's'} in scope`} icon={ListChecks}>
        <TableShell minWidth={1040}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Employee</Th><Th>Designation</Th><Th>Department</Th>
              <Th align="center">Total</Th><Th align="center">Completed</Th><Th align="center">Missed</Th><Th align="center">Pending</Th>
              <Th align="center">Score</Th><Th>Progress</Th><Th align="right">Action</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => {
              const sc = e.score ?? 0;
              const name = e.name || '—';
              return (
                <tr key={e.id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>
                    <div className="flex items-center gap-2.5">
                      <span className="w-7 h-7 rounded-full text-white text-[9px] font-bold flex items-center justify-center shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                        {name.split(' ').map((x) => x[0]).join('').slice(0, 2)}
                      </span>
                      {name}
                    </div>
                  </Td>
                  <Td className="text-[var(--accent-indigo)] font-bold uppercase text-[11px] tracking-wide">{e.designation || '—'}</Td>
                  <Td className="text-[var(--text-muted)] uppercase text-[11px] tracking-wide">{e.department || '—'}</Td>
                  <Td align="center" className="tabular-nums font-bold">{e.total ?? 0}</Td>
                  <Td align="center" className="font-bold text-[var(--accent-green)]">{e.completed ?? 0}</Td>
                  <Td align="center" className="font-bold text-[var(--accent-red)]">{e.missed ?? 0}</Td>
                  <Td align="center" className="font-bold text-[var(--accent-orange)]">{e.pending ?? 0}</Td>
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
              <tr><td colSpan={10} className="px-5 py-12 text-center text-[13px] font-bold text-[var(--text-muted)]">{loading ? 'Loading employee activity…' : 'No employees match your filters.'}</td></tr>
            )}
          </tbody>
        </TableShell>
      </Section>
    </div>
  );
};

export default SmopsEmployeeTask;
