import React, { useEffect, useMemo, useState } from 'react';
import {
  LayoutDashboard, RefreshCw, CheckCircle2, ClipboardList,
  Percent, Timer, AlertTriangle, Building2, Grid3x3, ListTodo,
} from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import { useNotification } from '../../../context/NotificationContext';
import { getClientDashboard } from '../../../services/tpmsFormsApi';
import { Section, Th, Td, TableShell, HeaderSelect } from '../common/dashboardKit';

/**
 * Client TPMS Dashboard — Success-Measure scorecard for the logged-in company,
 * filtered by month. All data is company-scoped server-side (a client can only ever
 * see their own company). Reuses the app theme via CSS variables.
 */

// Last 12 months as { value: 'YYYY-MM', label: 'Jul26' } — server maps to form period tokens.
const monthOptions = (now) => {
  const out = [];
  const base = now || new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    const label = `${d.toLocaleString('en-US', { month: 'short' })}${String(d.getFullYear()).slice(-2)}`;
    out.push({ value, label });
  }
  return out;
};

const pct = (v) => (v == null ? '—' : `${v}%`);

const STATUS_TONE = {
  'On Track': { text: 'var(--accent-green)', bg: 'var(--accent-green-bg)' },
  'At Risk':  { text: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)' },
  'Critical': { text: 'var(--accent-red)', bg: 'var(--accent-red-bg)' },
};
const ROW_STATUS_TONE = {
  Met:       { text: 'var(--accent-green)', bg: 'var(--accent-green-bg)' },
  Partial:   { text: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)' },
  'Not Met': { text: 'var(--accent-red)', bg: 'var(--accent-red-bg)' },
};

// Tracks the spec §7 achievement band (≥100 Met · 50–99 Partial · <50 Not Met) so the
// progress bar never reads amber next to a red "Not Met" pill.
const barColor = (p) => (p >= 100 ? 'var(--accent-green)' : p >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)');

// Colour vocabulary for the client × activity status grid. The backend cell.status
// is emitted in two spellings across sources — the TPMS status labels (Completed /
// Scheduled / Rescheduled / Lapsed / Cancelled) and the grid's lowercase tokens
// (done / pending / overdue / cancelled) — so both are aliased to the same tone.
const CELL_TONE = {
  Completed:   { label: 'Completed',   text: 'var(--accent-green)',  bg: 'var(--accent-green-bg)' },
  Scheduled:   { label: 'Scheduled',   text: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)' },
  Rescheduled: { label: 'Rescheduled', text: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)' },
  Lapsed:      { label: 'Lapsed',      text: 'var(--accent-red)',    bg: 'var(--accent-red-bg)' },
  Cancelled:   { label: 'Cancelled',   text: 'var(--text-muted)',    bg: 'var(--input-bg)' },
};
const CELL_ALIAS = {
  done: 'Completed', completed: 'Completed',
  pending: 'Scheduled', scheduled: 'Scheduled',
  reschedule: 'Rescheduled', rescheduled: 'Rescheduled',
  overdue: 'Lapsed', lapsed: 'Lapsed',
  cancelled: 'Cancelled', canceled: 'Cancelled',
};
// A fully-done cell always reads as Completed; otherwise map the status token.
const cellTone = (cell) => {
  if (cell && cell.total > 0 && cell.done >= cell.total) return CELL_TONE.Completed;
  const key = CELL_ALIAS[cell?.status] || cell?.status;
  return CELL_TONE[key] || CELL_TONE.Scheduled;
};
const CELL_LEGEND = ['Completed', 'Scheduled', 'Rescheduled', 'Lapsed'].map((k) => CELL_TONE[k]);

const StatCard = ({ icon: Icon, value, label, sub, tone = 'indigo' }) => {
  const tones = {
    indigo: 'var(--accent-indigo)', green: 'var(--accent-green)',
    orange: 'var(--accent-orange)', violet: '#8b5cf6', red: 'var(--accent-red)',
  };
  const c = tones[tone] || tones.indigo;
  return (
    <div className="flex-1 min-w-[160px] rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-[26px] font-black tracking-tight" style={{ color: c }}>{value}</span>
        <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: `${c}1a`, color: c }}>
          {Icon && <Icon size={18} />}
        </div>
      </div>
      <div className="mt-1 text-[12px] font-bold text-[var(--text-main)]">{label}</div>
      {sub && <div className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wide">{sub}</div>}
    </div>
  );
};

const Pill = ({ label, tone }) => (
  <span className="px-3 py-1 rounded-full text-[11px] font-black" style={{ color: tone.text, background: tone.bg }}>{label}</span>
);

/* ── Pending Actions ──────────────────────────────────────────
   Open follow-ups (tpms_action_items) raised when an activity runs
   overdue, closed only when internal staff confirm completion.

   While an item is open there is no numeric delay split yet — the
   server sends which side the clock is sitting on, so both delay
   columns carry the same label. Rather than print it twice at equal
   weight, the side actually being waited on is highlighted and the
   other is muted, so the hand-off is readable at a glance.
   ──────────────────────────────────────────────────────────── */
const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const DelayCell = ({ value, active }) => {
  if (!value || value === '—') return <span className="text-[var(--text-muted)] opacity-40">—</span>;
  const tone = active
    ? { color: 'var(--accent-orange)', background: 'var(--accent-orange-bg)' }
    : { color: 'var(--text-muted)', background: 'var(--input-bg)' };
  return (
    <span className="inline-flex items-center gap-1.5 text-[10.5px] font-black px-2.5 py-1 rounded-full whitespace-nowrap" style={tone}>
      {active && <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--accent-orange)' }} />}
      {value}
    </span>
  );
};

const ClientDashboard = () => {
  const { user } = useAuth();
  const { showError } = useNotification();

  const months = useMemo(() => monthOptions(), []);
  const [month, setMonth] = useState(months[0].value);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const res = await getClientDashboard(month);
        if (alive) setData(res.data);
      } catch (err) {
        if (alive) { setData(null); showError(err.response?.data?.detail || 'Failed to load dashboard'); }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [month, showError]);

  const co = data?.company;
  const cards = data?.cards;
  const scorecard = data?.scorecard || [];
  const statusTone = STATUS_TONE[co?.status] || STATUS_TONE['At Risk'];
  // Client dashboard is scoped to one company, so clients_grid holds a single row.
  const gridActivities = data?.activities ?? [];
  const gridCells = data?.clients_grid?.[0]?.cells ?? {};
  const pendingActions = data?.pending_actions ?? [];
  const today = todayIso();

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="rounded-[24px] overflow-hidden shadow-sm">
        <div className="px-6 py-5 flex items-center justify-between gap-4 flex-wrap bg-gradient-to-r from-indigo-600 to-violet-500 text-white">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-white/15 flex items-center justify-center shrink-0"><LayoutDashboard size={20} /></div>
            <div className="min-w-0">
              <h1 className="text-[16px] sm:text-[18px] font-black tracking-tight truncate">Client Dashboard</h1>
              <p className="text-[11px] font-semibold text-white/80 truncate">
                {co?.name || user?.company_name || 'Your Company'} · {user?.full_name || user?.email}
              </p>
            </div>
          </div>
          {/* Shared hero select — the rest of the TPMS headers use this; this page was the
              only one hand-rolling its own, which is how it drifted out of theme. */}
          <HeaderSelect value={month} onChange={setMonth} options={months} />
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="py-24 flex flex-col items-center justify-center text-[var(--text-muted)]">
          <RefreshCw size={26} className="animate-spin mb-3 opacity-60" />
          <p className="text-[13px] font-bold">Loading dashboard…</p>
        </div>
      )}

      {!loading && !data && (
        <div className="py-24 flex flex-col items-center justify-center text-[var(--text-muted)] rounded-2xl border border-dashed border-[var(--border)]">
          <AlertTriangle size={30} className="mb-3 opacity-40" />
          <p className="text-[13px] font-bold">Could not load dashboard data.</p>
        </div>
      )}

      {!loading && data && (
        <>
          {/* Company summary banner */}
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-5 py-3.5 flex items-center gap-2 flex-wrap text-[13px]">
            <Building2 size={15} className="text-[var(--accent-indigo)]" />
            <span className="font-black text-[var(--text-main)]">{co.name}</span>
            {co.om_name && <span className="text-[var(--text-muted)]">· OM: <b className="text-[var(--text-main)]">{co.om_name}</b></span>}
            <span className="text-[var(--text-muted)]">· Completion: <b style={{ color: 'var(--accent-indigo)' }}>{co.completion_pct}%</b></span>
            <span className="text-[var(--text-muted)]">· Status:</span>
            <Pill label={co.status?.toUpperCase()} tone={statusTone} />
          </div>

          {/* Summary cards — operational delivery for the selected month */}
          <div className="flex flex-wrap gap-4">
            <StatCard icon={ClipboardList} value={cards.planned} label="Planned" sub="This period" tone="orange" />
            <StatCard icon={CheckCircle2} value={cards.completed} label="Completed" sub="Activities done" tone="green" />
            <StatCard icon={Percent} value={`${cards.completion_pct}%`} label="Completion" sub="Done ÷ planned" tone="indigo" />
            <StatCard icon={Timer} value={cards.avg_delay_days} label="Avg Delay" sub="Days" tone="violet" />
          </div>

          {/* Activity scorecard */}
          <div className="rounded-[20px] border border-[var(--border)] overflow-hidden bg-[var(--bg-card)] shadow-sm">
            <div className="px-5 py-3.5 bg-[var(--table-header-bg,#1e293b)]" style={{ background: 'var(--sidebar-bg)' }}>
              <h2 className="text-[13px] font-black uppercase tracking-widest text-[var(--text-main)]">Activity Scorecard — Success Measures</h2>
            </div>

            {/* Table (scrolls horizontally on small screens) */}
            <div className="overflow-x-auto no-scrollbar">
              <table className="w-full min-w-[820px] text-[12px]">
                <thead>
                  <tr className="text-left text-[10px] font-black uppercase tracking-wider text-[var(--text-muted)] bg-[var(--input-bg)]">
                    <th className="px-4 py-2.5 w-8">#</th>
                    <th className="px-4 py-2.5">Activity Name</th>
                    <th className="px-3 py-2.5 text-center">Impl. Target %</th>
                    <th className="px-3 py-2.5 text-center">Actual Impl. %</th>
                    <th className="px-3 py-2.5 text-center">Score Target %</th>
                    <th className="px-3 py-2.5 text-center">Actual Score %</th>
                    <th className="px-3 py-2.5 text-center">Achievement %</th>
                    <th className="px-3 py-2.5 w-40">Progress</th>
                    <th className="px-3 py-2.5 text-right">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {scorecard.map((r, i) => {
                    const tone = ROW_STATUS_TONE[r.status] || ROW_STATUS_TONE['Not Met'];
                    return (
                      <tr key={r.activity} className="border-t border-[var(--border)] hover:bg-[var(--table-hover,rgba(0,0,0,0.02))]">
                        <td className="px-4 py-3 text-[var(--text-muted)] font-bold">{i + 1}</td>
                        <td className="px-4 py-3 font-black text-[var(--text-main)] whitespace-nowrap">{r.activity}</td>
                        <td className="px-3 py-3 text-center font-bold" style={{ color: 'var(--accent-indigo)' }}>{pct(r.impl_target_pct)}</td>
                        <td className="px-3 py-3 text-center">
                          {r.actual_impl_pct == null
                            ? <span className="text-[var(--text-muted)]">—</span>
                            : <span className="px-2 py-0.5 rounded-md font-black" style={{ color: barColor(r.actual_impl_pct), background: `${barColor(r.actual_impl_pct)}1a` }}>{r.actual_impl_pct}%</span>}
                        </td>
                        <td className="px-3 py-3 text-center font-bold" style={{ color: 'var(--accent-indigo)' }}>{pct(r.score_target_pct)}</td>
                        <td className="px-3 py-3 text-center font-bold text-[var(--text-main)]">{pct(r.actual_score_pct)}</td>
                        <td className="px-3 py-3 text-center font-black" style={{ color: barColor(r.achievement_pct) }}>{r.achievement_pct}%</td>
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-2">
                            <div className="flex-1 h-2 rounded-full bg-[var(--input-bg)] overflow-hidden">
                              <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, r.progress_pct)}%`, background: barColor(r.progress_pct) }} />
                            </div>
                            <span className="text-[10px] font-black text-[var(--text-muted)] w-8 text-right">{r.progress_pct}%</span>
                          </div>
                        </td>
                        <td className="px-3 py-3 text-right">
                          <span className="px-2.5 py-1 rounded-full text-[10px] font-black whitespace-nowrap" style={{ color: tone.text, background: tone.bg }}>{r.status}</span>
                        </td>
                      </tr>
                    );
                  })}
                  {scorecard.length === 0 && (
                    <tr><td colSpan={9} className="px-4 py-12 text-center text-[var(--text-muted)] text-[13px] font-bold">No activities for this month.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Activity Status grid — per-activity done/total with a status colour.
              Rows = the activity catalogue; each cell reflects this company's
              scheduled-vs-completed count and its lifecycle status. */}
          <Section
            title="Activity Status"
            subtitle="Scheduled vs. completed for each governance activity this month"
            icon={Grid3x3}
            action={<span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{gridActivities.length} activities</span>}
          >
            {/* Status legend */}
            <div className="px-5 py-3 flex flex-wrap gap-2 border-b border-[var(--border)]">
              {CELL_LEGEND.map((l) => (
                <span key={l.label} className="inline-flex items-center gap-1.5 text-[10.5px] font-bold px-2.5 py-1 rounded-full" style={{ color: l.text, background: l.bg }}>
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: l.text }} />{l.label}
                </span>
              ))}
            </div>

            {gridActivities.length === 0 ? (
              <div className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No activities to display for this month.</div>
            ) : (
              <TableShell minWidth={520}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <Th className="w-8">#</Th>
                    <Th>Activity</Th>
                    <Th align="center">Done / Total</Th>
                    <Th align="right">Status</Th>
                  </tr>
                </thead>
                <tbody>
                  {gridActivities.map((a, i) => {
                    const cell = gridCells[a.full];
                    const has = !!(cell && cell.total);
                    const tone = cellTone(cell);
                    return (
                      <tr key={a.full} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                        <Td className="text-[var(--text-muted)] font-bold">{i + 1}</Td>
                        <Td className="font-bold whitespace-nowrap">{a.full}</Td>
                        <Td align="center">
                          {has
                            ? <span className="inline-flex items-center justify-center min-w-[42px] text-[11px] font-black px-2 py-0.5 rounded-md tabular-nums" style={{ color: tone.text, background: tone.bg }}>{cell.done}/{cell.total}</span>
                            : <span className="text-[var(--text-muted)] opacity-40">—</span>}
                        </Td>
                        <Td align="right">
                          {has
                            ? (
                              <span className="inline-flex items-center gap-1.5 text-[10px] font-black px-2.5 py-1 rounded-full whitespace-nowrap" style={{ color: tone.text, background: tone.bg }}>
                                <span className="w-1.5 h-1.5 rounded-full" style={{ background: tone.text }} />{tone.label}
                              </span>
                            )
                            : <span className="text-[var(--text-muted)] opacity-40">—</span>}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>
            )}
          </Section>

          {/* Pending Actions — open follow-ups awaiting closure */}
          <Section
            title="Pending Actions"
            subtitle="Open follow-ups awaiting closure — shown across all periods, not just the selected month"
            icon={ListTodo}
            tone={pendingActions.length ? 'red' : 'green'}
            action={pendingActions.length > 0 && (
              <span className="text-[10.5px] font-black px-2.5 py-1 rounded-full whitespace-nowrap"
                style={{ color: 'var(--accent-red)', background: 'var(--accent-red-bg)' }}>
                {pendingActions.length} open
              </span>
            )}
          >
            {pendingActions.length === 0 ? (
              <div className="px-5 py-10 flex flex-col items-center gap-2 text-center">
                <CheckCircle2 size={24} className="text-[var(--accent-green)]" />
                <p className="text-[13px] font-bold">No pending actions.</p>
                <p className="text-[12px] text-[var(--text-muted)]">Follow-ups are raised automatically when an activity runs overdue.</p>
              </div>
            ) : (
              <TableShell minWidth={880}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <Th>Activity</Th>
                    <Th>Action</Th>
                    <Th>Owner</Th>
                    <Th align="center">Target Date</Th>
                    <Th align="center">Status</Th>
                    <Th align="center">Learner Delay</Th>
                    <Th align="center">Staff Delay</Th>
                  </tr>
                </thead>
                <tbody>
                  {pendingActions.map((a) => {
                    const target = String(a.target || '').slice(0, 10);
                    const overdue = target && target < today;
                    const waitingStaff = a.pending_side === 'staff';
                    return (
                      <tr key={a.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                        <Td className="font-black whitespace-nowrap">{a.activity || '—'}</Td>
                        <Td className="text-[var(--text-muted)]">{a.action || '—'}</Td>
                        <Td className="whitespace-nowrap">{a.owner || '—'}</Td>
                        <Td align="center" className="tabular-nums whitespace-nowrap">
                          <span className="font-bold" style={{ color: overdue ? 'var(--accent-red)' : 'var(--text-main)' }}>
                            {target || '—'}
                          </span>
                          {overdue && (
                            <span className="block text-[10px] font-black" style={{ color: 'var(--accent-red)' }}>
                              {a.follow_up || 'Overdue'}
                            </span>
                          )}
                        </Td>
                        <Td align="center">
                          <span className="px-2.5 py-1 rounded-full text-[10px] font-black whitespace-nowrap"
                            style={{ color: 'var(--accent-orange)', background: 'var(--accent-orange-bg)' }}>
                            {a.status || 'Pending'}
                          </span>
                        </Td>
                        <Td align="center"><DelayCell value={a.learner_delay} active={!waitingStaff} /></Td>
                        <Td align="center"><DelayCell value={a.staff_delay} active={waitingStaff} /></Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>
            )}
          </Section>

        </>
      )}
    </div>
  );
};

export default ClientDashboard;
