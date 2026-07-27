import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarRange, RefreshCw, Grid3x3, Building2, ListChecks, CheckCircle2,
  AlertTriangle, Inbox,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, Th, Td, TableShell, KpiTile,
} from '../../common/dashboardKit';
import { getSchedules, getActivities } from '../../../../services/tpmsApi';
import api from '../../../../services/api';
import { useAuth } from '../../../../context/AuthContext';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Client-wise Activity Calendar (H6).

   A client × activity monthly matrix: ROWS = client companies,
   COLUMNS = activities (short names). Each cell shows that client's
   scheduled occurrences for the activity in the chosen month, with a
   count and a colour-coded status indicator. Empty cell = nothing
   scheduled.

   The matrix is assembled client-side by grouping the month's schedule
   feed (getSchedules, all companies in scope) by (company_id, activity).
   ───────────────────────────────────────────────────────────── */

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

/* TPMS status → ERP accent tokens (no hex literals: dark mode comes free). */
const TONE = {
  Completed:   { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Scheduled:   { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  Rescheduled: { c: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)' },
  Lapsed:      { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  Cancelled:   { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)' },
};
/* Priority (worst → best) — decides the cell's dominant dot colour. */
const STATUS_ORDER = ['Lapsed', 'Cancelled', 'Rescheduled', 'Scheduled', 'Completed'];
const toneOf = (s) => TONE[s] || TONE.Scheduled;

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

/* One matrix cell: count + a dot per status present. Empty → faint dash. */
const Cell = ({ occ }) => {
  if (!occ || !occ.total) return <span className="text-[13px] text-[var(--text-muted)] opacity-40">·</span>;
  const present = STATUS_ORDER.filter((s) => occ.byStatus[s]);
  const title = present.map((s) => `${s}: ${occ.byStatus[s]}`).join(' · ');
  const dominant = toneOf(present[0]);
  return (
    <span
      title={title}
      className="inline-flex flex-col items-center gap-1 px-1.5 py-1 rounded-lg border"
      style={{ color: dominant.c, background: dominant.bg, borderColor: dominant.bd }}
    >
      <span className="text-[12.5px] font-extrabold tabular-nums leading-none">{occ.total}</span>
      <span className="flex items-center gap-[3px]">
        {present.map((s) => (
          <span key={s} className="w-1.5 h-1.5 rounded-full" style={{ background: toneOf(s).c }} />
        ))}
      </span>
    </span>
  );
};

const LegendDot = ({ status }) => (
  <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-[var(--text-muted)]">
    <span className="w-2 h-2 rounded-full" style={{ background: toneOf(status).c }} />{status}
  </span>
);

const ClientActivityCalendar = () => {
  // Admin scope: this screen is mounted under the admin panel; useAuth gives the
  // acting user so the feed is fetched with their (org-wide) visibility.
  const { user } = useAuth();

  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);   // 1-12
  const [events, setEvents] = useState([]);
  const [activities, setActivities] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [onlyActive, setOnlyActive] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Company roster + activity catalogue are static per session — load once.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [actRes, coRes] = await Promise.all([getActivities(), api.get('/companies')]);
        if (!alive) return;
        setActivities((actRes.data?.activities || []).map((a) => ({
          name: a.name || '',
          short: a.short || a.name || '',
        })).filter((a) => a.name));
        setCompanies((coRes.data || []).map((c) => ({
          id: String(c._id || c.id || ''),
          name: c.name || c._id || c.id || '',
        })).filter((c) => c.id));
      } catch {
        if (alive) setError('Failed to load activity catalogue or company list');
      }
    })();
    return () => { alive = false; };
  }, []);

  // Month feed — omit company_id to pull every client in scope.
  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await getSchedules({ year, month });
      setEvents(data?.events || []);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load the activity calendar');
    } finally {
      setLoading(false);
    }
  }, [year, month]);

  useEffect(() => { load(); }, [load]);

  const changeMonth = (delta) => {
    let m = month + delta;
    let y = year;
    if (m < 1) { m = 12; y -= 1; }
    if (m > 12) { m = 1; y += 1; }
    setMonth(m); setYear(y);
  };

  // (company_id, activity name) → { total, byStatus }.
  const matrix = useMemo(() => {
    const map = {};
    events.forEach((e) => {
      const cid = String(e.company_id || '');
      const act = e.activity || '';
      if (!cid || !act) return;
      const row = (map[cid] ||= {});
      const cell = (row[act] ||= { total: 0, byStatus: {} });
      cell.total += 1;
      const st = e.status || 'Scheduled';
      cell.byStatus[st] = (cell.byStatus[st] || 0) + 1;
    });
    return map;
  }, [events]);

  // Rows = the company roster, plus any company that appears in the feed but
  // is missing from /companies (defensive — never drop scheduled work).
  const rows = useMemo(() => {
    const byId = {};
    companies.forEach((c) => { byId[c.id] = c.name; });
    events.forEach((e) => {
      const cid = String(e.company_id || '');
      if (cid && !(cid in byId)) byId[cid] = e.company || cid;
    });
    let list = Object.entries(byId).map(([id, name]) => ({ id, name }));
    if (onlyActive) list = list.filter((c) => matrix[c.id]);
    return list.sort((a, b) => a.name.localeCompare(b.name));
  }, [companies, events, matrix, onlyActive]);

  const stats = useMemo(() => {
    const s = { total: events.length, Completed: 0, activeClients: Object.keys(matrix).length };
    events.forEach((e) => { if (e.status === 'Completed') s.Completed += 1; });
    return s;
  }, [events, matrix]);

  const kpis = [
    { value: stats.total,          label: 'Scheduled Occurrences', sub: `${MONTHS[month - 1]} ${year}`, tone: 'blue',  icon: ListChecks },
    { value: stats.activeClients,  label: 'Active Clients',        sub: 'With activity',                tone: 'blue',  icon: Building2 },
    { value: activities.length,    label: 'Activities Tracked',    sub: 'Catalogue columns',            tone: 'plain', icon: Grid3x3 },
    { value: stats.Completed,      label: 'Completed',             sub: 'Confirmed done',               tone: 'green', icon: CheckCircle2 },
  ];

  const matrixCols = activities.length + 1; // Client + activities

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={CalendarRange}
        title="Client-wise Activity Calendar"
        highlight={`${MONTHS[month - 1]} ${year}`}
        subtitle="Client × activity matrix of scheduled occurrences for the month"
      >
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 flex items-center gap-2.5 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /><span>{error}</span>
        </div>
      )}

      {/* KPI tiles */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Matrix */}
      <Section
        title="Client-wise Activity Matrix"
        subtitle="Each cell: occurrences this month, with a status dot per outcome"
        icon={Grid3x3}
        action={(
          <label className="hidden sm:inline-flex items-center gap-1.5 text-[11px] font-bold text-[var(--text-muted)] cursor-pointer select-none">
            <input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} className="accent-[var(--accent-indigo)]" />
            Only clients with activity
          </label>
        )}
      >
        {/* Month nav + legend */}
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <button
              onClick={() => changeMonth(-1)}
              className="px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-black text-[var(--text-muted)] hover:bg-[var(--table-hover)]"
              aria-label="Previous month"
            >‹</button>
            <span className="text-[14px] font-black text-[var(--text-main)] min-w-[150px] text-center">
              {MONTHS[month - 1]} {year}
            </span>
            <button
              onClick={() => changeMonth(1)}
              className="px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-black text-[var(--text-muted)] hover:bg-[var(--table-hover)]"
              aria-label="Next month"
            >›</button>
          </div>
          <div className="flex-1" />
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {STATUS_ORDER.map((s) => <LegendDot key={s} status={s} />)}
          </div>
        </div>

        {loading && events.length === 0 ? (
          <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading calendar…</div>
        ) : activities.length === 0 ? (
          <div className="flex items-center gap-2.5 px-5 py-10 justify-center">
            <span className="w-8 h-8 rounded-lg bg-[var(--input-bg)] text-[var(--text-muted)] flex items-center justify-center"><Inbox size={16} /></span>
            <p className="text-[13px] font-bold text-[var(--text-muted)]">No activities in the catalogue to build columns.</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex items-center gap-2.5 px-5 py-10 justify-center">
            <span className="w-8 h-8 rounded-lg bg-[var(--input-bg)] text-[var(--text-muted)] flex items-center justify-center"><Inbox size={16} /></span>
            <p className="text-[13px] font-bold text-[var(--text-muted)]">
              Nothing scheduled for {MONTHS[month - 1]} {year}.
            </p>
          </div>
        ) : (
          <TableShell minWidth={Math.max(720, 220 + activities.length * 88)}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Client</Th>
                {activities.map((a) => <Th key={a.name} align="center"><span title={a.name}>{a.short}</span></Th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const cells = matrix[r.id] || {};
                return (
                  <tr key={r.id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold whitespace-nowrap ${stickyCell}`}>{r.name}</Td>
                    {activities.map((a) => (
                      <Td key={a.name} align="center"><Cell occ={cells[a.name]} /></Td>
                    ))}
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr><td colSpan={matrixCols} className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No clients for this month.</td></tr>
              )}
            </tbody>
          </TableShell>
        )}
      </Section>

      <p className="text-[11px] text-[var(--text-muted)] font-medium px-1">
        Scope: {user?.name || user?.username || 'admin'} · Columns use activity short codes (hover for full name).
      </p>
    </div>
  );
};

export default ClientActivityCalendar;
