import React from 'react';
import {
  ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts';
import { STAGES, platformColor } from './sourceStages';

/**
 * Charts for Source Analytics (Hiring outcomes view). Each card says in one line what
 * question it answers, so the page reads without needing the table.
 */
const TICK = { fontSize: 11, fontWeight: 600, fill: 'var(--text-muted)' };

export const ChartCard = ({ title, hint, children, className = '' }) => (
  <div className={`rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 min-w-0 h-full ${className}`}>
    <p className="text-[13px] font-bold text-[var(--text-main)]">{title}</p>
    <p className="text-[11.5px] text-[var(--text-muted)] mb-3">{hint}</p>
    {children}
  </div>
);

export const ChartEmpty = ({ children }) => (
  <div className="h-[220px] grid place-items-center text-[12px] text-[var(--text-muted)]">{children}</div>
);

export const ChartTip = ({ active, payload, label, unit = '' }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 shadow-lg text-[12px]">
      {label != null && <p className="font-bold text-[var(--text-main)] mb-1">{label}</p>}
      {payload.map((p) => (
        <p key={p.dataKey || p.name} className="flex items-center gap-2 text-[var(--text-main)]">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color || p.payload?.fill }} />
          <span className="text-[var(--text-muted)]">{p.name}</span>
          <span className="ml-auto pl-3 font-semibold tabular-nums">{p.value == null ? '—' : `${p.value}${unit}`}</span>
        </p>
      ))}
    </div>
  );
};

const legendText = (v) => <span className="text-[11.5px] text-[var(--text-muted)]">{v}</span>;
const LEGEND = { formatter: legendText, iconType: 'circle', iconSize: 8, itemSorter: null };

/** Grouped bars: every stage, side by side, per job portal. */
const FunnelByPortal = ({ sources }) => (
  <ChartCard title="Hiring funnel by job portal"
    hint="For each portal: how many applied, and how many of them were shortlisted, connected, interviewed, selected and hired.">
    {!sources.length ? <ChartEmpty>No candidates in this period.</ChartEmpty> : (
      <div className="h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={sources} margin={{ top: 4, right: 8, left: -18, bottom: 0 }} barGap={1} barCategoryGap="18%">
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="source" tick={TICK} axisLine={false} tickLine={false} interval={0} />
            <YAxis tick={TICK} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip content={<ChartTip />} cursor={{ fill: 'var(--input-bg)' }} />
            <Legend {...LEGEND} />
            {STAGES.map((s) => (
              <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[3, 3, 0, 0]} maxBarSize={18} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    )}
  </ChartCard>
);

/** Donut: each portal's share of all candidates. */
const ShareOfCandidates = ({ sources, total }) => (
  <ChartCard title="Share of candidates" hint="Which platform brings the most candidates.">
    {!total ? <ChartEmpty>No candidates in this period.</ChartEmpty> : (
      <div className="flex flex-col sm:flex-row xl:flex-col 2xl:flex-row items-center gap-4">
        <div className="relative h-[190px] w-[190px] shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={sources} dataKey="applied" nameKey="source" innerRadius={60} outerRadius={88}
                paddingAngle={sources.length > 1 ? 2 : 0} stroke="none">
                {sources.map((s) => <Cell key={s.platform} fill={platformColor(s.platform)} />)}
              </Pie>
              <Tooltip content={<ChartTip />} />
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 grid place-items-center pointer-events-none text-center">
            <div>
              <p className="text-[22px] font-bold text-[var(--text-main)] leading-none">{total}</p>
              <p className="text-[10.5px] font-semibold text-[var(--text-muted)]">candidates</p>
            </div>
          </div>
        </div>
        <ul className="w-full space-y-1.5">
          {sources.map((s) => (
            <li key={s.platform} className="flex items-center gap-2 text-[12px]">
              <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: platformColor(s.platform) }} />
              <span className="truncate text-[var(--text-main)]">{s.source}</span>
              <span className="ml-auto tabular-nums font-semibold text-[var(--text-main)]">{s.applied}</span>
              <span className="w-11 text-right tabular-nums text-[var(--text-muted)]">{Math.round((100 * s.applied) / total)}%</span>
            </li>
          ))}
        </ul>
      </div>
    )}
  </ChartCard>
);

/** Horizontal bars: of what each portal brought, the % that got to each stage. */
const ConversionByPortal = ({ sources }) => {
  const h = Math.max(200, sources.length * 60 + 50);
  return (
    <ChartCard title="Conversion by job portal"
      hint="Of the candidates each portal brought, the % shortlisted, interviewed and hired — quality, not volume.">
      {!sources.length ? <ChartEmpty>No candidates in this period.</ChartEmpty> : (
        <div style={{ height: h }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={sources} layout="vertical" margin={{ top: 0, right: 16, left: 4, bottom: 0 }} barGap={2}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
              <XAxis type="number" domain={[0, 100]} tick={TICK} axisLine={false} tickLine={false} unit="%" />
              <YAxis type="category" dataKey="source" tick={TICK} axisLine={false} tickLine={false} width={104} />
              <Tooltip content={<ChartTip unit="%" />} cursor={{ fill: 'var(--input-bg)' }} />
              <Legend {...LEGEND} />
              <Bar dataKey="shortlist_rate" name="Shortlisted" fill={STAGES[1].color} radius={[0, 4, 4, 0]} maxBarSize={11} />
              <Bar dataKey="interview_rate" name="Interviewed" fill={STAGES[3].color} radius={[0, 4, 4, 0]} maxBarSize={11} />
              <Bar dataKey="hire_rate" name="Hired" fill={STAGES[5].color} radius={[0, 4, 4, 0]} maxBarSize={11} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
};

/** Stacked bars over time: when candidates arrived, and from which portal. */
const CandidatesOverTime = ({ trend, sources }) => {
  const points = (trend?.points || []).map((p) => ({ label: p.label, ...p.counts }));
  const any = points.some((p) => sources.some((s) => p[s.source]));
  const per = trend?.interval === 'month' ? 'month' : 'week';
  return (
    <ChartCard title="Candidates over time" hint={`New candidates each ${per}, split by job portal — which channels are picking up or drying up.`}>
      {!any ? <ChartEmpty>No candidates in this period.</ChartEmpty> : (
        <div style={{ height: Math.max(200, sources.length * 60 + 50) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={points} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="label" tick={TICK} axisLine={false} tickLine={false} minTickGap={8} />
              <YAxis tick={TICK} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip content={<ChartTip />} cursor={{ fill: 'var(--input-bg)' }} />
              <Legend {...LEGEND} />
              {sources.map((s, i) => (
                <Bar key={s.platform} dataKey={s.source} stackId="src" fill={platformColor(s.platform)} maxBarSize={34}
                  radius={i === sources.length - 1 ? [4, 4, 0, 0] : 0} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
};

const SourceCharts = ({ data }) => {
  const sources = data?.sources || [];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <div className="xl:col-span-2 min-w-0"><FunnelByPortal sources={sources} /></div>
        <div className="min-w-0"><ShareOfCandidates sources={sources} total={data?.totals?.applied || 0} /></div>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <ConversionByPortal sources={sources} />
        <CandidatesOverTime trend={data?.trend} sources={sources} />
      </div>
    </div>
  );
};

export default SourceCharts;
