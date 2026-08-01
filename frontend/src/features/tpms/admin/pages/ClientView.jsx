import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, Building2, Target, Gauge, CheckCircle2, ClipboardList, Star,
  ListChecks, AlertTriangle,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, Progress, TableShell, KpiTile,
  usePaged, Pager,
} from '../../common/dashboardKit';
import { getClientDashboard, currentPeriod, periodLabel } from '../../../../services/tpmsApi';
import api from '../../../../services/api';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Client View — the "Client Dashboard" for a single
   client: an activity scorecard (success measures) + pending actions.
   Staff/admin pick which client company to view; data is company-scoped
   server-side (getClientDashboard → tpms_dashboard_service.get_learner_dashboard).
   ───────────────────────────────────────────────────────────── */

/* Last 12 months as { value: 'YYYY-MM', label: 'Jul26' }. */
const monthOptions = () => {
  const out = [];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    out.push({ value, label: periodLabel(value) || value });
  }
  return out;
};

const pct = (v) => (v == null || v === '' ? '—' : `${v}%`);

/* Backend row status → pill styling (rows[].status = Met | Partial | Not Met). */
const STATUS_STYLE = {
  'Met':     { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  'Partial': { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  'Not Met': { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
};

const Pill = ({ label }) => {
  const s = STATUS_STYLE[label] || STATUS_STYLE.Partial;
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{label}
    </span>
  );
};

/* Delay labels come from _delay_label: "On time" | "—" | "<n>d" (overdue). */
const delayColor = (v) => {
  if (v === 'On time') return 'var(--accent-green)';
  if (!v || v === '—') return 'var(--text-muted)';
  if (/pending/i.test(v)) return 'var(--accent-orange)';
  return 'var(--accent-red)';
};

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const ClientView = () => {
  const months = useMemo(() => monthOptions(), []);
  const [companies, setCompanies] = useState([]);
  const [company, setCompany] = useState('');
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Company roster for the picker.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.get('/companies');
        if (!alive) return;
        const list = (res.data || []).map((c) => ({ id: String(c._id || c.id || ''), name: c.name || c._id || c.id }));
        setCompanies(list);
        if (list.length) setCompany((prev) => prev || list[0].id);
      } catch {
        if (alive) setError('Failed to load companies');
      }
    })();
    return () => { alive = false; };
  }, []);

  const load = useCallback(async () => {
    if (!company) { setData(null); setError('Select a client to view their dashboard.'); return; }
    setLoading(true);
    setError('');
    try {
      const res = await getClientDashboard({ period, company_id: company });
      if (res.data?.error) { setData(null); setError(res.data.error); }
      else setData(res.data);
    } catch (e) {
      setData(null);
      setError(e.response?.data?.detail || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, [company, period]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.rows || [];
  const pending = data?.pending_actions || [];
  const cards = data?.cards || {};
  const opCards = data?.op_cards || {};
  const clientName = data?.company || companies.find((c) => c.id === company)?.name || 'client';
  const pPending = usePaged(pending || [], 10);

  const kpis = [
    { value: cards.total ?? 0,              label: 'Activities',      sub: 'Tracked',          tone: 'blue',   icon: ListChecks },
    { value: `${cards.avg_score ?? 0}%`,    label: 'Avg Achievement', sub: 'Success measure',  tone: (cards.avg_score ?? 0) >= 80 ? 'green' : 'yellow', icon: Target },
    { value: cards.met ?? 0,               label: 'On Track',        sub: 'Met (≥ 100%)',     tone: 'green',  icon: CheckCircle2 },
    { value: `${opCards.completion ?? 0}%`, label: 'Completion',      sub: 'Done ÷ planned',   tone: 'green',  icon: Star },
    { value: pending.length,               label: 'Pending Actions', sub: 'Open items',       tone: pending.length ? 'red' : 'plain', icon: ClipboardList },
    { value: periodLabel(period) || period, label: 'Period',         sub: 'Reporting window', tone: 'plain',  icon: Gauge },
  ];

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={Building2} title="Client Dashboard" highlight={data?.company || undefined} subtitle="Activity scorecard & success measures for the selected client">
        <HeaderSelect value={company} onChange={setCompany} options={companies} />
        <HeaderSelect value={period} onChange={setPeriod} options={months} />
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {loading && !data && (
        <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading dashboard…</div>
      )}

      {!loading && error && (
        <div className="rounded-2xl border border-[var(--accent-orange-border)] bg-[var(--accent-orange-bg)] px-4 py-3 flex items-center gap-2.5 text-[12px] font-bold text-[var(--accent-orange)]">
          <AlertTriangle size={15} />
          <span>{error} {!company && 'Pick a client company above.'}</span>
        </div>
      )}

      {!loading && !error && data && (
        <>
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
                  const ach = r.achievement ?? 0;
                  return (
                    <tr key={`${r.activity}-${i}`} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <Td className="text-[var(--text-muted)] font-bold">{i + 1}</Td>
                      <Td className="font-bold">{r.activity}</Td>
                      <Td align="center" className="tabular-nums text-[var(--text-muted)]">{pct(r.impl_target)}</Td>
                      <Td align="center" className="tabular-nums font-bold">{pct(r.impl_actual)}</Td>
                      <Td align="center" className="tabular-nums text-[var(--text-muted)]">{pct(r.target)}</Td>
                      <Td align="center" className="tabular-nums font-bold">{pct(r.actual)}</Td>
                      <Td align="center" className="font-extrabold">{ach}%</Td>
                      <Td><Progress value={ach} /></Td>
                      <Td align="center"><Pill label={r.status} /></Td>
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
                <p className="text-[13px] font-bold text-[var(--accent-green)]">No pending actions for {clientName}.</p>
              </div>
            ) : (
              <>
              <TableShell minWidth={820}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <Th className={stickyHead}>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Target Date</Th>
                    <Th align="center">Status</Th><Th>Learner Delay</Th><Th>Staff Delay</Th>
                  </tr>
                </thead>
                <tbody>
                  {pPending.pageRows.map((r, i) => (
                    <tr key={r.id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <Td className={`font-bold ${stickyCell}`}>{r.activity}</Td>
                      <Td>{r.action}</Td>
                      <Td className="text-[var(--text-muted)]">{r.owner || '—'}</Td>
                      <Td className="tabular-nums">{r.target || '—'}</Td>
                      <Td align="center">
                        <span className="text-[10.5px] font-bold px-2 py-1 rounded-full" style={{
                          color: r.status === 'Overdue' ? 'var(--accent-red)' : 'var(--accent-orange)',
                          background: r.status === 'Overdue' ? 'var(--accent-red-bg)' : 'var(--accent-orange-bg)',
                        }}>{r.status}</span>
                      </Td>
                      <Td className="font-bold" style={{ color: delayColor(r.learner_delay) }}>{r.learner_delay || '—'}</Td>
                      <Td className="font-bold" style={{ color: delayColor(r.staff_delay) }}>{r.staff_delay || '—'}</Td>
                    </tr>
                  ))}
                </tbody>
              </TableShell>
              <Pager {...pPending} label="actions" />
              </>
            )}
          </Section>
        </>
      )}
    </div>
  );
};

export default ClientView;
