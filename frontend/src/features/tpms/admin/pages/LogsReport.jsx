import React, { useMemo, useState } from 'react';
import {
  RefreshCw, Download, ScrollText, Search, CheckCircle2, XCircle, MinusCircle, Layers,
  MessageCircle, Mail,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, Th, Td, TableShell, KpiTile, FilterSelect,
} from '../../common/dashboardKit';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Logs Report — WhatsApp / Email notification delivery
   logs with status KPIs, date + status + side + quick filters and
   full-text search. All data is placeholder mock.
   ───────────────────────────────────────────────────────────── */

const NOW = new Date('2026-07-18T23:59:59');

const LOGS = [
  { ts: '2026-07-17 14:04:53', channel: 'whatsapp', action: 'Schedule', side: 'Company', recipient: 'Meera N.',   phone: '9196******82', status: 'Failed',  error: 'HTTP 400: {"error":{"message":"(#132…"}}', scheduleId: 'SCH-1784277…-1', activity: 'WRM' },
  { ts: '2026-07-17 12:06:17', channel: 'whatsapp', action: 'Schedule', side: 'Company', recipient: 'Bhavna R.',  phone: '—',            status: 'Skipped', error: 'No phone', scheduleId: 'SCH-1784270…-1', activity: 'Monthly Mgmt Review' },
  { ts: '2026-07-17 12:06:15', channel: 'whatsapp', action: 'Schedule', side: 'Company', recipient: 'Harshit T.', phone: '9191******90', status: 'Failed',  error: 'HTTP 400: {"error":{"message":"(#132…"}}', scheduleId: 'SCH-1784270…-1', activity: 'Monthly Mgmt Review' },
  { ts: '2026-07-16 10:51:36', channel: 'whatsapp', action: 'Schedule', side: 'Company', recipient: 'Aashi K.',   phone: '9174******68', status: 'Failed',  error: 'HTTP 400: {"error":{"message":"(#132…"}}', scheduleId: 'SCH-1784179…-1', activity: 'Org Structure Update' },
  { ts: '2026-07-16 09:20:02', channel: 'email',    action: 'Schedule', side: 'Client',  recipient: 'ops@vertex.io', phone: '—',        status: 'Sent',    error: '—', scheduleId: 'SCH-1784100…-2', activity: 'DRM / KPI Sign-off' },
  { ts: '2026-07-15 17:41:10', channel: 'email',    action: 'Reminder', side: 'Company', recipient: 'coord@acme.co', phone: '—',        status: 'Sent',    error: '—', scheduleId: 'SCH-1784044…-1', activity: 'Weekly Review Meeting' },
  { ts: '2026-07-15 08:12:44', channel: 'email',    action: 'Schedule', side: 'Client',  recipient: 'hr@nimbus.in',  phone: '—',        status: 'Skipped', error: 'No template', scheduleId: 'SCH-1783990…-3', activity: 'Culture Rating' },
  { ts: '2026-07-12 11:33:29', channel: 'whatsapp', action: 'Escalate', side: 'Company', recipient: 'Rohit S.',   phone: '9190******11', status: 'Sent',    error: '—', scheduleId: 'SCH-1783720…-1', activity: 'Cal Disc' },
];

const STATUS = {
  Sent:    { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Failed:  { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  Skipped: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
};
const StatusPill = ({ v }) => {
  const s = STATUS[v];
  return <span className="inline-flex items-center text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}>{v}</span>;
};
const Chip = ({ children }) => (
  <span className="inline-flex items-center text-[10.5px] font-bold px-2 py-1 rounded-md bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)]">{children}</span>
);

const daysBetween = (d) => Math.floor((NOW - new Date(d.replace(' ', 'T'))) / 86400000);
const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';
const QUICK = [{ k: 'today', label: 'Today' }, { k: '7d', label: '7d' }, { k: '30d', label: '30d' }, { k: 'all', label: 'All' }];

const LogsReport = () => {
  const [channel, setChannel] = useState('whatsapp');
  const [status, setStatus] = useState('All');
  const [side, setSide] = useState('All');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [quick, setQuick] = useState('all');
  const [q, setQ] = useState('');

  const rows = useMemo(() => LOGS.filter((r) => {
    if (r.channel !== channel) return false;
    if (status !== 'All' && r.status !== status) return false;
    if (side !== 'All' && r.side !== side) return false;
    const d = r.ts.slice(0, 10);
    if (from && d < from) return false;
    if (to && d > to) return false;
    if (quick !== 'all') {
      const age = daysBetween(r.ts);
      if (quick === 'today' && age > 0) return false;
      if (quick === '7d' && age > 7) return false;
      if (quick === '30d' && age > 30) return false;
    }
    if (q.trim()) {
      const hay = `${r.recipient} ${r.phone} ${r.activity} ${r.side} ${r.scheduleId} ${r.action}`.toLowerCase();
      if (!hay.includes(q.trim().toLowerCase())) return false;
    }
    return true;
  }), [channel, status, side, from, to, quick, q]);

  const totals = useMemo(() => {
    const t = rows.length;
    const sent = rows.filter((r) => r.status === 'Sent').length;
    const failed = rows.filter((r) => r.status === 'Failed').length;
    const skipped = rows.filter((r) => r.status === 'Skipped').length;
    return { t, sent, failed, skipped, pct: t ? Math.round((sent / t) * 100) : 0 };
  }, [rows]);

  const kpis = [
    { value: totals.t,       label: 'Total',   sub: channel === 'whatsapp' ? 'WhatsApp' : 'Email', tone: 'blue',  icon: Layers },
    { value: totals.sent,    label: 'Sent',    sub: `${totals.pct}% success`, tone: 'green', icon: CheckCircle2 },
    { value: totals.failed,  label: 'Failed',  sub: 'needs review',           tone: 'red',   icon: XCircle },
    { value: totals.skipped, label: 'Skipped', sub: 'no phone / no tpl',      tone: 'yellow',icon: MinusCircle },
  ];

  const labelCls = 'text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]';
  const inputCls = 'px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]';

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={ScrollText} title="Logs Report" subtitle="Notification delivery logs across channels">
        {/* channel toggle */}
        <div className="flex items-center gap-1 bg-white/20 p-1 rounded-lg">
          {[{ k: 'whatsapp', label: 'WhatsApp', icon: MessageCircle }, { k: 'email', label: 'Email', icon: Mail }].map((c) => (
            <button key={c.k} onClick={() => setChannel(c.k)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-bold transition-all ${channel === c.k ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-white/80 hover:text-white'}`}>
              <c.icon size={13} /> {c.label}
            </button>
          ))}
        </div>
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
        <HeroButton icon={Download}>CSV</HeroButton>
      </DashboardHero>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Filter bar */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4">
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 items-end">
          <label className="flex flex-col gap-1"><span className={labelCls}>From</span><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inputCls} /></label>
          <label className="flex flex-col gap-1"><span className={labelCls}>To</span><input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={inputCls} /></label>
          <label className="flex flex-col gap-1"><span className={labelCls}>Status</span><FilterSelect value={status} onChange={setStatus} options={['All', 'Sent', 'Failed', 'Skipped']} /></label>
          <label className="flex flex-col gap-1"><span className={labelCls}>Side</span><FilterSelect value={side} onChange={setSide} options={['All', 'Company', 'Client']} /></label>
          <div className="flex flex-col gap-1">
            <span className={labelCls}>Quick</span>
            <div className="flex items-center gap-1">
              {QUICK.map((qb) => (
                <button key={qb.k} onClick={() => setQuick(qb.k)}
                  className={`px-2.5 py-2 rounded-lg text-[12px] font-bold transition-all border ${quick === qb.k ? 'text-white border-transparent' : 'text-[var(--text-muted)] border-[var(--border)] hover:bg-[var(--input-bg)]'}`}
                  style={quick === qb.k ? { background: 'var(--btn-primary)' } : undefined}>{qb.label}</button>
              ))}
            </div>
          </div>
          <label className="flex flex-col gap-1 col-span-2 md:col-span-1 xl:col-span-1">
            <span className={labelCls}>Search</span>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="name, phone, activity…" className={`${inputCls} w-full pl-9`} />
            </div>
          </label>
        </div>
      </div>

      {/* Logs table */}
      <Section title={`${channel === 'whatsapp' ? 'WhatsApp' : 'Email'} Logs`} subtitle={`${rows.length} row${rows.length === 1 ? '' : 's'}`} icon={channel === 'whatsapp' ? MessageCircle : Mail}>
        <TableShell minWidth={1120}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Timestamp</Th><Th>Action</Th><Th>Side</Th><Th>Recipient</Th><Th>Phone</Th>
              <Th align="center">Log Status</Th><Th>Error</Th><Th>Schedule ID</Th><Th>Activity</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                <Td className={`tabular-nums font-bold whitespace-nowrap ${stickyCell}`}>{r.ts}</Td>
                <Td><Chip>{r.action}</Chip></Td>
                <Td><Chip>{r.side}</Chip></Td>
                <Td className="font-medium whitespace-nowrap">{r.recipient}</Td>
                <Td className="tabular-nums text-[var(--text-muted)]">{r.phone}</Td>
                <Td align="center"><StatusPill v={r.status} /></Td>
                <Td className="max-w-[240px] truncate" style={{ color: r.status === 'Failed' ? 'var(--accent-red)' : 'var(--text-muted)' }}>{r.error}</Td>
                <Td className="tabular-nums text-[var(--text-muted)] whitespace-nowrap">{r.scheduleId}</Td>
                <Td className="font-medium whitespace-nowrap">{r.activity}</Td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={9} className="px-5 py-12 text-center text-[13px] font-bold text-[var(--text-muted)]">No logs match your filters.</td></tr>
            )}
          </tbody>
        </TableShell>
      </Section>
    </div>
  );
};

export default LogsReport;
