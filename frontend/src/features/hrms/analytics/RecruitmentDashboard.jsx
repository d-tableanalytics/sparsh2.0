import React, { useCallback, useEffect, useState } from 'react';
import { BarChart3, Clock } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  getHrmsDashboard, getHrmsFunnel, getHrmsBreakdown,
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
];

const RecruitmentDashboard = () => {
  const { scope, companyId } = useHrms();

  const [range, setRange] = useState({ from: '', to: '' });
  const [data, setData] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [breakdowns, setBreakdowns] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    const params = {
      ...scope,
      date_from: range.from || undefined,
      date_to: range.to || undefined,
    };
    try {
      // One await for the two headline calls so the page paints complete rather than in
      // two visible steps.
      const [dash, fun] = await Promise.all([
        getHrmsDashboard(params),
        getHrmsFunnel(params),
      ]);
      setData(dash.data);
      setFunnel(fun.data);

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
  }, [companyId, range.from, range.to]);

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
