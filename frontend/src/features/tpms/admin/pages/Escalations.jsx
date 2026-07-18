import React, { useMemo, useState } from 'react';
import {
  RefreshCw, Siren, Info, AlertTriangle, Flame, Timer, CheckCircle2, ListOrdered,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile,
} from '../../common/dashboardKit';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Escalations — active escalations requiring OM action,
   the reminder-timeline system logic, and resolved escalations.
   Escalation chain: HOD (T+5) → HR (T+7) → MD (T+10). All data mock.
   ───────────────────────────────────────────────────────────── */

const ACTIVE = [
  { client: 'Nimbus Ltd',  om: 'S. Kapoor', activity: 'WRM',      daysOverdue: 6, level: 'Escalation L1', escalatedTo: 'HOD + OM',     escDate: '2026-07-12', lastReminder: '2026-07-16', status: 'Awaiting HOD',   action: 'Call HOD, confirm WRM reschedule' },
  { client: 'Orbit Media', om: 'P. Shah',   activity: 'Cal Disc', daysOverdue: 9, level: 'Escalation L2', escalatedTo: 'HR + OM',      escDate: '2026-07-09', lastReminder: '2026-07-17', status: 'Escalated to HR', action: 'HR to intervene with client MD' },
  { client: 'Acme Corp',   om: 'R. Mehta',  activity: 'DRM',      daysOverdue: 3, level: 'Reminder 2',    escalatedTo: 'Client Coord', escDate: '2026-07-15', lastReminder: '2026-07-17', status: 'Follow-up sent', action: 'Send urgent follow-up mail' },
];

const TIMELINE = [
  { stage: 'Pre-Reminder',  tone: 'green',  timing: 'T − 2 days',   trigger: 'Scheduler auto-fires',    action: 'Send advance notice',   recipient: 'Client Coord (HOD/HR)', subject: '[Reminder] {Activity} due in 2 days | {Client}' },
  { stage: 'Activity Due',  tone: 'green',  timing: 'T (Due Date)', trigger: 'Date reached',            action: 'Send primary alert',    recipient: 'Client Coord + MD',     subject: '[Action Required] {Activity} | {Client} | {Date}' },
  { stage: 'Reminder 1',    tone: 'orange', timing: 'T + 2 days',   trigger: 'No response detected',    action: 'Auto follow-up mail',   recipient: 'Client Coord',          subject: '[Follow Up] {Activity} | {Client} | Reminder 1' },
  { stage: 'Reminder 2',    tone: 'orange', timing: 'T + 4 days',   trigger: 'Still no response',       action: 'Auto follow-up URGENT', recipient: 'Client Coord',          subject: '[URGENT] {Activity} | {Client} | Reminder 2' },
  { stage: 'Escalation L1', tone: 'red',    timing: 'T + 5 days',   trigger: '3rd reminder unanswered', action: 'Escalate to HOD',       recipient: 'HOD + OM CC',           subject: '[ESCALATION] {Activity} Overdue | {Client}' },
  { stage: 'Escalation L2', tone: 'red',    timing: 'T + 7 days',   trigger: 'HOD unresponsive',        action: 'Escalate to HR',        recipient: 'HR + OM',               subject: '[ESCALATION L2] {Activity} | {Client} | HOD Unresponsive' },
  { stage: 'Escalation L3', tone: 'red',    timing: 'T + 10 days',  trigger: 'HR unresponsive',         action: 'Escalate to MD',        recipient: 'MD + OM',               subject: '[CRITICAL] {Activity} | {Client} | MD Attention Required' },
];

const RESOLVED = [
  { client: 'Vertex Health', om: 'A. Nair',   activity: 'MMR', escDate: '2026-07-02', resDate: '2026-07-05', daysTaken: 3, method: 'Client Coord response', resolvedBy: 'A. Nair' },
  { client: 'Helix Pharma',  om: 'S. Kapoor', activity: 'DRM', escDate: '2026-06-28', resDate: '2026-07-04', daysTaken: 6, method: 'HOD intervention',     resolvedBy: 'HR' },
];

const levelTone = (lvl) => (lvl.includes('Escalation') ? 'red' : lvl.includes('Reminder') ? 'orange' : 'green');
const TONE = {
  green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  orange: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  red:    { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
};
const Pill = ({ label, tone }) => {
  const s = TONE[tone] || TONE.orange;
  return <span className="inline-flex items-center text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}>{label}</span>;
};

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const Escalations = () => {
  const [om, setOm] = useState('All OMs');
  const [client, setClient] = useState('All Clients');

  const active = useMemo(() => ACTIVE.filter((r) =>
    (om === 'All OMs' || r.om === om) && (client === 'All Clients' || r.client === client)), [om, client]);
  const resolved = useMemo(() => RESOLVED.filter((r) =>
    (om === 'All OMs' || r.om === om) && (client === 'All Clients' || r.client === client)), [om, client]);

  const critical = active.filter((r) => /L2|L3/.test(r.level)).length;
  const avgOverdue = active.length ? Math.round(active.reduce((a, r) => a + r.daysOverdue, 0) / active.length) : 0;

  const kpis = [
    { value: active.length, label: 'Active Escalations', sub: 'Need OM action',     tone: active.length ? 'red' : 'plain', icon: AlertTriangle },
    { value: critical,      label: 'Critical (L2+)',     sub: 'HR / MD involved',   tone: critical ? 'red' : 'plain',       icon: Flame },
    { value: avgOverdue,    label: 'Avg Days Overdue',   sub: 'Across active',      tone: 'yellow',                         icon: Timer },
    { value: resolved.length, label: 'Resolved',         sub: 'This month',         tone: 'green',                          icon: CheckCircle2 },
  ];

  const omOpts = ['All OMs', ...Array.from(new Set([...ACTIVE, ...RESOLVED].map((r) => r.om)))];
  const clientOpts = ['All Clients', ...Array.from(new Set([...ACTIVE, ...RESOLVED].map((r) => r.client)))];

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={Siren} title="Escalation Dashboard" subtitle="Active escalations, reminder logic & resolutions">
        <HeaderSelect value={om} onChange={setOm} options={omOpts} />
        <HeaderSelect value={client} onChange={setClient} options={clientOpts} />
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
      </DashboardHero>

      {/* Source / chain info */}
      <div className="rounded-2xl border border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] px-4 py-3 flex items-start gap-2.5">
        <span className="w-7 h-7 rounded-lg bg-[var(--bg-card)] text-[var(--accent-indigo)] flex items-center justify-center shrink-0 shadow-sm"><Info size={15} /></span>
        <p className="text-[12px] font-medium text-[var(--text-main)] leading-relaxed">
          Source: <b>Escalation Tracker + Action Tracker</b> · Escalation chain:
          <b className="text-[var(--accent-indigo)]"> HOD (T+5) → HR (T+7) → MD (T+10)</b> · “This month” = current calendar month.
        </p>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Active Escalations */}
      <Section title="Active Escalations — Requires Immediate OM Action" subtitle={active.length ? `${active.length} open` : 'Nothing pending'} icon={AlertTriangle} tone="red">
        {active.length === 0 ? (
          <div className="flex items-center gap-2.5 px-5 py-8 justify-center">
            <span className="w-8 h-8 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] flex items-center justify-center"><CheckCircle2 size={16} /></span>
            <p className="text-[13px] font-bold text-[var(--accent-green)]">No active escalations 🎉</p>
          </div>
        ) : (
          <TableShell minWidth={1120}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>#</Th><Th>Client</Th><Th>OM</Th><Th>Activity</Th>
                <Th align="center">Days Overdue</Th><Th align="center">Level</Th><Th>Escalated To</Th>
                <Th>Escalation Date</Th><Th>Last Reminder</Th><Th align="center">Status</Th><Th>Recommended Action</Th>
              </tr>
            </thead>
            <tbody>
              {active.map((r, i) => (
                <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className="text-[var(--text-muted)] font-bold">{i + 1}</Td>
                  <Td className="font-bold">{r.client}</Td>
                  <Td className="text-[var(--text-muted)]">{r.om}</Td>
                  <Td className="font-medium">{r.activity}</Td>
                  <Td align="center" className="font-extrabold text-[var(--accent-red)] tabular-nums">{r.daysOverdue}</Td>
                  <Td align="center"><Pill label={r.level} tone={levelTone(r.level)} /></Td>
                  <Td className="font-medium">{r.escalatedTo}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.escDate}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.lastReminder}</Td>
                  <Td align="center"><Pill label={r.status} tone={levelTone(r.level)} /></Td>
                  <Td className="text-[var(--text-muted)] max-w-[220px]">{r.action}</Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>

      {/* Reminder Timeline (system logic) */}
      <Section title="Escalation Reminder Timeline (System Logic)" subtitle="Automated cadence from pre-reminder to MD escalation" icon={ListOrdered}>
        <TableShell minWidth={1040}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Stage</Th><Th>Timing</Th><Th>Trigger</Th><Th>Action</Th><Th>Recipient</Th><Th>Subject Line Format</Th>
            </tr>
          </thead>
          <tbody>
            {TIMELINE.map((r) => (
              <tr key={r.stage} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                <Td className={stickyCell}><span className="font-extrabold" style={{ color: TONE[r.tone].c }}>{r.stage}</span></Td>
                <Td className="font-bold tabular-nums whitespace-nowrap">{r.timing}</Td>
                <Td className="text-[var(--text-muted)]">{r.trigger}</Td>
                <Td className="font-medium">{r.action}</Td>
                <Td className="font-medium">{r.recipient}</Td>
                <Td>
                  <code className="inline-block text-[11px] font-mono px-2 py-1 rounded-md bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] whitespace-nowrap">{r.subject}</code>
                </Td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      </Section>

      {/* Resolved Escalations */}
      <Section title="Resolved Escalations — This Month" subtitle={resolved.length ? `${resolved.length} resolved` : 'None yet'} icon={CheckCircle2} tone="green">
        {resolved.length === 0 ? (
          <div className="px-5 py-8 text-center text-[13px] font-bold text-[var(--text-muted)]">No escalations resolved this month.</div>
        ) : (
          <TableShell minWidth={880}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Client</Th><Th>OM</Th><Th>Activity</Th><Th>Escalation Date</Th>
                <Th>Resolution Date</Th><Th align="center">Days Taken</Th><Th>Resolution Method</Th><Th>Resolved By</Th>
              </tr>
            </thead>
            <tbody>
              {resolved.map((r, i) => (
                <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>{r.client}</Td>
                  <Td className="text-[var(--text-muted)]">{r.om}</Td>
                  <Td className="font-medium">{r.activity}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.escDate}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.resDate}</Td>
                  <Td align="center" className="font-extrabold text-[var(--accent-green)] tabular-nums">{r.daysTaken}</Td>
                  <Td className="font-medium">{r.method}</Td>
                  <Td className="text-[var(--text-muted)]">{r.resolvedBy}</Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>
    </div>
  );
};

export default Escalations;
