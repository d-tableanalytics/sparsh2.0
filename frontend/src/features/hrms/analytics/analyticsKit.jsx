import React from 'react';
import { useNavigate } from 'react-router-dom';
import { TrendingDown } from 'lucide-react';
import { CARD, SECTION_TITLE, nf } from './analyticsKit';

/**
 * HRMS ▸ shared analytics presentation pieces.
 *
 * Layout and rendering only — every number arrives already computed and already
 * role-scoped from the server. Nothing here derives, filters or totals anything, which is
 * the whole point of Phase 10: the source HRMS computed its figures in the browser, so no
 * two screens agreed and none of them could be role-scoped
 * (FRONTEND_ANALYSIS §6.1).
 *
 * Styled with the ERP's CSS variables so it inherits light/dark theming, matching
 * components/reports/chartKit.js rather than carrying its own palette.
 */

/** A headline number. Clickable when the server supplied a deep link — a KPI you cannot
 *  click through to is a number the reader has to take on trust. */
export const KpiCard = ({ kpi }) => {
  const navigate = useNavigate();
  const clickable = !!kpi.link;
  return (
    <button
      type="button"
      disabled={!clickable}
      onClick={() => clickable && navigate(kpi.link)}
      className={`${CARD} text-left transition-colors ${
        clickable
          ? 'hover:border-[var(--accent-indigo)] cursor-pointer'
          : 'cursor-default'
      }`}
    >
      <p className={SECTION_TITLE}>{kpi.label}</p>
      <p className="mt-1.5 text-2xl font-bold text-[var(--text-main)] tabular-nums">
        {nf(kpi.value)}
      </p>
      {kpi.hint && (
        <p className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">{kpi.hint}</p>
      )}
    </button>
  );
};

/**
 * The hiring funnel.
 *
 * Deliberately CSS bars rather than a recharts FunnelChart: the shape is eight horizontal
 * bars with two labels each, and recharts adds no interaction worth ~100 kB here.
 * Percentages come from the server, so the chart and the API can never disagree.
 */
export const FunnelChart = ({ stages }) => {
  const top = stages?.[0]?.count || 0;
  return (
    <div className="space-y-2.5">
      {(stages || []).map((s) => (
        <div key={s.key}>
          <div className="flex items-baseline justify-between gap-3 mb-1">
            <span className="text-[12.5px] font-semibold text-[var(--text-main)]">
              {s.label}
            </span>
            <span className="text-[11.5px] text-[var(--text-muted)] tabular-nums">
              <strong className="text-[var(--text-main)]">{nf(s.count)}</strong>
              {' · '}{s.of_total}% of applied
              {' · '}{s.from_previous}% from previous
            </span>
          </div>
          <div className="h-2.5 rounded-full bg-[var(--input-bg)] overflow-hidden">
            <div
              className="h-full rounded-full bg-[var(--accent-indigo)] transition-all"
              style={{ width: `${top ? Math.max((s.count / top) * 100, s.count ? 1.5 : 0) : 0}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
};

/** A ranked list with proportional bars — sources, departments, platforms. */
export const BarList = ({ rows, emptyLabel = 'No data in this period.' }) => {
  const max = Math.max(1, ...(rows || []).map((r) => r.count));
  if (!rows?.length) {
    return <p className="text-[12.5px] text-[var(--text-muted)]">{emptyLabel}</p>;
  }
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.name} className="flex items-center gap-3">
          <span className="w-32 shrink-0 truncate text-[12.5px] text-[var(--text-main)]"
            title={r.name}>
            {r.name}
          </span>
          <div className="flex-1 h-2 rounded-full bg-[var(--input-bg)] overflow-hidden">
            <div className="h-full rounded-full bg-[var(--accent-indigo)]"
              style={{ width: `${(r.count / max) * 100}%` }} />
          </div>
          <span className="w-20 shrink-0 text-right text-[11.5px] text-[var(--text-muted)] tabular-nums">
            {nf(r.count)} · {r.share}%
          </span>
        </div>
      ))}
    </div>
  );
};

/** A small labelled figure inside a card. */
export const MiniStat = ({ label, value, tone }) => (
  <div>
    <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
      {label}
    </p>
    <p className={`text-[17px] font-bold tabular-nums ${
      tone === 'danger' ? 'text-[var(--accent-red)]'
        : tone === 'good' ? 'text-[var(--accent-green,var(--accent-indigo))]'
        : 'text-[var(--text-main)]'}`}>
      {value}
    </p>
  </div>
);

/** Shown to a hiring manager, so they never read own-scope numbers as company-wide. */
export const ScopeNotice = () => (
  <div className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2">
    <TrendingDown size={14} className="mt-0.5 shrink-0 text-[var(--text-muted)]" />
    <p className="text-[11.5px] text-[var(--text-muted)]">
      These figures cover <strong>the requisitions you raised</strong>, not the whole
      company.
    </p>
  </div>
);

/** From/to pickers. Kept dumb — the server validates and bounds the range. */
export const RangePicker = ({ value, onChange }) => (
  <div className="flex flex-wrap items-center gap-2">
    {[['from', 'From'], ['to', 'To']].map(([key, label]) => (
      <label key={key} className="flex items-center gap-1.5 text-[11.5px] text-[var(--text-muted)]">
        {label}
        <input
          type="date"
          value={value[key] || ''}
          onChange={(e) => onChange({ ...value, [key]: e.target.value })}
          className="h-8 px-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12px] text-[var(--text-main)]"
        />
      </label>
    ))}
    {(value.from || value.to) && (
      <button
        type="button"
        onClick={() => onChange({ from: '', to: '' })}
        className="h-8 px-2.5 rounded-lg border border-[var(--border)] text-[11.5px] font-semibold text-[var(--text-muted)] hover:text-[var(--text-main)]"
      >
        Last 90 days
      </button>
    )}
  </div>
);
