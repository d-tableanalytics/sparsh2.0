import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, GitBranch, CheckCircle2, CircleDashed, XCircle, Gauge, Target,
  Info, Grid3x3, MousePointerClick, AlertTriangle,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, Progress, TableShell, KpiTile,
} from '../../common/dashboardKit';
import { useAuth } from '../../../../context/AuthContext';
import { getImplementationTracker, currentPeriod } from '../../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Implementation Tracker — per-client Success-Measure
   scorecard + client × activity completion matrix.

   Wired to /tpms/dashboards/implementation (get_implementation_tracker).
   The scorecard is only returned when a single company is in scope, so it
   surfaces once a client is picked; "All Clients" shows the matrix only.

   Scoring model (server-supplied fields):
     • impl_target / impl_actual  — occurrence cadence expectation vs actual
     • score_target / score_actual — success-measure score vs target
     • achievement — Actual Score ÷ Score Target × 100
     • Status — Met ≥100% · Partial 1–99% · Not Met 0/none
   ───────────────────────────────────────────────────────────── */

const statusOf = (a) => (a >= 100 ? 'Met' : a > 0 ? 'Partial' : 'Not Met');
const STATUS = {
  'Met':     { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  'Partial': { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  'Not Met': { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
};
const Pill = ({ label }) => {
  const s = STATUS[label] || STATUS['Not Met'];
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{label}
    </span>
  );
};
const scoreColor = (v) => (v >= 80 ? 'var(--accent-green)' : v >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)');
const pctOrDash = (v) => (v == null ? '—' : `${v}%`);

// Last 12 months as { value: 'YYYY-MM', label: 'Jul26' }.
const monthOptions = () => {
  const out = [];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    const label = `${d.toLocaleString('en-US', { month: 'short' })}${String(d.getFullYear()).slice(-2)}`;
    out.push({ value, label });
  }
  return out;
};

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const ImplementationTracker = () => {
  const { user } = useAuth();
  // Client-role users are auto-scoped server-side; only admins/OMs pick a company.
  const canPickCompany = user?.role !== 'client';

  const periods = useMemo(() => monthOptions(), []);
  const [period, setPeriod] = useState(currentPeriod());
  const [company, setCompany] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getImplementationTracker({
        period: period || undefined,
        company_id: company || undefined,
      });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load implementation tracker');
    } finally {
      setLoading(false);
    }
  }, [period, company]);

  useEffect(() => { load(); }, [load]);

  const cards = data?.cards || {};
  const scorecard = useMemo(() => data?.scorecard || [], [data]);
  const matrixActivities = data?.matrix_activities || [];
  const clients = data?.clients || [];
  const filters = useMemo(() => data?.filters || {}, [data]);

  const companyOpts = useMemo(
    () => [{ id: '', name: 'All Clients' }, ...(filters.companies || [])], [filters]);
  const selectedName = useMemo(
    () => companyOpts.find((c) => String(c.id) === String(company))?.name || 'All Clients',
    [companyOpts, company]);

  const total = cards.total ?? scorecard.length;
  const avgScore = useMemo(() => {
    if (!scorecard.length) return 0;
    const sum = scorecard.reduce((a, r) => a + (r.score_actual || 0), 0);
    return Math.round(sum / scorecard.length);
  }, [scorecard]);

  const kpis = [
    { value: `${cards.met ?? 0}/${total}`,     label: 'Activity Done',  sub: 'Met ≥100%',        tone: 'green',  icon: CheckCircle2 },
    { value: `${cards.partial ?? 0}/${total}`, label: 'Partially Done', sub: 'Partial 1–99%',    tone: 'yellow', icon: CircleDashed },
    { value: `${cards.not_met ?? 0}/${total}`, label: 'Not Done',       sub: 'Not Met 0%',       tone: 'red',    icon: XCircle },
    { value: `${avgScore}%`,                   label: 'Avg Score',      sub: 'Across activities', tone: 'blue',  icon: Gauge },
    { value: '100%',                           label: 'Target',         sub: 'Default cadence',  tone: 'blue',   icon: Target },
  ];

  const hasScorecard = scorecard.length > 0;
  const matrixMinWidth = Math.max(720, 220 + matrixActivities.length * 64);

  if (loading && !data) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading implementation tracker…</div>;
  }

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={GitBranch} title="Implementation Tracker" highlight={selectedName} subtitle="Deployment scoring across success measures">
        <HeaderSelect value={period} onChange={setPeriod} options={periods} />
        {canPickCompany && <HeaderSelect value={company} onChange={setCompany} options={companyOpts} />}
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {/* Scoring legend */}
      <div className="rounded-2xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-4 py-3 flex items-start gap-2.5">
        <span className="w-7 h-7 rounded-lg bg-[var(--bg-card)] text-[var(--accent-orange)] flex items-center justify-center shrink-0 shadow-sm"><Info size={15} /></span>
        <p className="text-[12px] font-medium text-[var(--text-main)] leading-relaxed">
          <b>Impl. Target</b> = default cadence · <b>Actual Impl. %</b> = occurrence completion this period ·
          <b> Achievement %</b> = Actual Score ÷ Score Target × 100 —
          <span className="text-[var(--accent-green)] font-bold"> Met ≥100%</span> ·
          <span className="text-[var(--accent-orange)] font-bold"> Partial 1–99%</span> ·
          <span className="text-[var(--accent-red)] font-bold"> Not Met 0%</span>.
        </p>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Activity Scorecard */}
      <Section title="Activity Scorecard" subtitle={hasScorecard ? `Success measures for ${selectedName}` : 'Detailed success measures & uploads'} icon={Target}
        action={hasScorecard && <span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{scorecard.length} activities</span>}>
        {!hasScorecard ? (
          <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center"><MousePointerClick size={22} /></span>
            <p className="text-[13px] font-bold">Select a client to view its scorecard</p>
            <p className="text-[12px] text-[var(--text-muted)]">Pick a client from the header to see detailed success measures for {period}.</p>
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
              {scorecard.map((r, i) => {
                const achievement = r.achievement || 0;
                return (
                  <tr key={r.activity || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className="text-[var(--text-muted)] font-bold">{i + 1}</Td>
                    <Td className="font-bold">{r.activity || '—'}</Td>
                    <Td align="center" className="tabular-nums text-[var(--text-muted)]">{pctOrDash(r.impl_target)}</Td>
                    <Td align="center" className="tabular-nums font-bold" style={{ color: r.impl_actual ? 'var(--accent-green)' : 'var(--accent-red)' }}>{pctOrDash(r.impl_actual)}</Td>
                    <Td align="center" className="tabular-nums text-[var(--text-muted)]">{pctOrDash(r.score_target)}</Td>
                    <Td align="center" className="tabular-nums font-bold">{pctOrDash(r.score_actual)}</Td>
                    <Td align="center" className="font-extrabold">{achievement}%</Td>
                    <Td><Progress value={Math.min(achievement, 100)} /></Td>
                    <Td align="center"><Pill label={statusOf(achievement)} /></Td>
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
        )}
      </Section>

      {/* Client × Activity Completion Matrix */}
      <Section title="Client × Activity Completion Matrix" subtitle="Completion % per activity, all clients in scope" icon={Grid3x3}
        action={<span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{clients.length} clients</span>}>
        {clients.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
            <span className="w-10 h-10 rounded-2xl bg-[var(--input-bg)] text-[var(--text-muted)] flex items-center justify-center"><AlertTriangle size={20} /></span>
            <p className="text-[13px] font-bold">No activity for this period.</p>
          </div>
        ) : (
          <TableShell minWidth={matrixMinWidth}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Client</Th>
                {matrixActivities.map((a) => <Th key={a.full} align="center">{a.short}</Th>)}
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.company_id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>{c.company}</Td>
                  {matrixActivities.map((a) => {
                    const cell = c.cells?.[a.full];
                    const val = cell && cell.total ? Math.round((cell.done / cell.total) * 100) : null;
                    return (
                      <Td key={a.full} align="center" className="tabular-nums font-bold" style={{ color: val == null ? 'var(--text-muted)' : scoreColor(val) }}>
                        {val == null ? '—' : `${val}%`}
                      </Td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>
    </div>
  );
};

export default ImplementationTracker;
