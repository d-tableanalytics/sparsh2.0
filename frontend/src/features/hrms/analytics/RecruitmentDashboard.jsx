import React, { useCallback, useEffect, useState } from 'react';
import { BarChart3, Clock } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  getHrmsDashboard, getHrmsFunnel, getHrmsBreakdown, getHrmsPositions, getClients,
} from '../../../services/hrmsApi';
import { CARD, GRID_KPI, GRID_TWO, SECTION_TITLE, nf } from './analyticsKit';
import {
  BarList, FunnelChart, KpiCard, MiniStat, RangePicker, ScopeNotice,
} from './analyticsKit.jsx';

/**
 * HRMS ▸ recruitment dashboard.
 *
 * Every figure is computed and scoped server-side. This component fetches and lays out —
 * it never totals, filters or re-derives anything, so the screen and the API cannot
 * disagree. That is the specific failure this phase exists to fix (FRONTEND_ANALYSIS §6.1:
 * the source computed everything in the browser, per screen, inconsistently).
 */

const BREAKDOWNS = [
  { by: 'source', title: 'Where candidates come from' },
  { by: 'department', title: 'Requisitions by department' },
  { by: 'designation', title: 'Requisitions by role' },
  { by: 'platform', title: 'Job postings by platform' },
  // ── Phase 11-R, Item 4 ──
  { by: 'referral_source', title: 'Referral sources' },
  { by: 'client_status', title: 'Client verdicts' },
];

const RecruitmentDashboard = () => {
  const { scope, companyId } = useHrms();

  const [range, setRange] = useState({ from: '', to: '' });
  const [data, setData] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [breakdowns, setBreakdowns] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // ── Phase 11-R, Item 4 ── the client-wise dropdown. Empty means "all clients", which is
  // what surfaces the per-client comparison table instead of one client's figures.
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState('');
  const [positions, setPositions] = useState(null);

  useEffect(() => {
    if (!companyId) return;
    // Failing quietly is correct: a company that does not use the client master should get
    // the dashboard it has always had, not an error banner about a feature it ignores.
    getClients(scope)
      .then(({ data: d }) => setClients(d?.clients || []))
      .catch(() => setClients([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    const params = {
      ...scope,
      date_from: range.from || undefined,
      date_to: range.to || undefined,
      client_id: clientId || undefined,
    };
    try {
      // One await for the headline calls so the page paints complete rather than in
      // several visible steps.
      const [dash, fun, pos] = await Promise.all([
        getHrmsDashboard(params),
        getHrmsFunnel(params),
        // The matrix is supporting detail — a failure there must not blank the KPIs above
        // it, which are the reason the reader opened the page.
        getHrmsPositions(params).catch(() => ({ data: null })),
      ]);
      setData(dash.data);
      setFunnel(fun.data);
      setPositions(pos.data);

      const results = await Promise.all(
        BREAKDOWNS.map((b) => getHrmsBreakdown({ ...params, by: b.by })
          .then((r) => [b.by, r.data])
          // A failed breakdown must not blank the dashboard — the KPIs above it are the
          // reason the reader opened the page.
          .catch(() => [b.by, null])),
      );
      setBreakdowns(Object.fromEntries(results));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the dashboard.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, range.from, range.to, clientId]);

  useEffect(() => { load(); }, [load]);

  const tth = data?.time_to_hire;

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={BarChart3}
        title="Recruitment dashboard"
        subtitle={data?.range ? `${data.range.from} to ${data.range.to}` : 'Hiring at a glance'}
        actions={<RangePicker value={range} onChange={setRange} />}
      />
      <HrmsScopeBar />

      {/* ── Phase 11-R, Item 4 — the client-wise dropdown ──
          Rendered only when a client master exists, so a company that does not recruit for
          clients never sees a filter with one option in it. "All clients" is not a wider
          scope than the default — it IS the default, and it turns on the per-client
          comparison table below. */}
      {clients.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <label htmlFor="d-client" className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
            Client
          </label>
          <select
            id="d-client"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
          >
            <option value="">All clients</option>
            {clients.map((c) => (
              <option key={c.client_id} value={c.client_id}>{c.name}</option>
            ))}
          </select>
        </div>
      )}

      {data?.scoped_to_own_requisitions && <ScopeNotice />}

      {loading && <HrmsLoading label="Crunching the numbers…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {data && !loading && !error && (
        <>
          <div className={GRID_KPI}>
            {data.kpis.map((k) => <KpiCard key={k.key} kpi={k} />)}
          </div>

          <div className={GRID_TWO}>
            <section className={CARD}>
              <p className={`${SECTION_TITLE} mb-3`}>Hiring funnel</p>
              {funnel?.total ? (
                <>
                  <FunnelChart stages={funnel.stages} />
                  {funnel.unranked > 0 && (
                    <p className="mt-3 text-[11px] text-[var(--text-muted)]">
                      {nf(funnel.unranked)} candidate(s) have a stage this dashboard
                      cannot interpret and are excluded from the bars.
                    </p>
                  )}
                </>
              ) : (
                <p className="text-[12.5px] text-[var(--text-muted)]">
                  No applications in this period.
                </p>
              )}
            </section>

            <div className="space-y-4">
              <section className={CARD}>
                <p className={`${SECTION_TITLE} mb-3`}>Positions</p>
                <div className="grid grid-cols-3 gap-3">
                  <MiniStat label="Open" value={nf(data.positions.open)} />
                  <MiniStat label="Vacancies" value={nf(data.positions.vacancies)} />
                  <MiniStat label="Filled" value={nf(data.positions.filled)} tone="good" />
                  <MiniStat label="On hold" value={nf(data.positions.on_hold)} />
                  <MiniStat label="Cancelled" value={nf(data.positions.cancelled)} />
                </div>
              </section>

              <section className={CARD}>
                <p className={`${SECTION_TITLE} mb-3`}>Offer outcomes</p>
                <div className="grid grid-cols-3 gap-3">
                  <MiniStat label="Sent" value={nf(data.offer_outcomes.sent)} />
                  <MiniStat label="Accepted" value={nf(data.offer_outcomes.accepted)} tone="good" />
                  <MiniStat label="Declined" value={nf(data.offer_outcomes.declined)} tone="danger" />
                  <MiniStat label="Revoked" value={nf(data.offer_outcomes.revoked)} />
                  <MiniStat label="Acceptance" value={`${data.offer_outcomes.acceptance_rate}%`} />
                </div>
              </section>

              <section className={CARD}>
                <p className={`${SECTION_TITLE} mb-3 flex items-center gap-1.5`}>
                  <Clock size={12} /> Time to hire
                </p>
                {tth?.sample ? (
                  <div className="grid grid-cols-3 gap-3">
                    <MiniStat label="Median" value={`${tth.median_days} d`} />
                    <MiniStat label="Mean" value={`${tth.mean_days} d`} />
                    <MiniStat label="Hires measured" value={nf(tth.sample)} />
                  </div>
                ) : (
                  <p className="text-[12.5px] text-[var(--text-muted)]">
                    No offers were accepted in this period, so there is nothing to measure.
                  </p>
                )}
                <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                  Application to offer acceptance. Median and mean are both shown — one slow
                  senior hire skews a mean badly.
                </p>
              </section>
            </div>
          </div>

          {/* ── Phase 11-R, Item 4 — the per-client comparison ──
              Shown only in the "all clients" view: with one client selected the KPIs above
              already ARE that client's figures, and a one-row comparison is noise. */}
          {!clientId && data.client_comparison?.length > 0 && (
            <section className={CARD}>
              <p className={`${SECTION_TITLE} mb-3`}>Client comparison</p>
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px] min-w-[760px]">
                  <thead>
                    <tr className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)]">
                      <th className="text-left py-2 pr-3">Client</th>
                      <th className="text-right py-2 px-2">Reqs</th>
                      <th className="text-right py-2 px-2">CVs</th>
                      <th className="text-right py-2 px-2">Reviewed</th>
                      <th className="text-right py-2 px-2">Shared</th>
                      <th className="text-right py-2 px-2">Client OK</th>
                      <th className="text-right py-2 px-2">Client no</th>
                      <th className="text-right py-2 px-2">Selected</th>
                      <th className="text-right py-2 pl-2">Joined</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.client_comparison.map((row) => (
                      <tr key={row.client_id || 'none'} className="border-b border-[var(--border)] last:border-0">
                        <td className="py-2 pr-3 font-semibold text-[var(--text-main)]">
                          {row.client_name}
                        </td>
                        <td className="py-2 px-2 text-right">{nf(row.requisitions)}</td>
                        <td className="py-2 px-2 text-right">{nf(row.total)}</td>
                        <td className="py-2 px-2 text-right">{nf(row.reviewed)}</td>
                        <td className="py-2 px-2 text-right">{nf(row.shared_with_client)}</td>
                        <td className="py-2 px-2 text-right text-[var(--accent-green,var(--accent-indigo))]">
                          {nf(row.client_shortlisted)}
                        </td>
                        <td className="py-2 px-2 text-right text-[var(--accent-red)]">
                          {nf(row.client_rejected)}
                        </td>
                        <td className="py-2 px-2 text-right">{nf(row.selected)}</td>
                        <td className="py-2 pl-2 text-right font-bold text-[var(--text-main)]">
                          {nf(row.joinings)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* ── Phase 11-R, Item 4 — position-wise CV status matrix ──
              Horizontally scrolling with a sticky first column: there is one column per
              application status and that will always be wider than a screen. Only statuses
              with a non-zero count anywhere are shown, so the table stays readable rather
              than being mostly zeros. */}
          {positions?.rows?.length > 0 && (
            <section className={CARD}>
              <p className={`${SECTION_TITLE} mb-3`}>Position-wise CV status</p>
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px] border-collapse">
                  <thead>
                    <tr className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)]">
                      <th className="text-left py-2 pr-3 sticky left-0 bg-[var(--bg-card)] z-10 min-w-[190px]">
                        Position
                      </th>
                      <th className="text-right py-2 px-2">Vac</th>
                      <th className="text-right py-2 px-2">CVs</th>
                      {positions.statuses
                        .filter((s) => positions.rows.some((r) => r.counts[s] > 0))
                        .map((s) => (
                          <th key={s} className="text-right py-2 px-2 whitespace-nowrap">{s}</th>
                        ))}
                    </tr>
                  </thead>
                  <tbody>
                    {positions.rows.map((row) => (
                      <tr key={row.request_no} className="border-b border-[var(--border)] last:border-0">
                        <td className="py-2 pr-3 sticky left-0 bg-[var(--bg-card)] z-10">
                          <span className="font-semibold text-[var(--text-main)]">
                            {row.designation || row.request_no}
                          </span>
                          <span className="block text-[11px] text-[var(--text-muted)]">
                            {[row.request_no, row.department, row.client_name]
                              .filter(Boolean).join(' · ')}
                          </span>
                        </td>
                        <td className="py-2 px-2 text-right">{nf(row.vacancy)}</td>
                        <td className="py-2 px-2 text-right font-bold text-[var(--text-main)]">
                          {nf(row.totals.candidates)}
                        </td>
                        {positions.statuses
                          .filter((s) => positions.rows.some((r) => r.counts[s] > 0))
                          .map((s) => (
                            <td key={s} className="py-2 px-2 text-right">
                              {row.counts[s] ? nf(row.counts[s])
                                : <span className="text-[var(--text-muted)]">—</span>}
                            </td>
                          ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <div className={GRID_TWO}>
            {BREAKDOWNS.map(({ by, title }) => (
              <section key={by} className={CARD}>
                <p className={`${SECTION_TITLE} mb-3`}>{title}</p>
                <BarList rows={breakdowns[by]?.rows} />
                {breakdowns[by]?.truncated && (
                  <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                    Showing the top {breakdowns[by].rows.length} only.
                  </p>
                )}
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export default RecruitmentDashboard;
