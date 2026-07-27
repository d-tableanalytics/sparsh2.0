import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, Download, ClipboardCheck, Users, Star, Search, LayoutGrid, LineChart as LineIcon, MessageSquare, AlertTriangle,
} from 'lucide-react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import { DashboardHero, HeroButton, Section, KpiTile, FilterSelect } from './dashboardKit';
import { useAuth } from '../../../context/AuthContext';
import { getReviewReports, currentPeriod, periodLabel } from '../../../services/tpmsApi';
import api from '../../../services/api';

/* ─────────────────────────────────────────────────────────────
   Review Report — review-form responses with a Cards view and a
   Monthly Trend chart. Shared by the Admin panel and SMOPS panel.
   Data comes from GET /tpms/reports/reviews (per-respondent
   submissions + monthly score trend); see tpms_dashboard_service
   .get_review_reports for the response shape.
   ───────────────────────────────────────────────────────────── */

// Fallback form list so the source selector renders before the first fetch.
const DEFAULT_SOURCES = [
  { id: 'accountability', label: 'Accountability Rating' },
  { id: 'ownership', label: 'Ownership Rating' },
  { id: 'culture', label: 'Culture Rating' },
  { id: 'implementation_feedback', label: 'Implementation Update Feedback' },
];

// Last 12 months as { id: 'YYYY-MM', name: 'Jul26' } for the period picker.
const monthOptions = () => {
  const out = [{ id: '', name: 'All Periods' }];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const id = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    out.push({ id, name: periodLabel(id) || id });
  }
  return out;
};

// Status bands mirror the backend (≥85 strong / ≥70 moderate / below).
const scoreColor = (p) => (p >= 85 ? 'var(--accent-green)' : p >= 70 ? 'var(--accent-orange)' : 'var(--accent-red)');
const initials = (name) => (name || '?').split(' ').filter(Boolean).map((x) => x[0]).join('').slice(0, 2).toUpperCase();

const Stars = ({ value }) => (
  <span className="inline-flex items-center gap-0.5">
    {[1, 2, 3, 4, 5].map((i) => (
      <Star key={i} size={13} style={{ color: 'var(--accent-yellow)', fill: i <= Math.round(value) ? 'var(--accent-yellow)' : 'transparent' }} className={i <= Math.round(value) ? '' : 'opacity-30'} />
    ))}
  </span>
);

const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 shadow-lg">
      <p className="text-[11px] font-bold text-[var(--text-muted)] mb-1">{label}</p>
      <p className="text-[12px] font-bold text-[var(--accent-indigo)]">Avg score: {payload[0].value}%</p>
    </div>
  );
};

const ReviewReport = ({ title = 'Review Reports', subtitle = 'Evaluation & feedback responses across teams' }) => {
  useAuth(); // ensure an authenticated context; server scopes results by role.

  const periods = useMemo(() => monthOptions(), []);

  const [view, setView] = useState('cards');
  const [source, setSource] = useState('accountability');
  const [period, setPeriod] = useState(currentPeriod());
  const [companyId, setCompanyId] = useState('');
  const [respondentId, setRespondentId] = useState('');
  const [q, setQ] = useState('');

  const [companies, setCompanies] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Companies list for the picker (loaded once; server still scopes by role).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.get('/companies');
        if (alive) setCompanies(res.data || []);
      } catch {
        if (alive) setCompanies([]);
      }
    })();
    return () => { alive = false; };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = { source: source || 'accountability' };
      if (period) params.period = period;
      if (companyId) params.company_id = companyId;
      const res = await getReviewReports(params);
      setData(res.data);
    } catch (e) {
      setData(null);
      setError(e.response?.data?.detail || 'Failed to load review reports');
    } finally {
      setLoading(false);
    }
  }, [source, period, companyId]);

  // Fetch on mount + whenever source / period / company change.
  useEffect(() => { load(); }, [load]);

  const sources = data?.sources?.length ? data.sources : DEFAULT_SOURCES;
  const totals = data?.totals || {};
  const isYesno = !!data?.is_yesno;
  const sourceMeta = data?.source || {};

  // M7 — form-appropriate status vocabulary. Checklist (yes/no) forms read as
  // compliance; rating (matrix) forms read as review health. Thresholds match
  // the backend bands (≥85 / ≥70 / below).
  const isChecklist = isYesno || (source || '') === 'implementation_feedback';
  const statusVocab = isChecklist
    ? { high: 'Compliant', mid: 'Partial', low: 'At Risk' }
    : { high: 'Strong', mid: 'Healthy', low: 'Needs Focus' };
  const statusLabel = (p) => (p >= 85 ? statusVocab.high : p >= 70 ? statusVocab.mid : statusVocab.low);

  const companyOpts = useMemo(
    () => [{ id: '', name: 'All Companies' }, ...companies.map((c) => ({ id: String(c._id || c.id), name: c.name }))],
    [companies],
  );
  const respondentOpts = useMemo(
    () => [{ id: '', name: 'All Respondents' },
      ...(data?.respondent_options || []).map((r) => ({ id: String(r.id), name: r.name }))],
    [data],
  );

  // Respondent + search are refined client-side over the fetched entries.
  const rows = useMemo(() => {
    const entries = data?.entries || [];
    const needle = q.trim().toLowerCase();
    return entries.filter((e) => {
      if (respondentId && String(e.respondent_id) !== String(respondentId)) return false;
      if (!needle) return true;
      const names = e.matrix ? (e.employees || []).map((emp) => emp.name).join(' ') : '';
      return `${e.name} ${e.company} ${names}`.toLowerCase().includes(needle);
    });
  }, [data, respondentId, q]);

  const kpis = [
    { value: totals.responses ?? 0, label: 'Responses', sub: 'Submitted', tone: 'blue', icon: ClipboardCheck },
    { value: totals.respondent_count ?? 0, label: 'Respondents', sub: 'Reviewers', tone: 'green', icon: Users },
    isYesno
      ? { value: totals.yes_pct === '' || totals.yes_pct == null ? '—' : `${totals.yes_pct}%`, label: 'Yes Rate', sub: 'Checklist', tone: 'yellow', icon: Star }
      : { value: totals.avg_rating === '' || totals.avg_rating == null ? '—' : totals.avg_rating, label: 'Avg Rating', sub: 'Out of 5', tone: 'yellow', icon: Star },
  ];

  // Monthly trend: average score % across rated people per period (ascending).
  const trendData = useMemo(() => {
    const trend = data?.trend || { periods: [], people: [] };
    const ps = [...(trend.periods || [])].reverse();
    const people = trend.people || [];
    return ps.map((p) => {
      const vals = people
        .map((pp) => pp.scores?.[p.id])
        .filter((v) => typeof v === 'number');
      const avg = vals.length ? Math.round(vals.reduce((a, v) => a + v, 0) / vals.length) : null;
      return { m: p.name, rating: avg };
    });
  }, [data]);

  // M6 — export the currently filtered entries as a CSV file, built client-side.
  const exportCsv = useCallback(() => {
    const cell = (v) => {
      const s = v == null ? '' : String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lastHeader = isYesno ? 'Yes %' : 'Avg Rating';
    const header = ['Respondent', 'Company', 'Period', 'Score %', lastHeader];
    const table = [header, ...rows.map((r) => {
      const last = isYesno
        ? (r.total ? Math.round(((r.yes || 0) / r.total) * 100) : (r.score_pct ?? ''))
        : (r.avg ?? '');
      return [r.name ?? '', r.company ?? '', r.period_label || r.period || '', r.score_pct ?? '', last];
    })];
    const csv = table.map((row) => row.map(cell).join(',')).join('\r\n');
    const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const date = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `tpms-review-${source || 'form'}-${date}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [rows, isYesno, source]);

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={ClipboardCheck} title={title} subtitle={subtitle}>
        <div className="flex items-center gap-1 bg-white/20 p-1 rounded-lg">
          {[{ k: 'cards', label: 'Cards', icon: LayoutGrid }, { k: 'trend', label: 'Monthly Trend', icon: LineIcon }].map((v) => (
            <button key={v.k} onClick={() => setView(v.k)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-bold transition-all ${view === v.k ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-white/80 hover:text-white'}`}>
              <v.icon size={13} /> {v.label}
            </button>
          ))}
        </div>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
        <HeroButton icon={Download} onClick={exportCsv}>Export CSV</HeroButton>
      </DashboardHero>

      {/* KPI tiles */}
      <div className="grid grid-cols-3 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Filter bar */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4">
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3 items-end">
          {[
            { label: 'Form', value: source, set: setSource, opts: sources.map((s) => ({ id: s.id, name: s.label })) },
            { label: 'Period', value: period, set: setPeriod, opts: periods },
            { label: 'Company', value: companyId, set: setCompanyId, opts: companyOpts },
            { label: 'Respondent', value: respondentId, set: setRespondentId, opts: respondentOpts },
          ].map((f) => (
            <label key={f.label} className="flex flex-col gap-1">
              <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{f.label}</span>
              <FilterSelect value={f.value} onChange={f.set} options={f.opts} />
            </label>
          ))}
          <label className="flex flex-col gap-1 col-span-2 md:col-span-1">
            <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Search</span>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Respondent, company, employee…"
                className="w-full pl-9 pr-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]" />
            </div>
          </label>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="py-24 flex flex-col items-center justify-center text-[var(--text-muted)]">
          <RefreshCw size={26} className="animate-spin mb-3 opacity-60" />
          <p className="text-[13px] font-bold">Loading review reports…</p>
        </div>
      ) : view === 'trend' ? (
        <Section title="Monthly Score Trend" subtitle="Average review score % over time" icon={LineIcon}>
          <div className="px-2 py-5 h-[320px]">
            {trendData.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-[var(--text-muted)]">
                <AlertTriangle size={24} className="mb-2 opacity-40" />
                <p className="text-[13px] font-bold">No trend data for this selection.</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="m" tick={{ fontSize: 11, fontWeight: 700, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11, fontWeight: 700, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Line type="monotone" dataKey="rating" stroke="var(--accent-indigo)" strokeWidth={2.5} dot={{ r: 4, fill: 'var(--accent-indigo)' }} activeDot={{ r: 6 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </Section>
      ) : rows.length === 0 ? (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm py-16 text-center">
          <MessageSquare size={26} className="mx-auto text-[var(--text-muted)]" />
          <p className="text-[13px] font-bold mt-3">No responses match these filters.</p>
          <p className="text-[12px] text-[var(--text-muted)] mt-1">Try a different form, period, company or respondent.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {rows.map((r, i) => {
            const pctVal = Number(r.score_pct) || 0;
            return (
              <div key={`${r.respondent_id}-${r.period}-${i}`} className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4 flex flex-col hover:shadow-md transition-all">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="w-9 h-9 rounded-xl text-white text-[11px] font-bold flex items-center justify-center shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                      {initials(r.name)}
                    </span>
                    <div className="min-w-0">
                      <p className="text-[13.5px] font-bold truncate">{r.name || '—'}</p>
                      <p className="text-[11px] text-[var(--text-muted)] truncate">{r.company || '—'}</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-bold px-2 py-1 rounded-md shrink-0 tabular-nums" style={{ color: 'var(--accent-indigo)', background: 'var(--input-bg)' }}>{r.period_label || r.period}</span>
                </div>

                <div className="flex items-center gap-2 mt-3">
                  {!isYesno && r.avg !== '' && r.avg != null && <Stars value={Number(r.avg)} />}
                  <span className="text-[13px] font-extrabold tabular-nums" style={{ color: scoreColor(pctVal) }}>{pctVal}%</span>
                  {statusLabel(pctVal) && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ color: scoreColor(pctVal), background: `${scoreColor(pctVal)}1a` }}>{statusLabel(pctVal)}</span>
                  )}
                </div>

                {/* Matrix: per-employee scores · Checklist: per-question answers */}
                <div className="mt-3 flex-1 max-h-56 overflow-y-auto no-scrollbar space-y-1.5">
                  {isYesno
                    ? (r.items || []).map((it, k) => (
                      <div key={k} className="flex items-center justify-between gap-2 text-[12px]">
                        <span className="text-[var(--text-main)] truncate">{it.question}</span>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0" style={{ color: it.yes ? 'var(--accent-green)' : 'var(--accent-red)', background: it.yes ? 'var(--accent-green-bg)' : 'var(--accent-red-bg)' }}>{it.answer}</span>
                      </div>
                    ))
                    : (r.employees || []).map((emp) => (
                      <div key={emp.id} className="flex items-center justify-between gap-2 text-[12px]">
                        <span className="text-[var(--text-main)] truncate">{emp.name}</span>
                        <span className="text-[11px] font-extrabold tabular-nums shrink-0" style={{ color: scoreColor(Number(emp.score_pct) || 0) }}>{emp.score_pct}%</span>
                      </div>
                    ))}
                </div>

                <div className="flex items-center justify-between mt-3 pt-3 border-t border-[var(--border)] text-[11px] font-medium text-[var(--text-muted)]">
                  <span>{isYesno ? `${r.yes ?? 0}/${r.total ?? 0} yes` : `${(r.employees || []).length} rated`}</span>
                  <span className="tabular-nums">{sourceMeta.label || ''}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* M6 — Grand Total summary (from server totals across the fetched set). */}
      {!loading && view === 'cards' && (
        <Section title="Grand Total" subtitle="Overall totals for the current form & filters" icon={ClipboardCheck}>
          <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-[var(--border)]">
            {[
              { label: 'Total Responses', value: totals.responses ?? 0 },
              { label: 'Respondents', value: totals.respondent_count ?? 0 },
              isYesno
                ? { label: 'Overall Yes %', value: totals.yes_pct === '' || totals.yes_pct == null ? '—' : `${totals.yes_pct}%` }
                : { label: 'Overall Avg Rating', value: totals.avg_rating === '' || totals.avg_rating == null ? '—' : totals.avg_rating },
            ].map((c) => (
              <div key={c.label} className="px-5 py-4 flex flex-col gap-1">
                <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{c.label}</span>
                <span className="text-[20px] font-extrabold tabular-nums text-[var(--text-main)]">{c.value}</span>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
};

export default ReviewReport;
