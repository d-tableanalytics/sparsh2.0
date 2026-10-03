import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Users, ListChecks, MessagesSquare, BadgeCheck, Info, X, Filter } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { getSourceAnalytics } from '../../../services/hrmsApi';
import SourceCharts from './SourceCharts';
import { STAGES, platformColor } from './sourceStages';

/**
 * Source Analytics ▸ Hiring outcomes view (the page shell is SourceAnalytics.jsx).
 *
 * Job Portal -> Applied -> Shortlisted -> Connected -> Interviewed -> Selected -> Hired, per
 * platform. The platform is kept on the candidate from the day they apply, so every later
 * stage is attributed to it. Each stage is evidence-backed and implies the ones before it,
 * so a row only ever narrows (see source_analytics in hrms_analytics_service.py).
 */
const SELECT = 'h-9 w-full px-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[12.5px] text-[var(--text-main)]';
const LABEL = 'block text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1';
const pctOf = (n, d) => (d ? Math.round((100 * n) / d) : null);
const NO_FILTERS = { request_no: '', department: '', position: '', platform: '' };

const Leader = ({ icon, tone, title, lead, unit }) => (
  <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 flex gap-3 min-w-0">
    <span className={`h-10 w-10 shrink-0 grid place-items-center rounded-lg ${tone}`}>
      {React.createElement(icon, { size: 18 })}
    </span>
    <div className="min-w-0">
      <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{title}</p>
      {lead ? (
        <>
          <p className="mt-0.5 text-[16px] font-bold text-[var(--text-main)] truncate">{lead.source}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {lead.count} {unit}{lead.count === 1 ? '' : 's'}
            {unit !== 'candidate' && lead.applied ? ` · ${pctOf(lead.count, lead.applied)}% of its ${lead.applied}` : ''}
          </p>
        </>
      ) : <p className="mt-1 text-[12px] text-[var(--text-muted)]">No candidate with a named job portal yet.</p>}
    </div>
  </div>
);

const SourceOutcomes = ({ from, to }) => {
  const { scope, companyId } = useHrms();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState(NO_FILTERS);
  const [sort, setSort] = useState({ key: 'applied', dir: -1 });

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

  const rows = useMemo(() => {
    const list = [...(data?.sources || [])];
    list.sort((a, b) => (sort.key === 'source'
      ? a.source.localeCompare(b.source) * sort.dir
      : ((a[sort.key] ?? -1) - (b[sort.key] ?? -1)) * sort.dir));
    return list;
  }, [data, sort]);

  const t = data?.totals || {};
  const opts = data?.options || {};
  const L = data?.leaders || {};
  const active = Object.values(filters).some(Boolean);
  const setF = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }));
  const sortBy = (key) => setSort((s) => ({ key, dir: s.key === key ? -s.dir : (key === 'source' ? 1 : -1) }));
  const arrow = (key) => (sort.key === key ? (sort.dir < 0 ? ' ↓' : ' ↑') : '');

  return (
    <div className="space-y-4">
      {/* Filters: requisition, department, position, job portal (the date is above). */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] p-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
          <label className="min-w-0">
            <span className={LABEL}>Job / requisition</span>
            <select className={SELECT} value={filters.request_no} onChange={setF('request_no')}>
              <option value="">All requisitions</option>
              {(opts.requisitions || []).map((r) => (
                <option key={r.request_no} value={r.request_no}>{r.request_no}{r.label ? ` · ${r.label}` : ''}</option>
              ))}
            </select>
          </label>
          <label className="min-w-0">
            <span className={LABEL}>Department</span>
            <select className={SELECT} value={filters.department} onChange={setF('department')}>
              <option value="">All departments</option>
              {(opts.departments || []).map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label className="min-w-0">
            <span className={LABEL}>Position</span>
            <select className={SELECT} value={filters.position} onChange={setF('position')}>
              <option value="">All positions</option>
              {(opts.positions || []).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label className="min-w-0">
            <span className={LABEL}>Source / job portal</span>
            <select className={SELECT} value={filters.platform} onChange={setF('platform')}>
              <option value="">All sources</option>
              {(opts.platforms || []).map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
            </select>
          </label>
        </div>
        {(active || data?.scoped_to_own_requisitions) && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11.5px] text-[var(--text-muted)]">
            {active && (
              <>
                <Filter size={12} /> Filtered
                <button type="button" onClick={() => setFilters(NO_FILTERS)}
                  className="h-6 px-2 rounded-md border border-[var(--border)] bg-[var(--bg-card)] font-bold text-[var(--accent-indigo)] inline-flex items-center gap-1">
                  <X size={11} /> Clear filters
                </button>
              </>
            )}
            {data?.scoped_to_own_requisitions && <span>Showing candidates on your own requisitions.</span>}
          </div>
        )}
      </div>

      {loading && <HrmsLoading label="Loading candidate sources…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && data && (
        <>
          {/* The four questions HR asked, answered first. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
            <Leader icon={Users} tone="bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"
              title="Most candidates" lead={L.applied} unit="candidate" />
            <Leader icon={ListChecks} tone="bg-sky-500/10 text-sky-600"
              title="Most shortlisted" lead={L.shortlisted} unit="shortlist" />
            <Leader icon={MessagesSquare} tone="bg-amber-500/10 text-amber-600"
              title="Most interviews" lead={L.interviewed} unit="interview" />
            <Leader icon={BadgeCheck} tone="bg-emerald-500/10 text-emerald-600"
              title="Most hires" lead={L.hired} unit="hire" />
          </div>

          {/* The overall funnel: Job Portal -> Applied -> ... -> Hired. */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-3">
              All sources · {STAGES.map((s) => s.label).join(' → ')}
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {STAGES.map((s, i) => (
                <div key={s.key} title={s.hint} className="min-w-0">
                  <p className="text-[20px] font-bold text-[var(--text-main)] tabular-nums">{t[s.key] ?? 0}</p>
                  <p className="text-[11px] font-semibold text-[var(--text-muted)] truncate">
                    {s.label}{i > 0 && t.applied ? ` · ${pctOf(t[s.key] || 0, t.applied)}%` : ''}
                  </p>
                  <div className="mt-1 h-1.5 w-full rounded-full bg-[var(--input-bg)] overflow-hidden">
                    <div className="h-full rounded-full" style={{
                      background: s.color,
                      width: `${t.applied ? Math.max((t[s.key] || 0) ? 4 : 0, (100 * (t[s.key] || 0)) / t.applied) : 0}%`,
                    }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Source-wise table. */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-x-auto">
            <table className="w-full min-w-[860px] text-[12.5px]">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                  <th className="px-3 py-2.5 text-left text-[10.5px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                    <button type="button" onClick={() => sortBy('source')} className="hover:text-[var(--text-main)]">Source{arrow('source')}</button>
                  </th>
                  {STAGES.map((s) => (
                    <th key={s.key} title={s.hint} className="px-3 py-2.5 text-right text-[10.5px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                      <button type="button" onClick={() => sortBy(s.key)} className="hover:text-[var(--text-main)]">{s.label}{arrow(s.key)}</button>
                    </th>
                  ))}
                  <th className="px-3 py-2.5 text-right text-[10.5px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                    <button type="button" onClick={() => sortBy('hire_rate')} className="hover:text-[var(--text-main)]">Hire rate{arrow('hire_rate')}</button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {!rows.length && (
                  <tr><td colSpan={STAGES.length + 2} className="px-3 py-6 text-center text-[var(--text-muted)]">No candidates match these filters.</td></tr>
                )}
                {rows.map((r) => (
                  <tr key={r.platform} className="border-t border-[var(--border)] hover:bg-[var(--input-bg)]/50">
                    <td className="px-3 py-2.5">
                      <span className="inline-flex items-center gap-2 font-semibold">
                        <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: platformColor(r.platform) }} />
                        <span className={r.platform === 'unspecified' ? 'italic text-[var(--text-muted)]' : 'text-[var(--text-main)]'}>{r.source}</span>
                      </span>
                    </td>
                    {STAGES.map((s, i) => (
                      <td key={s.key} className="px-3 py-2.5 text-right tabular-nums">
                        <span className={i === 0 ? 'font-bold text-[var(--text-main)]' : 'text-[var(--text-main)]'}>{r[s.key]}</span>
                        {i > 0 && r.applied > 0 && (
                          <span className="block text-[10.5px] text-[var(--text-muted)]">{pctOf(r[s.key], r.applied)}%</span>
                        )}
                      </td>
                    ))}
                    <td className="px-3 py-2.5 text-right tabular-nums font-bold text-[var(--text-main)]">
                      {r.hire_rate == null ? '—' : `${r.hire_rate}%`}
                    </td>
                  </tr>
                ))}
                {rows.length > 1 && (
                  <tr className="border-t-2 border-[var(--border)] bg-[var(--input-bg)]">
                    <td className="px-3 py-2.5 font-bold text-[var(--text-main)]">Total</td>
                    {STAGES.map((s) => (
                      <td key={s.key} className="px-3 py-2.5 text-right tabular-nums font-bold text-[var(--text-main)]">{t[s.key] ?? 0}</td>
                    ))}
                    <td className="px-3 py-2.5 text-right tabular-nums font-bold text-[var(--text-main)]">
                      {t.applied ? `${pctOf(t.hired || 0, t.applied)}%` : '—'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <SourceCharts data={data} />

          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 text-[11.5px] text-[var(--text-muted)]">
            <p className="flex items-center gap-1.5 font-bold text-[var(--text-main)] mb-2"><Info size={13} /> How each column is counted</p>
            <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">
              {STAGES.map((s) => (
                <li key={s.key}><span className="font-semibold text-[var(--text-main)]">{s.label}</span> — {s.hint}.</li>
              ))}
              <li className="md:col-span-2 mt-1">
                A candidate counts at every stage they reached, so someone rejected after an interview still
                counts as interviewed. The source is taken from the tracked job link, the “which job portal” answer
                on the form, or HR’s pick when adding a CV — and stays with the candidate all the way to joining.
                {data.not_specified > 0 && ` ${data.not_specified} older candidate${data.not_specified === 1 ? '' : 's'} only said “job portal” without naming which, so they show as Not specified.`}
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
};

export default SourceOutcomes;
