import React, { useState } from 'react';
import { Radar, CalendarRange } from 'lucide-react';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import SourceOutcomes from './SourceOutcomes';

/**
 * Internal Hiring ▸ Reports ▸ Source Analytics.
 *
 * Per job portal: Applied -> Shortlisted -> Connected -> Interviewed -> Selected -> Hired.
 * This shell owns the page header and the date range; SourceOutcomes owns the rest.
 */
const iso = (d) => d.toISOString().slice(0, 10);
const daysAgo = (n) => iso(new Date(Date.now() - n * 86400000));
const PRESETS = [['30 days', 30], ['90 days', 90], ['6 months', 182], ['1 year', 365]];
const DATE = 'h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[12px] text-[var(--text-main)]';

const SourceAnalytics = () => {
  const [from, setFrom] = useState(daysAgo(90));
  const [to, setTo] = useState(iso(new Date()));
  const today = iso(new Date());
  const activePreset = to === today ? PRESETS.find(([, n]) => from === daysAgo(n))?.[1] : null;

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Radar}
        title="Source Analytics"
        subtitle="Which job portal brings Sparsh Magic's candidates — and how far they get: shortlisted, connected, interviewed, hired."
      />
      <HrmsScopeBar />

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mr-1">
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
          <input type="date" aria-label="From" className={DATE} value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
          <span className="text-[11px] text-[var(--text-muted)]">to</span>
          <input type="date" aria-label="To" className={DATE} value={to} min={from} max={today} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>

      <SourceOutcomes from={from} to={to} />
    </div>
  );
};

export default SourceAnalytics;
