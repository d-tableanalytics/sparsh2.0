import React, { useEffect, useMemo, useState } from 'react';
import {
  LayoutDashboard, RefreshCw, CalendarDays, CheckCircle2, ClipboardList,
  Percent, Timer, TrendingUp, AlertTriangle, ShieldCheck, Building2,
} from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import { useNotification } from '../../../context/NotificationContext';
import { getClientDashboard } from '../../../services/tpmsFormsApi';

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

const barColor = (p) => (p >= 100 ? 'var(--accent-green)' : p > 0 ? 'var(--accent-orange)' : 'var(--accent-red)');

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
          <Icon size={18} />
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
  const stats = data?.stats;
  const scorecard = data?.scorecard || [];
  const statusTone = STATUS_TONE[co?.status] || STATUS_TONE['At Risk'];

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
          <select value={month} onChange={(e) => setMonth(e.target.value)}
            className="h-9 px-3 rounded-lg bg-white text-[12px] font-black text-gray-800 outline-none shadow-sm cursor-pointer">
            {months.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
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

          {/* Summary cards */}
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

            {/* Stat badges */}
            <div className="px-5 py-3 flex flex-wrap gap-2 border-b border-[var(--border)]">
              <Pill label={`Met ${stats.met}/${stats.total_activities}`} tone={ROW_STATUS_TONE.Met} />
              <Pill label={`Partial ${stats.partial}/${stats.total_activities}`} tone={ROW_STATUS_TONE.Partial} />
              <Pill label={`Not Met ${stats.not_met}/${stats.total_activities}`} tone={ROW_STATUS_TONE['Not Met']} />
              <Pill label={`Avg Score ${stats.avg_score_pct}%`} tone={{ text: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)' }} />
              <Pill label={`Target ${stats.target_score_pct}%`} tone={{ text: '#8b5cf6', bg: 'rgba(139,92,246,0.12)' }} />
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

          {/* Statistics footer cards */}
          <div className="flex flex-wrap gap-4">
            <StatCard icon={ShieldCheck} value={stats.met} label="Met Activities" tone="green" />
            <StatCard icon={TrendingUp} value={stats.partial} label="Partial Activities" tone="orange" />
            <StatCard icon={AlertTriangle} value={stats.not_met} label="Not Met Activities" tone="red" />
            <StatCard icon={Percent} value={`${stats.avg_score_pct}%`} label="Average Score" tone="indigo" />
            <StatCard icon={CalendarDays} value={`${stats.target_score_pct}%`} label="Target Score" tone="violet" />
          </div>
        </>
      )}
    </div>
  );
};

export default ClientDashboard;
