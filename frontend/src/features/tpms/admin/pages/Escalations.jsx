import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, Siren, Info, AlertTriangle, Flame, Timer, CheckCircle2, ListOrdered,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile,
} from '../../common/dashboardKit';
import { getEscalationDashboard } from '../../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Escalations — active escalations requiring OM action,
   the reminder-timeline system logic, and resolved escalations.

   Levels shown here come from the auto-feed sweep (HOD T+5 → HR T+7 → MD T+10).
   NOTE: the mails recipients actually receive run on a different, faster cadence
   (D+1 pending → D+2 critical → D+3 lapsed). Both engines are ported from the
   Apps Script, which runs both — see backend tpms_escalation_service.py.
   ───────────────────────────────────────────────────────────── */

const TIMELINE = [
  { stage: 'Pre-Reminder',  tone: 'green',  timing: 'T − 2 days',   trigger: 'Scheduler auto-fires',    action: 'Send advance notice',   recipient: 'Client Coord (HOD/HR)', subject: '[Reminder] {Activity} due in 2 days | {Client}' },
  { stage: 'Activity Due',  tone: 'green',  timing: 'T (Due Date)', trigger: 'Date reached',            action: 'Send primary alert',    recipient: 'Client Coord + MD',     subject: '[Action Required] {Activity} | {Client} | {Date}' },
  { stage: 'Reminder 1',    tone: 'orange', timing: 'T + 2 days',   trigger: 'No response detected',    action: 'Auto follow-up mail',   recipient: 'Client Coord',          subject: '[Follow Up] {Activity} | {Client} | Reminder 1' },
  { stage: 'Reminder 2',    tone: 'orange', timing: 'T + 4 days',   trigger: 'Still no response',       action: 'Auto follow-up URGENT', recipient: 'Client Coord',          subject: '[URGENT] {Activity} | {Client} | Reminder 2' },
  { stage: 'Escalation L1', tone: 'red',    timing: 'T + 5 days',   trigger: '3rd reminder unanswered', action: 'Escalate to HOD',       recipient: 'HOD + OM CC',           subject: '[ESCALATION] {Activity} Overdue | {Client}' },
  { stage: 'Escalation L2', tone: 'red',    timing: 'T + 7 days',   trigger: 'HOD unresponsive',        action: 'Escalate to HR',        recipient: 'HR + OM',               subject: '[ESCALATION L2] {Activity} | {Client} | HOD Unresponsive' },
  { stage: 'Escalation L3', tone: 'red',    timing: 'T + 10 days',  trigger: 'HR unresponsive',         action: 'Escalate to MD',        recipient: 'MD + OM',               subject: '[CRITICAL] {Activity} | {Client} | MD Attention Required' },
];

// level 1 → HOD, 2 → HR, 3 → MD (escLevel_ in the source)
const LEVEL_LABEL = { 1: 'Escalation L1', 2: 'Escalation L2', 3: 'Escalation L3' };
const levelTone = (lvl) => (Number(lvl) >= 2 ? 'red' : Number(lvl) === 1 ? 'orange' : 'green');
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
  // Filters are applied SERVER-side (the source passed {smopsId, companyId} to the
  // backend and reloaded), so the KPI cards always reflect the current selection.
  const [om, setOm] = useState('');
  const [client, setClient] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getEscalationDashboard({
        om_id: om || undefined,
        company_id: client || undefined,
      });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load escalations');
    } finally {
      setLoading(false);
    }
  }, [om, client]);

  useEffect(() => { load(); }, [load]);

  const active = data?.active || [];
  const resolved = data?.resolved || [];
  const cards = data?.cards || {};

  const kpis = [
    { value: cards.active_count ?? 0,   label: 'Active Escalations', sub: 'Need OM action',   tone: cards.active_count ? 'red' : 'plain', icon: AlertTriangle },
    { value: (cards.l2 ?? 0) + (cards.l3 ?? 0), label: 'Critical (L2+)', sub: 'HR / MD involved', tone: (cards.l2 || cards.l3) ? 'red' : 'plain', icon: Flame },
    { value: cards.avg_overdue ?? 0,    label: 'Avg Days Overdue',   sub: 'Across active',    tone: 'yellow',                             icon: Timer },
    { value: cards.resolved_month ?? 0, label: 'Resolved',           sub: 'This month',       tone: 'green',                              icon: CheckCircle2 },
  ];

  const omOpts = useMemo(
    () => [{ id: '', name: 'All OMs' }, ...(data?.filters?.oms || [])], [data]);
  const clientOpts = useMemo(
    () => [{ id: '', name: 'All Clients' }, ...(data?.filters?.companies || [])], [data]);

  if (loading && !data) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading escalations…</div>;
  }

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={Siren} title="Escalation Dashboard" subtitle="Active escalations, reminder logic & resolutions">
        <HeaderSelect value={om} onChange={setOm} options={omOpts} />
        <HeaderSelect value={client} onChange={setClient} options={clientOpts} />
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

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
                  <Td className="font-bold">{r.company}</Td>
                  <Td className="text-[var(--text-muted)]">{r.om || '—'}</Td>
                  <Td className="font-medium">{r.activity}</Td>
                  <Td align="center" className="font-extrabold text-[var(--accent-red)] tabular-nums">{r.days_overdue}</Td>
                  <Td align="center"><Pill label={LEVEL_LABEL[r.level] || '—'} tone={levelTone(r.level)} /></Td>
                  <Td className="font-medium">{r.escalated_to || '—'}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.esc_date || '—'}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.last_reminder || '—'}</Td>
                  <Td align="center"><Pill label="Active" tone={levelTone(r.level)} /></Td>
                  <Td className="text-[var(--text-muted)] max-w-[220px]">{r.recommended || '—'}</Td>
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
                  <Td className={`font-bold ${stickyCell}`}>{r.company}</Td>
                  <Td className="text-[var(--text-muted)]">{r.om || '—'}</Td>
                  <Td className="font-medium">{r.activity}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.esc_date || '—'}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.res_date || '—'}</Td>
                  <Td align="center" className="font-extrabold text-[var(--accent-green)] tabular-nums">{r.days_taken}</Td>
                  <Td className="font-medium">{r.method || '—'}</Td>
                  <Td className="text-[var(--text-muted)]">{r.resolved_by || '—'}</Td>
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
