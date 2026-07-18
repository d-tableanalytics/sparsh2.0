import React, { useMemo, useState } from 'react';
import { AlertTriangle, Grid3x3, ClipboardList, CheckCircle2 } from 'lucide-react';
import { Section, Th, Td, Fraction, KpiTile, FilterSelect, TableShell } from './dashboardKit';

/**
 * Shared body for the "OM Dashboard" (KPI tiles + activity-status matrix
 * + action-required list + open-action-items table). Used by both the Admin
 * panel's OM (SMOps) View and the SMOPS panel Dashboard — each supplies its own
 * gradient header and pre-scoped data.
 *
 * props: kpis, matrix, alerts, actions, activityOptions
 */
const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const OmDashboardBody = ({ kpis, matrix, alerts, actions, activityOptions = ['WRM', 'MMR', 'DRM'] }) => {
  const [fActivity, setFActivity] = useState('All Activities');
  const [fClient, setFClient] = useState('All Clients');
  const [fOwner, setFOwner] = useState('All Owners');

  const clientOpts = useMemo(() => ['All Clients', ...Array.from(new Set(actions.map((a) => a.client)))], [actions]);
  const ownerOpts = useMemo(() => ['All Owners', ...Array.from(new Set(actions.map((a) => a.owner)))], [actions]);

  const filteredActions = actions.filter((a) =>
    (fActivity === 'All Activities' || a.activity === fActivity) &&
    (fClient === 'All Clients' || a.client === fClient) &&
    (fOwner === 'All Owners' || a.owner === fOwner));

  const clearFilters = () => { setFActivity('All Activities'); setFClient('All Clients'); setFOwner('All Owners'); };

  return (
    <>
      {/* KPI tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Activity Status matrix */}
      <Section
        title="My Clients — Activity Status"
        subtitle="Cadence completion across every governance ritual"
        icon={Grid3x3}
        action={<span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{matrix.length} clients</span>}
      >
        <TableShell minWidth={960}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Client</Th>
              <Th align="center">Org Str</Th><Th align="center">DRM/KPI</Th><Th align="center">Cal Disc</Th>
              <Th align="center">WRM</Th><Th align="center">MMR</Th><Th align="center">1-Pager</Th>
              <Th align="center">Action Cls</Th><Th align="center">A&O Rtg</Th><Th align="center">Cult Rtg</Th><Th align="center">Done</Th>
            </tr>
          </thead>
          <tbody>
            {matrix.map((r) => (
              <tr key={r.client} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                <Td className={`font-bold ${stickyCell}`}>{r.client}</Td>
                <Td align="center"><Fraction v={r.org} /></Td>
                <Td align="center"><Fraction v={r.drm} /></Td>
                <Td align="center"><Fraction v={r.cal} /></Td>
                <Td align="center"><Fraction v={r.wrm} /></Td>
                <Td align="center"><Fraction v={r.mmr} /></Td>
                <Td align="center"><Fraction v={r.pager} /></Td>
                <Td align="center"><Fraction v={r.action} /></Td>
                <Td align="center"><Fraction v={r.aoRtg} /></Td>
                <Td align="center"><Fraction v={r.cultRtg} /></Td>
                <Td align="center" className="font-extrabold text-[var(--accent-green)]">{r.done}</Td>
              </tr>
            ))}
            {matrix.length === 0 && (
              <tr><td colSpan={11} className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No clients for this selection.</td></tr>
            )}
          </tbody>
        </TableShell>
      </Section>

      {/* Action Required From Me */}
      <Section
        title="Action Required From Me"
        subtitle={alerts.length ? `${alerts.length} item${alerts.length > 1 ? 's' : ''} need your attention` : 'Nothing overdue'}
        icon={AlertTriangle}
        tone="red"
      >
        {alerts.length === 0 ? (
          <div className="flex items-center gap-2.5 px-5 py-6">
            <span className="w-8 h-8 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] flex items-center justify-center"><CheckCircle2 size={16} /></span>
            <p className="text-[13px] font-bold text-[var(--accent-green)]">All clear — no actions overdue.</p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {alerts.map((a, i) => (
              <div key={i} className="flex items-start gap-3 px-5 py-3.5 hover:bg-[var(--table-hover)] transition-colors">
                <span className="w-6 h-6 rounded-lg bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center mt-0.5 shrink-0"><AlertTriangle size={13} /></span>
                <span className="text-[12.5px] font-medium leading-relaxed">{a.text}</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Open Action Items */}
      <Section
        title="Open Action Items — My Clients"
        subtitle="Track pending follow-ups and closures"
        icon={ClipboardList}
        action={
          <div className="hidden md:flex items-center gap-2">
            <FilterSelect value={fActivity} onChange={setFActivity} options={['All Activities', ...activityOptions]} />
            <FilterSelect value={fClient} onChange={setFClient} options={clientOpts} />
            <FilterSelect value={fOwner} onChange={setFOwner} options={ownerOpts} />
            <button onClick={clearFilters} className="px-3 py-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] text-[12.5px] font-bold hover:bg-[var(--input-bg)] transition-all">Clear</button>
          </div>
        }
      >
        {/* Mobile filter row */}
        <div className="md:hidden flex flex-wrap items-center gap-2 px-4 py-3 border-b border-[var(--border)]">
          <FilterSelect value={fActivity} onChange={setFActivity} options={['All Activities', ...activityOptions]} />
          <FilterSelect value={fClient} onChange={setFClient} options={clientOpts} />
          <FilterSelect value={fOwner} onChange={setFOwner} options={ownerOpts} />
          <button onClick={clearFilters} className="px-3 py-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] text-[12.5px] font-bold hover:bg-[var(--input-bg)] transition-all">Clear</button>
        </div>

        <TableShell minWidth={940}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Client</Th>
              <Th>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Emp ID</Th>
              <Th>Target Date</Th><Th>Actual Date</Th><Th align="center">Status</Th><Th>Client Delay</Th><Th>OM Delay</Th>
            </tr>
          </thead>
          <tbody>
            {filteredActions.map((r, i) => (
              <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                <Td className={`font-bold ${stickyCell}`}>{r.client}</Td>
                <Td className="text-[var(--text-muted)]">{r.activity}</Td>
                <Td>{r.action}</Td>
                <Td className="text-[var(--text-muted)]">{r.owner}</Td>
                <Td className="tabular-nums text-[var(--text-muted)]">{r.emp}</Td>
                <Td className="tabular-nums">{r.target}</Td>
                <Td className="text-[var(--text-muted)]">{r.actual}</Td>
                <Td align="center"><span className="text-[10.5px] font-bold px-2 py-1 rounded-full" style={{ color: 'var(--accent-orange)', background: 'var(--accent-orange-bg)' }}>{r.status}</span></Td>
                <Td className="font-bold" style={{ color: r.clientDelay === 'On-track' ? 'var(--accent-green)' : 'var(--accent-orange)' }}>{r.clientDelay}</Td>
                <Td className="font-bold" style={{ color: r.omDelay === 'Overdue' ? 'var(--accent-red)' : r.omDelay === 'On-track' ? 'var(--accent-green)' : 'var(--accent-orange)' }}>{r.omDelay}</Td>
              </tr>
            ))}
            {filteredActions.length === 0 && (
              <tr><td colSpan={10} className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No open action items.</td></tr>
            )}
          </tbody>
        </TableShell>
      </Section>
    </>
  );
};

export default OmDashboardBody;
