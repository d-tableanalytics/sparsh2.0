import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Radar, CalendarRange, Users, Layers, Trophy, AlertTriangle, X, Info, SlidersHorizontal,
} from 'lucide-react';
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip } from 'recharts';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { getSourceAnalytics } from '../../../services/hrmsApi';
import { platformColor } from './sourceStages';

/**
 * HRMS ▸ Source Analytics (its own sidebar entry).
 *
 * How many candidates applied from each platform -- Naukri, LinkedIn, Indeed, Apna, Company
 * Website, Referral... -- for Sparsh Magic's own hiring. Every platform in the catalogue is
 * listed, zeros included, so HR can compare them at a glance; "Not specified" appears only
 * when some candidates applied before the platform was asked.
 */
const iso = (d) => d.toISOString().slice(0, 10);
const daysAgo = (n) => iso(new Date(Date.now() - n * 86400000));
const PRESETS = [['30 days', 30], ['90 days', 90], ['6 months', 182], ['1 year', 365]];
const NO_FILTERS = { request_no: '', department: '', position: '', platform: '' };
const CONTROL = 'h-9 w-full px-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[12.5px] text-[var(--text-main)]';
const KICKER = 'text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]';
const pct = (n, d) => (d ? Math.round((100 * n) / d) : 0);

const Kpi = ({ icon, tone, label, value, hint }) => (
  <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-4 flex items-start gap-3 min-w-0">
    <span className={`h-10 w-10 shrink-0 grid place-items-center rounded-xl ${tone}`}>
      {React.createElement(icon, { size: 18 })}
    </span>
    <div className="min-w-0">
      <p className={KICKER}>{label}</p>
      <p className="mt-0.5 text-[22px] leading-tight font-bold text-[var(--text-main)] truncate">{value}</p>
      {hint && <p className="text-[11.5px] text-[var(--text-muted)] truncate">{hint}</p>}
    </div>
  </div>
);

const ShareTip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 shadow-lg text-[12px]">
      <p className="font-bold text-[var(--text-main)]">{p.name}</p>
      <p className="text-[var(--text-muted)]">{p.value} candidate{p.value === 1 ? '' : 's'}</p>
    </div>
  );
};

const SourceAnalytics = () => {
  const { scope, companyId } = useHrms();
  const [from, setFrom] = useState(daysAgo(90));
  const [to, setTo] = useState(iso(new Date()));
  const [filters, setFilters] = useState(NO_FILTERS);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const today = iso(new Date());
  const activePreset = to === today ? PRESETS.find(([, n]) => from === daysAgo(n))?.[1] : null;

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const params = { ...scope, date_from: from || undefined, date_to: to || undefined };
      Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
      const { data: d } = await getSourceAnalytics(params);
      setData(d);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the source analytics.');
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, from, to, filters]);
  useEffect(() => { load(); }, [load]);

  // Every platform, zeros included, most candidates first.
  const rows = useMemo(() => {
    const found = Object.fromEntries((data?.sources || []).map((r) => [r.platform, r]));
    return (data?.options?.platforms || [])
      .filter((pl) => !filters.platform || pl.key === filters.platform)
      .map((pl, i) => ({ key: pl.key, label: pl.label, applied: found[pl.key]?.applied || 0, order: i }))
      .filter((r) => r.key !== 'unspecified' || r.applied > 0)
      // "Not specified" is not a platform, so it always ranks last, whatever its count.
      .sort((a, b) => ((a.key === 'unspecified') - (b.key === 'unspecified'))
        || (b.applied - a.applied) || (a.order - b.order));
  }, [data, filters.platform]);

  const total = rows.reduce((n, r) => n + r.applied, 0);
  const withCandidates = rows.filter((r) => r.applied > 0);
  const named = withCandidates.filter((r) => r.key !== 'unspecified');
  const top = named[0];
  const unspecified = rows.find((r) => r.key === 'unspecified')?.applied || 0;
  const zeroRows = rows.filter((r) => r.applied === 0);
  const max = Math.max(1, ...withCandidates.map((r) => r.applied));
  const opts = data?.options || {};
  const active = Object.values(filters).some(Boolean);
  const setF = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Radar}
        title="Source Analytics"
        subtitle="How many candidates applied from each platform — Naukri, LinkedIn, Indeed, Apna, Company Website, Referral and more."
      />
      <HrmsScopeBar />

      {/* One toolbar: the period, then the four filters. */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-[var(--border)]">
          <span className={`inline-flex items-center gap-1.5 mr-1 ${KICKER}`}>
            <CalendarRange size={13} /> Applied
          </span>
          <div className="inline-flex p-0.5 rounded-lg bg-[var(--input-bg)]">
            {PRESETS.map(([label, n]) => (
              <button key={n} type="button" onClick={() => { setFrom(daysAgo(n)); setTo(today); }}
                className={`h-7 px-2.5 rounded-md text-[11.5px] font-bold ${activePreset === n
                  ? 'bg-[var(--bg-card)] text-[var(--accent-indigo)] shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                {label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1.5">
            <input type="date" aria-label="From" value={from} max={to} onChange={(e) => setFrom(e.target.value)}
              className="h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[12px] text-[var(--text-main)]" />
            <span className="text-[11px] text-[var(--text-muted)]">to</span>
            <input type="date" aria-label="To" value={to} min={from} max={today} onChange={(e) => setTo(e.target.value)}
              className="h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[12px] text-[var(--text-main)]" />
          </div>
        </div>
        <div className="px-4 py-3 bg-[var(--input-bg)]">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
            {[
              ['request_no', 'Job / requisition', 'All requisitions',
                (opts.requisitions || []).map((r) => [r.request_no, `${r.request_no}${r.label ? ` · ${r.label}` : ''}`])],
              ['department', 'Department', 'All departments', (opts.departments || []).map((d) => [d, d])],
              ['position', 'Position', 'All positions', (opts.positions || []).map((p) => [p, p])],
              ['platform', 'Platform', 'All platforms', (opts.platforms || []).map((p) => [p.key, p.label])],
            ].map(([key, label, all, choices]) => (
              <label key={key} className="min-w-0">
                <span className={`block mb-1 ${KICKER}`}>{label}</span>
                <select className={CONTROL} value={filters[key]} onChange={setF(key)}>
                  <option value="">{all}</option>
                  {choices.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
            ))}
          </div>
          {(active || data?.scoped_to_own_requisitions) && (
            <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11.5px] text-[var(--text-muted)]">
              {active && (
                <button type="button" onClick={() => setFilters(NO_FILTERS)}
                  className="h-6 px-2 rounded-md border border-[var(--border)] bg-[var(--bg-card)] font-bold text-[var(--accent-indigo)] inline-flex items-center gap-1">
                  <SlidersHorizontal size={11} /> Filters on · <X size={11} /> Clear
                </button>
              )}
              {data?.scoped_to_own_requisitions && <span>Showing candidates on your own requisitions.</span>}
            </div>
          )}
        </div>
      </div>

      {loading && <HrmsLoading label="Counting candidates by platform…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && data && (
        <>
          {/* Headline numbers. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
            <Kpi icon={Users} tone="bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"
              label="Candidates applied" value={total} hint="in the selected period" />
            <Kpi icon={Layers} tone="bg-sky-500/10 text-sky-600"
              label="Platforms in use" value={named.length}
              hint={`of ${rows.filter((r) => r.key !== 'unspecified').length} platforms`} />
            <Kpi icon={Trophy} tone="bg-emerald-500/10 text-emerald-600"
              label="Top platform" value={top ? top.label : '—'}
              hint={top ? `${top.applied} candidates · ${pct(top.applied, total)}% of all` : 'No named platform yet'} />
            <Kpi icon={AlertTriangle}
              tone={unspecified ? 'bg-amber-500/10 text-amber-600' : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}
              label="Platform not recorded" value={unspecified}
              hint={unspecified ? 'Set it on the candidate (Correct the source)' : 'Every candidate has a platform'} />
          </div>

          {total === 0 ? (
            <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--bg-card)] py-14 text-center">
              <Radar size={28} className="mx-auto text-[var(--text-muted)] opacity-50" />
              <p className="mt-3 text-[13.5px] font-bold text-[var(--text-main)]">No candidates in this period</p>
              <p className="text-[12px] text-[var(--text-muted)]">Widen the dates or clear the filters.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
              {/* Ranked list: every platform with candidates, longest bar first. */}
              <div className="xl:col-span-2 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 min-w-0">
                <div className="flex items-baseline justify-between gap-2 mb-4">
                  <p className="text-[14px] font-bold text-[var(--text-main)]">Applications by platform</p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">{total} total</p>
                </div>
                <ol className="space-y-3">
                  {withCandidates.map((r, i) => {
                    const muted = r.key === 'unspecified';
                    return (
                      <li key={r.key} className="grid grid-cols-[22px_minmax(0,140px)_1fr_auto] items-center gap-3">
                        <span className="text-[11px] font-bold text-[var(--text-muted)] tabular-nums text-right">{i + 1}</span>
                        <span className="inline-flex items-center gap-2 min-w-0">
                          <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: platformColor(r.key) }} />
                          <span className={`text-[12.5px] font-semibold truncate ${muted ? 'italic text-[var(--text-muted)]' : 'text-[var(--text-main)]'}`}>{r.label}</span>
                        </span>
                        <span className="h-2.5 rounded-full bg-[var(--input-bg)] overflow-hidden">
                          <span className="block h-full rounded-full transition-all"
                            style={{ width: `${(100 * r.applied) / max}%`, background: platformColor(r.key) }} />
                        </span>
                        <span className="text-right tabular-nums whitespace-nowrap">
                          <span className="text-[13px] font-bold text-[var(--text-main)]">{r.applied}</span>
                          <span className="ml-1.5 text-[11px] text-[var(--text-muted)]">{pct(r.applied, total)}%</span>
                        </span>
                      </li>
                    );
                  })}
                </ol>
                {zeroRows.length > 0 && (
                  <div className="mt-5 pt-4 border-t border-[var(--border)]">
                    <p className={`mb-2 ${KICKER}`}>No candidates yet</p>
                    <div className="flex flex-wrap gap-1.5">
                      {zeroRows.map((r) => (
                        <span key={r.key}
                          className="inline-flex items-center gap-1.5 h-6 px-2 rounded-md bg-[var(--input-bg)] text-[11px] font-semibold text-[var(--text-muted)]">
                          <span className="h-2 w-2 rounded-sm" style={{ background: platformColor(r.key), opacity: 0.5 }} />
                          {r.label}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Share of the total, as a donut. */}
              <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 min-w-0">
                <p className="text-[14px] font-bold text-[var(--text-main)]">Share of candidates</p>
                <p className="text-[11.5px] text-[var(--text-muted)] mb-2">Each platform's slice of everyone who applied.</p>
                <div className="relative h-[210px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={withCandidates} dataKey="applied" nameKey="label" innerRadius={64} outerRadius={94}
                        paddingAngle={withCandidates.length > 1 ? 2 : 0} stroke="none">
                        {withCandidates.map((r) => <Cell key={r.key} fill={platformColor(r.key)} />)}
                      </Pie>
                      <Tooltip content={<ShareTip />} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="absolute inset-0 grid place-items-center pointer-events-none text-center">
                    <div>
                      <p className="text-[26px] font-bold leading-none text-[var(--text-main)]">{total}</p>
                      <p className="text-[10.5px] font-semibold text-[var(--text-muted)]">candidates</p>
                    </div>
                  </div>
                </div>
                <ul className="mt-2 space-y-1.5">
                  {withCandidates.map((r) => (
                    <li key={r.key} className="flex items-center gap-2 text-[12px]">
                      <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: platformColor(r.key) }} />
                      <span className="truncate text-[var(--text-main)]">{r.label}</span>
                      <span className="ml-auto tabular-nums text-[var(--text-muted)]">{pct(r.applied, total)}%</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <p className="flex items-start gap-1.5 px-1 text-[11.5px] text-[var(--text-muted)]">
            <Info size={13} className="shrink-0 mt-0.5" />
            <span>
              Counted by the date the candidate applied. The platform comes from the tracked job link,
              the applicant&apos;s “Which job portal?” answer, or HR&apos;s pick when adding a CV.
            </span>
          </p>
        </>
      )}
    </div>
  );
};

export default SourceAnalytics;
